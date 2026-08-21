from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.event_store import get_event_store
from app.provenance import ProvenanceLedger
from app.provenance.projection import build_conservative, build_tight

router = APIRouter()


@router.get("/{run_id}")
async def get_provenance(run_id: str, mode: str = Query("conservative", pattern="^(conservative|tight)$")) -> dict:
    store = await get_event_store()
    ledger = ProvenanceLedger(store.db_path.with_name("provenance.db"))
    try:
        if not ledger.list_artifacts(run_id):
            raise HTTPException(status_code=404, detail="provenance run not found")
        graph = build_conservative(ledger, run_id) if mode == "conservative" else build_tight(ledger, run_id)
        graph = graph.visible(ledger)
        return {
            "run_id": run_id,
            "mode": mode,
            "snapshot": ledger.snapshot(run_id).snapshot_hash,
            "nodes": [
                {
                    "version_id": v.version_id,
                    "artifact_id": v.artifact_id,
                    "kind": v.kind.value,
                    "integrity": v.integrity,
                    "confidentiality": v.confidentiality,
                    "scope": v.scope,
                    "taint_class": v.taint_class.value,
                    "state": (ledger.current_state(v.version_id) or "active").value
                    if hasattr((ledger.current_state(v.version_id) or "active"), "value")
                    else (ledger.current_state(v.version_id) or "active"),
                    "label_enforced": ledger.has_label_enforcement(v.version_id),
                }
                for v in graph.versions.values()
            ],
            "edges": [
                {"relation_id": d.relation_id, "child": d.child_version_id, "parents": list(d.parent_version_ids), "relation_type": d.relation_type}
                for d in graph.derivations.values()
            ],
            "activities": [activity.__dict__ for activity in ledger.list_activities(run_id)],
            "support_groups": [support.__dict__ for support in ledger.list_support_groups(run_id)],
            "metrics": ledger.metrics(run_id),
        }
    finally:
        ledger.close()
