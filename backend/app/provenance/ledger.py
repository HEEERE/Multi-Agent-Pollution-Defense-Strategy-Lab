from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Iterable

from app.provenance.models import (
    ArtifactKind,
    ArtifactState,
    ArtifactVersion,
    ActivityRecord,
    Derivation,
    LabelEnforcementRecord,
    ProvenanceLevel,
    ProvenanceSnapshot,
    StateTransition,
    SupportGroup,
    TaintClass,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS provenance_runs (
  run_id TEXT PRIMARY KEY, policy_version TEXT NOT NULL DEFAULT 'v1',
  ledger_seq INTEGER NOT NULL DEFAULT 0, state_seq INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS artifact_versions (
  version_id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL, run_id TEXT NOT NULL,
  kind TEXT NOT NULL, value_hash TEXT NOT NULL, origin_principals TEXT NOT NULL,
  integrity TEXT NOT NULL, confidentiality TEXT NOT NULL, scope TEXT NOT NULL,
  expiry REAL, derivation_ids TEXT NOT NULL, taint_class TEXT NOT NULL,
  metadata TEXT NOT NULL, created_seq INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS provenance_relations (
  relation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, child_version_id TEXT NOT NULL,
  parent_version_ids TEXT NOT NULL, activity_id TEXT NOT NULL, relation_type TEXT NOT NULL,
  seq INTEGER NOT NULL, parent_roles TEXT NOT NULL DEFAULT '[]',
  provenance_level TEXT NOT NULL DEFAULT 'P0', effect_class TEXT NOT NULL DEFAULT 'E0'
);
CREATE TABLE IF NOT EXISTS activities (
  activity_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, actor_agent_id TEXT NOT NULL,
  kind TEXT NOT NULL, visible_input_ids TEXT NOT NULL, tool_id TEXT, operation TEXT,
  effect_class TEXT NOT NULL, seq INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS state_transitions (
  transition_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, version_id TEXT NOT NULL,
  from_state TEXT, to_state TEXT NOT NULL, seq INTEGER NOT NULL,
  reason TEXT NOT NULL, action_id TEXT
);
CREATE TABLE IF NOT EXISTS ledger_events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
  event_type TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS support_groups (
  support_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, goal_id TEXT NOT NULL,
  verifier_id TEXT NOT NULL, verified INTEGER NOT NULL,
  provenance_level TEXT NOT NULL, seq INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS support_members (
  support_id TEXT NOT NULL, version_id TEXT NOT NULL,
  PRIMARY KEY (support_id, version_id)
);
CREATE TABLE IF NOT EXISTS evidence_records (
  record_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, action_id TEXT,
  evidence_type TEXT NOT NULL, source TEXT NOT NULL, outcome TEXT NOT NULL,
  details TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS decision_records (
  record_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, action_id TEXT NOT NULL,
  decision TEXT NOT NULL, reason_code TEXT NOT NULL, snapshot_hash TEXT,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS action_records (
  record_id INTEGER PRIMARY KEY AUTOINCREMENT, action_id TEXT NOT NULL,
  run_id TEXT NOT NULL, lifecycle TEXT NOT NULL, request_hash TEXT NOT NULL,
  effect_class TEXT NOT NULL, resource_scope TEXT NOT NULL,
  idempotency_key TEXT, details TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_action_idempotency
  ON action_records(run_id, idempotency_key, lifecycle)
  WHERE idempotency_key IS NOT NULL AND idempotency_key <> '' AND lifecycle = 'executed';
CREATE TABLE IF NOT EXISTS certificates (
  certificate_hash TEXT PRIMARY KEY, run_id TEXT NOT NULL,
  certificate_kind TEXT NOT NULL, pre_snapshot_hash TEXT NOT NULL,
  post_state_hash TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS label_enforcements (
  enforcement_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, version_id TEXT NOT NULL,
  certificate_hash TEXT NOT NULL, confidentiality TEXT NOT NULL,
  blocked_effects TEXT NOT NULL, seq INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS denial_records (
  record_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, action_id TEXT NOT NULL,
  public_reason TEXT NOT NULL, internal_reason TEXT NOT NULL,
  latency_bucket_ms INTEGER NOT NULL, budget_charge INTEGER NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS compensation_records (
  record_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, action_id TEXT NOT NULL,
  effect_class TEXT NOT NULL, status TEXT NOT NULL, details TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS metrics (
  run_id TEXT NOT NULL, name TEXT NOT NULL, value REAL NOT NULL,
  updated_at REAL NOT NULL, PRIMARY KEY(run_id, name)
);
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY, applied_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pv_run ON artifact_versions(run_id);
CREATE INDEX IF NOT EXISTS idx_pr_child ON provenance_relations(child_version_id);
CREATE INDEX IF NOT EXISTS idx_st_version ON state_transitions(version_id, seq);
CREATE INDEX IF NOT EXISTS idx_activity_run ON activities(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_action_run ON action_records(run_id, action_id);
CREATE VIEW IF NOT EXISTS v_artifact_state AS
SELECT av.version_id,
       (SELECT st.to_state FROM state_transitions st
        WHERE st.version_id = av.version_id ORDER BY st.seq DESC LIMIT 1) AS state,
       (SELECT MAX(st2.seq) FROM state_transitions st2
        WHERE st2.version_id = av.version_id) AS state_seq
FROM artifact_versions av;
"""


class ProvenanceLedger:
    """Small append-only repository used by the runtime and tests.

    The ledger never updates an artifact version or transition. Current state is
    derived from the latest transition, and snapshot hashes include both
    sequence counters so a preflight check cannot be reused after a mutation.
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        self._lock = RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._transaction_depth = 0
        self._migrate_legacy_schema()
        self._conn.commit()

    def _migrate_legacy_schema(self) -> None:
        columns = {
            row[1] for row in self._conn.execute("PRAGMA table_info(provenance_relations)")
        }
        additions = {
            "parent_roles": "TEXT NOT NULL DEFAULT '[]'",
            "provenance_level": "TEXT NOT NULL DEFAULT 'P0'",
            "effect_class": "TEXT NOT NULL DEFAULT 'E0'",
        }
        for name, ddl in additions.items():
            if name not in columns:
                self._conn.execute(
                    f"ALTER TABLE provenance_relations ADD COLUMN {name} {ddl}"
                )
        self._conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (1, ?)",
            (time.time(),),
        )

    @contextmanager
    def atomic(self):
        """Nestable transaction used for graph, state and certificate commits."""
        with self._lock:
            outermost = self._transaction_depth == 0
            if outermost:
                self._conn.execute("BEGIN IMMEDIATE")
            self._transaction_depth += 1
            try:
                yield self
            except Exception:
                self._transaction_depth -= 1
                if outermost:
                    self._conn.rollback()
                raise
            else:
                self._transaction_depth -= 1
                if outermost:
                    self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def ensure_run(self, run_id: str, policy_version: str = "v1") -> None:
        with self.atomic():
            self._conn.execute(
                "INSERT OR IGNORE INTO provenance_runs(run_id, policy_version, created_at) VALUES (?, ?, ?)",
                (run_id, policy_version, time.time()),
            )

    def run_exists(self, run_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM provenance_runs WHERE run_id=? LIMIT 1", (run_id,)
        ).fetchone() is not None

    def _next_ledger_seq(self, run_id: str) -> int:
        row = self._conn.execute("SELECT ledger_seq FROM provenance_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            self.ensure_run(run_id)
            row = self._conn.execute("SELECT ledger_seq FROM provenance_runs WHERE run_id=?", (run_id,)).fetchone()
        seq = int(row[0]) + 1
        self._conn.execute("UPDATE provenance_runs SET ledger_seq=? WHERE run_id=?", (seq, run_id))
        return seq

    def append_artifact(self, artifact: ArtifactVersion) -> ArtifactVersion:
        with self.atomic():
            seq = self._next_ledger_seq(artifact.run_id)
            self._conn.execute(
                "INSERT INTO artifact_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (artifact.version_id, artifact.artifact_id, artifact.run_id, artifact.kind.value,
                 artifact.value_hash, json.dumps(sorted(artifact.origin_principals)), artifact.integrity,
                 artifact.confidentiality, artifact.scope, artifact.expiry, json.dumps(list(artifact.derivation_ids)),
                 artifact.taint_class.value, json.dumps(artifact.metadata, sort_keys=True), seq),
            )
            self._conn.execute("INSERT INTO ledger_events(run_id,event_type,payload,created_at) VALUES (?,?,?,?)",
                               (artifact.run_id, "artifact_version", json.dumps({"version_id": artifact.version_id}), time.time()))
            state_row = self._conn.execute("SELECT state_seq FROM provenance_runs WHERE run_id=?", (artifact.run_id,)).fetchone()
            state_seq = int(state_row[0]) + 1
            self._conn.execute("UPDATE provenance_runs SET state_seq=? WHERE run_id=?", (state_seq, artifact.run_id))
            self._conn.execute(
                "INSERT INTO state_transitions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"init_{artifact.version_id}", artifact.run_id, artifact.version_id, None,
                 ArtifactState.ACTIVE.value, state_seq, "artifact_committed", None),
            )
        return artifact

    def append_derivation(self, derivation: Derivation) -> Derivation:
        with self.atomic():
            seq = self._next_ledger_seq(derivation.run_id)
            self._conn.execute(
                """INSERT INTO provenance_relations(
                     relation_id,run_id,child_version_id,parent_version_ids,
                     activity_id,relation_type,seq,parent_roles,provenance_level,effect_class
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (derivation.relation_id, derivation.run_id, derivation.child_version_id,
                 json.dumps(list(derivation.parent_version_ids)), derivation.activity_id,
                 derivation.relation_type, seq, json.dumps(list(derivation.parent_roles)),
                 derivation.provenance_level.value, derivation.effect_class),
            )
        return derivation

    def append_activity(self, activity: ActivityRecord) -> ActivityRecord:
        with self.atomic():
            seq = self._next_ledger_seq(activity.run_id)
            if activity.seq != seq:
                activity = ActivityRecord(
                    activity.activity_id, activity.run_id, activity.actor_agent_id,
                    activity.kind, activity.visible_input_ids, activity.tool_id,
                    activity.operation, activity.effect_class, seq,
                )
            self._conn.execute(
                "INSERT INTO activities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (activity.activity_id, activity.run_id, activity.actor_agent_id,
                 activity.kind, json.dumps(list(activity.visible_input_ids)),
                 activity.tool_id, activity.operation, activity.effect_class, activity.seq),
            )
        return activity

    def append_support_group(self, support: SupportGroup) -> SupportGroup:
        if support.provenance_level is ProvenanceLevel.P2 and support.verified:
            raise ValueError("P2 support cannot be verified authority")
        with self.atomic():
            seq = self._next_ledger_seq(support.run_id)
            self._conn.execute(
                "INSERT INTO support_groups VALUES (?, ?, ?, ?, ?, ?, ?)",
                (support.support_id, support.run_id, support.goal_id,
                 support.verifier_id, int(support.verified),
                 support.provenance_level.value, seq),
            )
            self._conn.executemany(
                "INSERT INTO support_members VALUES (?, ?)",
                [(support.support_id, version_id) for version_id in support.member_version_ids],
            )
        return support

    def transition_state(self, transition: StateTransition) -> StateTransition:
        with self.atomic():
            artifact = self.get_artifact(transition.version_id)
            if artifact is None:
                raise KeyError(transition.version_id)
            current = self.current_state(transition.version_id)
            # State transitions are append-only, but not arbitrary. In
            # particular an invalidated/retained version can never be silently
            # reactivated, which prevents recovery from laundering old data.
            expected = current or ArtifactState.ACTIVE
            if transition.from_state not in {None, expected}:
                raise ValueError(
                    f"state precondition failed for {transition.version_id}: "
                    f"expected {expected.value}, got {transition.from_state.value}"
                )
            allowed = {
                ArtifactState.ACTIVE: {ArtifactState.QUARANTINED, ArtifactState.INVALIDATED, ArtifactState.RETAINED},
                ArtifactState.QUARANTINED: {ArtifactState.INVALIDATED, ArtifactState.RECOVERED},
                ArtifactState.RETAINED: {ArtifactState.INVALIDATED},
                ArtifactState.RECOVERED: {ArtifactState.INVALIDATED},
                ArtifactState.INVALIDATED: set(),
            }
            if transition.to_state not in allowed[expected]:
                raise ValueError(
                    f"illegal state transition {expected.value}->{transition.to_state.value}"
                )
            row = self._conn.execute("SELECT state_seq FROM provenance_runs WHERE run_id=?", (transition.run_id,)).fetchone()
            if row is None:
                self.ensure_run(transition.run_id)
                row = (0,)
            seq = int(row[0]) + 1
            if transition.seq != seq:
                transition = StateTransition(transition.transition_id, transition.run_id, transition.version_id,
                                              transition.from_state, transition.to_state, seq, transition.reason, transition.action_id)
            self._conn.execute("UPDATE provenance_runs SET state_seq=? WHERE run_id=?", (seq, transition.run_id))
            self._conn.execute("INSERT INTO state_transitions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               (transition.transition_id, transition.run_id, transition.version_id,
                                transition.from_state.value if transition.from_state else None,
                                transition.to_state.value, transition.seq, transition.reason, transition.action_id))
        return transition

    def current_state(self, version_id: str) -> ArtifactState | None:
        row = self._conn.execute("SELECT to_state FROM state_transitions WHERE version_id=? ORDER BY seq DESC LIMIT 1", (version_id,)).fetchone()
        return ArtifactState(row[0]) if row else None

    def get_artifact(self, version_id: str) -> ArtifactVersion | None:
        row = self._conn.execute("SELECT * FROM artifact_versions WHERE version_id=?", (version_id,)).fetchone()
        if not row:
            return None
        return ArtifactVersion(row["version_id"], row["artifact_id"], row["run_id"], ArtifactKind(row["kind"]), row["value_hash"],
                               frozenset(json.loads(row["origin_principals"])), row["integrity"], row["confidentiality"],
                               row["scope"], row["expiry"], tuple(json.loads(row["derivation_ids"])),
                               TaintClass(row["taint_class"]),
                               json.loads(row["metadata"]))

    def version_ids(self, run_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT version_id FROM artifact_versions WHERE run_id=? ORDER BY created_seq", (run_id,)
        ).fetchall()
        return [row[0] for row in rows]

    def list_artifacts(self, run_id: str) -> list[ArtifactVersion]:
        rows = self._conn.execute("SELECT version_id FROM artifact_versions WHERE run_id=? ORDER BY created_seq", (run_id,)).fetchall()
        return [artifact for row in rows if (artifact := self.get_artifact(row[0])) is not None]

    def list_derivations(self, run_id: str) -> list[Derivation]:
        rows = self._conn.execute("SELECT * FROM provenance_relations WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
        return [Derivation(
            r["relation_id"], r["run_id"], r["child_version_id"],
            tuple(json.loads(r["parent_version_ids"])), r["activity_id"],
            r["relation_type"], tuple(json.loads(r["parent_roles"])),
            ProvenanceLevel(r["provenance_level"]), r["effect_class"],
        ) for r in rows]

    def list_activities(self, run_id: str) -> list[ActivityRecord]:
        rows = self._conn.execute(
            "SELECT * FROM activities WHERE run_id=? ORDER BY seq", (run_id,)
        ).fetchall()
        return [ActivityRecord(
            r["activity_id"], r["run_id"], r["actor_agent_id"], r["kind"],
            tuple(json.loads(r["visible_input_ids"])), r["tool_id"], r["operation"],
            r["effect_class"], r["seq"],
        ) for r in rows]

    def list_support_groups(self, run_id: str, *, verified_only: bool = True) -> list[SupportGroup]:
        sql = "SELECT * FROM support_groups WHERE run_id=?"
        params: tuple = (run_id,)
        if verified_only:
            sql += " AND verified=1 AND provenance_level IN ('P0','P1')"
        sql += " ORDER BY seq"
        rows = self._conn.execute(sql, params).fetchall()
        result: list[SupportGroup] = []
        for row in rows:
            members = self._conn.execute(
                "SELECT version_id FROM support_members WHERE support_id=? ORDER BY version_id",
                (row["support_id"],),
            ).fetchall()
            result.append(SupportGroup(
                row["support_id"], row["run_id"], row["goal_id"],
                tuple(member[0] for member in members), row["verifier_id"],
                bool(row["verified"]), ProvenanceLevel(row["provenance_level"]),
            ))
        return result

    def append_label_enforcement(self, record: LabelEnforcementRecord) -> LabelEnforcementRecord:
        with self.atomic():
            row = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM label_enforcements WHERE run_id=?",
                (record.run_id,),
            ).fetchone()
            seq = int(row[0]) + 1
            if record.seq != seq:
                record = LabelEnforcementRecord(
                    record.enforcement_id, record.run_id, record.version_id,
                    record.certificate_hash, record.confidentiality,
                    record.blocked_effects, seq,
                )
            self._conn.execute(
                "INSERT INTO label_enforcements VALUES (?, ?, ?, ?, ?, ?, ?)",
                (record.enforcement_id, record.run_id, record.version_id,
                 record.certificate_hash, record.confidentiality,
                 json.dumps(list(record.blocked_effects)), record.seq),
            )
        return record

    def has_label_enforcement(self, version_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM label_enforcements WHERE version_id=? LIMIT 1", (version_id,)
        ).fetchone() is not None

    def record_action(self, *, action_id: str, run_id: str, lifecycle: str,
                      request_hash: str, effect_class: str, resource_scope: str,
                      idempotency_key: str = "", details: dict | None = None) -> None:
        with self.atomic():
            self._conn.execute(
                """INSERT INTO action_records(action_id,run_id,lifecycle,request_hash,
                   effect_class,resource_scope,idempotency_key,details,created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (action_id, run_id, lifecycle, request_hash, effect_class,
                 resource_scope, idempotency_key, json.dumps(details or {}, sort_keys=True),
                 time.time()),
            )

    def idempotent_result(self, run_id: str, idempotency_key: str) -> dict | None:
        if not idempotency_key:
            return None
        row = self._conn.execute(
            """SELECT details FROM action_records WHERE run_id=? AND idempotency_key=?
               AND lifecycle='executed' ORDER BY record_id DESC LIMIT 1""",
            (run_id, idempotency_key),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def has_action_lifecycle(self, run_id: str, action_id: str, lifecycle: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM action_records WHERE run_id=? AND action_id=? AND lifecycle=? LIMIT 1",
            (run_id, action_id, lifecycle),
        ).fetchone() is not None

    def record_denial(self, *, record_id: str, run_id: str, action_id: str,
                      public_reason: str, internal_reason: str,
                      latency_bucket_ms: int, budget_charge: int) -> None:
        with self.atomic():
            self._conn.execute(
                "INSERT INTO denial_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (record_id, run_id, action_id, public_reason, internal_reason,
                latency_bucket_ms, budget_charge, time.time()),
            )

    def record_compensation(self, *, record_id: str, run_id: str, action_id: str,
                            effect_class: str, status: str,
                            details: dict | None = None) -> None:
        """Record the required follow-up for an irreversible escape.

        The ledger does not claim compensation succeeded; callers must update
        the status with a new record if an external compensator completes.
        """
        with self.atomic():
            self._conn.execute(
                "INSERT INTO compensation_records VALUES (?, ?, ?, ?, ?, ?, ?)",
                (record_id, run_id, action_id, effect_class, status,
                 json.dumps(details or {}, sort_keys=True, default=str), time.time()),
            )

    def record_decision(self, *, record_id: str, run_id: str, action_id: str,
                        decision: str, reason_code: str, snapshot_hash: str | None) -> None:
        with self.atomic():
            self._conn.execute(
                "INSERT INTO decision_records VALUES (?, ?, ?, ?, ?, ?, ?)",
                (record_id, run_id, action_id, decision, reason_code,
                 snapshot_hash, time.time()),
            )

    def store_certificate(self, certificate_hash: str, run_id: str,
                          certificate_kind: str, pre_snapshot_hash: str,
                          post_state_hash: str, payload: dict) -> None:
        with self.atomic():
            self._conn.execute(
                "INSERT INTO certificates VALUES (?, ?, ?, ?, ?, ?, ?)",
                (certificate_hash, run_id, certificate_kind, pre_snapshot_hash,
                 post_state_hash, json.dumps(payload, sort_keys=True, default=lambda value: sorted(value) if isinstance(value, (set, frozenset, tuple)) else str(value)), time.time()),
            )

    def increment_metric(self, run_id: str, name: str, amount: float = 1.0) -> None:
        with self.atomic():
            self._conn.execute(
                """INSERT INTO metrics(run_id,name,value,updated_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT(run_id,name) DO UPDATE SET
                   value=value+excluded.value, updated_at=excluded.updated_at""",
                (run_id, name, amount, time.time()),
            )

    def metrics(self, run_id: str) -> dict[str, float]:
        rows = self._conn.execute(
            "SELECT name,value FROM metrics WHERE run_id=?", (run_id,)
        ).fetchall()
        return {row["name"]: float(row["value"]) for row in rows}

    def list_action_records(self, run_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM action_records WHERE run_id=? ORDER BY record_id", (run_id,)
        ).fetchall()
        return [self._decoded_row(row, {"details"}) for row in rows]

    def list_denials(self, run_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM denial_records WHERE run_id=? ORDER BY created_at", (run_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def list_decisions(self, run_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM decision_records WHERE run_id=? ORDER BY created_at", (run_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def list_certificates(self, run_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM certificates WHERE run_id=? ORDER BY created_at", (run_id,)
        ).fetchall()
        return [self._decoded_row(row, {"payload"}) for row in rows]

    def list_label_enforcements(self, run_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM label_enforcements WHERE run_id=? ORDER BY seq", (run_id,)
        ).fetchall()
        return [self._decoded_row(row, {"blocked_effects"}) for row in rows]

    def list_state_transitions(self, run_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM state_transitions WHERE run_id=? ORDER BY seq", (run_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def list_compensations(self, run_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM compensation_records WHERE run_id=? ORDER BY created_at", (run_id,)
        ).fetchall()
        return [self._decoded_row(row, {"details"}) for row in rows]

    @staticmethod
    def _decoded_row(row, json_fields: set[str]) -> dict:
        result = dict(row)
        for field in json_fields:
            if field in result:
                result[field] = json.loads(result[field])
        return result

    def storage_bytes(self) -> int:
        page_count = int(self._conn.execute("PRAGMA page_count").fetchone()[0])
        page_size = int(self._conn.execute("PRAGMA page_size").fetchone()[0])
        return page_count * page_size

    def backup(self, destination: str | Path) -> Path:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._conn.commit()
            target = sqlite3.connect(str(path))
            try:
                self._conn.backup(target)
                target.commit()
            finally:
                target.close()
        return path

    def has_low_integrity_ancestor(self, version_id: str) -> bool:
        seen: set[str] = set()
        stack = [version_id]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            artifact = self.get_artifact(current)
            if artifact is not None and artifact.integrity == "low":
                return True
            rows = self._conn.execute(
                "SELECT parent_version_ids FROM provenance_relations WHERE child_version_id=? ORDER BY seq",
                (current,),
            ).fetchall()
            for row in rows:
                stack.extend(json.loads(row[0]))
        return False

    def snapshot(self, run_id: str, *, policy_version: str | None = None, component_versions: dict[str, str] | None = None) -> ProvenanceSnapshot:
        row = self._conn.execute("SELECT ledger_seq,state_seq,policy_version FROM provenance_runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            self.ensure_run(run_id)
            row = self._conn.execute("SELECT ledger_seq,state_seq,policy_version FROM provenance_runs WHERE run_id=?", (run_id,)).fetchone()
        policy = policy_version or row["policy_version"]
        components = tuple(sorted((component_versions or {}).items()))
        material = json.dumps([int(row["ledger_seq"]), int(row["state_seq"]), policy, components], separators=(",", ":"))
        digest = hashlib.sha256(material.encode()).hexdigest()
        return ProvenanceSnapshot(run_id, int(row["ledger_seq"]), int(row["state_seq"]), policy, components, digest)

    def verify_snapshot(self, snapshot: ProvenanceSnapshot) -> bool:
        current = self.snapshot(snapshot.run_id, policy_version=snapshot.policy_version, component_versions=dict(snapshot.component_versions))
        return current.snapshot_hash == snapshot.snapshot_hash

    def events(self, run_id: str) -> list[dict]:
        rows = self._conn.execute("SELECT seq,event_type,payload,created_at FROM ledger_events WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
        return [{"seq": r["seq"], "event_type": r["event_type"], "payload": json.loads(r["payload"]), "created_at": r["created_at"]} for r in rows]
