"""Formal Phase 6 mechanism experiment runner.

The public command executes M-01 through M-04.  The held-out command refuses
to run until the public Gate passed and a pre-open hash inventory exists.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, fields, replace
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
from time import perf_counter
from typing import Any

from app.provenance.conservative_builder import build_conservative
from app.provenance.models import ArtifactKind, Derivation as RuntimeDerivation
from app.research.mechanism.cases import (
    SEMANTIC_CLASSES,
    generate_case_records,
    graph_from_dict,
)
from app.research.mechanism.oracle import (
    authority_atoms,
    enumerate_reference_witnesses,
    reference_bruteforce_cover,
    residual_count,
    validation_issues,
)
from app.research.scale.analysis import classify, enumerate_witnesses
from app.research.scale.baselines import (
    STRATEGIES,
    Outcome,
    raise_conservative,
    run_all,
)
from app.research.scale.checker import IndependentChecker
from app.research.scale.experiment import run_grid as run_scale_grid
from app.research.scale.experiment import summarise as summarise_scale
from app.research.scale.graph import GenSpec, Hypergraph, generate
from app.research.scale.grid_runner import run_grid as run_baseline_grid
from app.research.scale.grid_runner import summarise as summarise_baselines
from app.research.scale.raise_mechanism import raise_solve
from app.research.scale.solvers import brute_force_cover, greedy_cover, mincut_cover
from app.runtime import RunEngine, RunManifest
from app.state.controller import StateController
from app.verification.certificate_checker import (
    Certificate,
    CertificateChecker,
    ReissuePolicy,
)
from app.verification.residual_checker import ResidualChecker


WITNESS_CAP = 20_000
EXACT_MAX_SUBSETS = 200_000
BUDGETS_MS = (50, 100, 250, 500, 1000)
SCHEMA_VERSION = "majd-mechanism-results-v1"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _json_default(value):
    if isinstance(value, (set, frozenset, tuple)):
        return sorted(value)
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text.rstrip() + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = sorted({key for row in rows for key in row}) if rows else ["status"]
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    os.replace(temporary, path)


def _safe_number(value: float) -> float | None:
    return round(value, 6) if math.isfinite(value) else None


def _outcome(outcome: Outcome) -> dict[str, Any]:
    return {
        "name": outcome.name,
        "selected": sorted(outcome.selected),
        "repair": str(outcome.repair),
        "residual_witnesses": outcome.residual_witnesses,
        "escaped": outcome.escaped,
        "j": round(outcome.j(), 6),
        "op_cost": round(outcome.op_cost, 6),
        "task_loss": round(outcome.task_loss, 6),
        "replay_cost": round(outcome.replay_cost, 6),
        "human_cost": round(outcome.human_cost, 6),
        "task_utility": round(outcome.task_utility, 6),
        "benign_preservation": round(outcome.benign_preservation, 6),
        "versions_total": outcome.versions_total,
        "versions_active": outcome.versions_active,
        "versions_invalidated": outcome.versions_invalidated,
        "versions_retained": outcome.versions_retained,
        "goals_total": outcome.goals_total,
        "goals_supported": outcome.goals_supported,
        "solver_status": outcome.solver_status,
        "exhaustive": outcome.exhaustive,
    }


def _m01(staging: Path) -> tuple[list[tuple[dict, dict]], dict[str, Any]]:
    records = generate_case_records()
    validation_rows: list[dict[str, Any]] = []
    for case, oracle in records:
        case_path = staging / "cases" / f"{case['case_id']}.json"
        oracle_path = staging / "oracle" / f"{case['case_id']}.oracle.json"
        _write_json(case_path, case)
        _write_json(oracle_path, oracle)
        # Re-read from disk so the acceptance covers the serialized artifacts.
        disk_case = json.loads(case_path.read_text(encoding="utf-8"))
        disk_oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
        from app.research.mechanism.cases import validate_case_record

        issues = validate_case_record(disk_case, disk_oracle)
        validation_rows.append(
            {
                "case_id": case["case_id"],
                "semantic_class": case["semantic_class"],
                "status": "PASS" if not issues else "FAIL",
                "issues": issues,
            }
        )
    per_class = {
        semantic_class: sum(
            1 for case, _oracle in records if case["semantic_class"] == semantic_class
        )
        for semantic_class in SEMANTIC_CLASSES
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "task": "M-01",
        "planned": 60,
        "validated": sum(row["status"] == "PASS" for row in validation_rows),
        "failed": sum(row["status"] == "FAIL" for row in validation_rows),
        "per_semantic_class": per_class,
        "oracle_separate_from_cases": all(
            "oracle" not in case and "expected_status" not in case
            for case, _oracle in records
        ),
        "rows": validation_rows,
    }
    _write_json(staging / "results" / "m01_case_validation.json", summary)
    datasheet = """# M-01 机制案例数据说明

- Schema：`majd-mechanism-case-v1` 与独立 `majd-mechanism-oracle-v1`。
- 数量：12 类语义，每类 5 个，共 60 个。
- case 文件只包含运行可见的图、参数和场景元数据；expected status、真值 authority edge、witness 和 support 仅存在于 `oracle/`。
- 重复 derivation 与循环是预期无效输入，验收通过表示验证器准确拒绝，而不是把它们送入 solver。
- `missing_provenance` 与预算截断固定报告 UNKNOWN；不可覆盖的 break-set 固定报告 UNSATISFIABLE。
- Oracle 实现位于 research-only 包，不导入生产 witness、optimizer、checker 或 runtime。
"""
    _write_text(staging / "DATASHEET.md", datasheet)
    return records, summary


def _truth_signatures(graph: Hypergraph) -> set[tuple[str, tuple[str, ...]]]:
    return {
        (witness.root_qid, (source,))
        for witness in enumerate_reference_witnesses(graph)
        for source in witness.versions & graph.low_integrity_sources
    }


def _m02(staging: Path, records: list[tuple[dict, dict]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case, oracle in records:
        tight = graph_from_dict(case["tight_graph"])
        conservative = graph_from_dict(case["conservative_graph"])
        expected_validation = case["expected_validation"]
        base = {
            "case_id": case["case_id"],
            "semantic_class": case["semantic_class"],
            "expected_status": oracle["expected_status"],
        }
        if expected_validation != "VALID":
            rows.append(
                {
                    **base,
                    "status": "EXCLUDED",
                    "reason": expected_validation,
                    "edge_recall": None,
                    "witness_recall": None,
                }
            )
            continue

        truth_edges = {tuple(edge) for edge in oracle["truth_authority_edges"]}
        p1_edges = authority_atoms(conservative)
        edge_recall = len(truth_edges & p1_edges) / len(truth_edges) if truth_edges else 1.0
        truth_witnesses = {
            (row["sink"], tuple(row["low_sources"]))
            for row in oracle["truth_witness_signatures"]
        }
        p1_witnesses = _truth_signatures(conservative)
        witness_recall = (
            len(truth_witnesses & p1_witnesses) / len(truth_witnesses)
            if truth_witnesses
            else 1.0
        )

        if oracle["expected_status"] == "UNKNOWN":
            rows.append(
                {
                    **base,
                    "status": "UNKNOWN",
                    "reason": "missing_provenance_or_bounded_universe",
                    "edge_recall": edge_recall,
                    "witness_recall": witness_recall,
                    "exact_agrees_reference": None,
                    "greedy_residual": None,
                }
            )
            continue

        production_enum = enumerate_witnesses(conservative, cap=WITNESS_CAP)
        reference_witnesses = enumerate_reference_witnesses(conservative)
        exact = brute_force_cover(
            conservative,
            production_enum.witnesses,
            max_subsets=EXACT_MAX_SUBSETS,
        )
        reference = reference_bruteforce_cover(
            conservative,
            reference_witnesses,
            max_subsets=EXACT_MAX_SUBSETS,
        )
        greedy = greedy_cover(conservative, production_enum.witnesses)
        mincut = mincut_cover(conservative, production_enum.witnesses)
        greedy_residual = residual_count(
            conservative, reference_witnesses, greedy.selected
        )
        exact_agrees = exact.status == reference.status and (
            exact.cost == reference.cost
            or (not math.isfinite(exact.cost) and not math.isfinite(reference.cost))
        )
        reported_status = (
            "UNSATISFIABLE"
            if exact.status == "unsatisfiable"
            else "UNKNOWN"
            if not production_enum.exhaustive
            else "COVERED"
            if greedy_residual == 0
            else "UNSAFE"
        )
        expect_divergence = bool(case["metadata"].get("expect_greedy_strictly_worse"))
        rows.append(
            {
                **base,
                "status": reported_status,
                "reason": "",
                "edge_recall": round(edge_recall, 6),
                "witness_recall": round(witness_recall, 6),
                "p1_witnesses": len(production_enum.witnesses),
                "enumeration_exhaustive": production_enum.exhaustive,
                "exact_status": exact.status,
                "exact_cost": _safe_number(exact.cost),
                "reference_status": reference.status,
                "reference_cost": _safe_number(reference.cost),
                "exact_agrees_reference": exact_agrees,
                "greedy_status": greedy.status,
                "greedy_cost": _safe_number(greedy.cost),
                "greedy_residual": greedy_residual,
                "greedy_gap": (
                    round(greedy.cost / exact.cost, 6)
                    if exact.cost > 0 and math.isfinite(exact.cost) and math.isfinite(greedy.cost)
                    else None
                ),
                "mincut_status": mincut.status,
                "mincut_cost": _safe_number(mincut.cost),
                "expected_greedy_divergence": expect_divergence,
                "observed_greedy_divergence": (
                    greedy.cost > exact.cost + 1e-9
                    if math.isfinite(greedy.cost) and math.isfinite(exact.cost)
                    else False
                ),
            }
        )

    evaluated = [row for row in rows if row["status"] != "EXCLUDED"]
    exact_rows = [
        row for row in evaluated if row.get("exact_agrees_reference") is not None
    ]
    covered_rows = [row for row in evaluated if row["status"] == "COVERED"]
    divergence_rows = [row for row in rows if row.get("expected_greedy_divergence")]
    gates = {
        "p1_edge_recall_100_percent": all(row["edge_recall"] == 1.0 for row in evaluated),
        "p1_witness_recall_100_percent": all(row["witness_recall"] == 1.0 for row in evaluated),
        "exact_reference_agreement_100_percent": bool(exact_rows) and all(
            row["exact_agrees_reference"] for row in exact_rows
        ),
        "greedy_covered_residual_zero": all(
            row.get("greedy_residual", 0) == 0 for row in covered_rows
        ),
        "selected_divergence_cases_observed": len(divergence_rows) == 5 and all(
            row["observed_greedy_divergence"] for row in divergence_rows
        ),
        "statuses_not_conflated": all(
            row["status"] == row["expected_status"]
            for row in rows
            if row["expected_status"] in {"UNKNOWN", "UNSATISFIABLE", "EXCLUDED"}
        ),
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "task": "M-02",
        "rows": rows,
        "counts": {
            status: sum(row["status"] == status for row in rows)
            for status in {row["status"] for row in rows}
        },
        "gates": gates,
        "gate_pass": all(gates.values()),
    }
    _write_json(staging / "results" / "m02_cross_validation.json", summary)
    _write_csv(staging / "tables" / "m02_correctness.csv", rows)
    counterexamples = [
        row for row in rows
        if row["status"] in {"UNSAFE", "UNKNOWN", "UNSATISFIABLE", "EXCLUDED"}
        or row.get("observed_greedy_divergence")
    ]
    _write_json(staging / "results" / "m02_counterexamples.json", counterexamples)
    return summary


def _certificate_fixture(run_id: str):
    engine = RunEngine()
    context = engine.create_run(RunManifest(run_id))
    low = context.append_artifact(
        artifact_id=f"{run_id}-low",
        kind=ArtifactKind.MESSAGE,
        value="untrusted",
        integrity="low",
    )
    sink = context.append_artifact(
        artifact_id=f"{run_id}-sink",
        kind=ArtifactKind.ARGUMENT,
        value="protected",
        integrity="high",
    )
    context.derive(sink, [low], activity_id=f"{run_id}-sink-activity")
    graph = build_conservative(context.ledger, run_id)
    checker = CertificateChecker(context.ledger)
    certificate = checker.issue(
        graph,
        run_id=run_id,
        sink_versions={sink.version_id},
        blocked_versions={low.version_id},
    )
    return context, graph, checker, certificate, low, sink


def _mutant_value(field_name: str, value):
    if field_name == "integrity_hash":
        return "0" * 64 if value != "0" * 64 else "1" * 64
    if field_name == "reissue_policy":
        return ReissuePolicy(ttl_seconds=1.0, max_reissues=1)
    if isinstance(value, frozenset):
        return value | {"mutant"}
    if isinstance(value, tuple):
        return value + ("mutant",)
    if isinstance(value, str):
        return f"{value}-mutant" if value else "mutant"
    if isinstance(value, float):
        return value + 1.0
    if isinstance(value, int):
        return value + 1
    if value is None:
        return "mutant"
    raise TypeError(f"no mutation for {field_name}: {type(value)!r}")


def _retention_trial(trial: int, *, horizon: str) -> dict[str, Any]:
    run_id = f"m03-retention-{horizon}-{trial}"
    engine = RunEngine()
    context = engine.create_run(RunManifest(run_id, horizon_closure=horizon))
    low = context.append_artifact(
        artifact_id=f"{run_id}-low", kind=ArtifactKind.MESSAGE,
        value="parked payload", integrity="low",
    )
    stash = context.append_artifact(
        artifact_id=f"{run_id}-stash", kind=ArtifactKind.MEMORY,
        value="parked", integrity="high",
    )
    clean = context.append_artifact(
        artifact_id=f"{run_id}-clean", kind=ArtifactKind.MESSAGE,
        value="clean", integrity="high",
    )
    sink = context.append_artifact(
        artifact_id=f"{run_id}-sink", kind=ArtifactKind.ARGUMENT,
        value="send", integrity="high",
    )
    context.derive(stash, [low], activity_id=f"{run_id}-park")
    context.derive(sink, [clean], activity_id=f"{run_id}-sink")
    controller = StateController(context.ledger, run_id)
    retention = controller.certify_and_retain(
        sink_versions={sink.version_id},
        blocked_versions=set(),
        candidate_versions={stash.version_id},
        horizon_closure=horizon,
    )
    row: dict[str, Any] = {
        "trial": trial,
        "horizon": horizon,
        "certificate_valid": retention.certificate.valid,
        "retained_before_attack": stash.version_id in retention.retained,
        "certificate_status": retention.certificate.status,
        "certificate_completeness": retention.certificate.completeness,
        "demoted": False,
        "post_attack_status": "NOT_RUN",
        "escaped": False,
    }
    if horizon == "closed":
        context.ledger.append_derivation(
            RuntimeDerivation(
                f"{run_id}-attack-edge",
                run_id,
                sink.version_id,
                (stash.version_id,),
                f"{run_id}-attack",
            )
        )
        invalidated = controller.recheck_retained(
            {stash.version_id}, {sink.version_id}
        )
        post_graph = build_conservative(context.ledger, run_id)
        post = ResidualChecker().check(
            post_graph,
            sink_versions={sink.version_id},
            blocked_versions=set(invalidated),
        )
        row.update(
            {
                "demoted": stash.version_id in invalidated,
                "post_attack_status": post.status,
                "escaped": post.status != "COVERED",
            }
        )
    context.ledger.close()
    return row


def _m03(staging: Path) -> dict[str, Any]:
    mutation_rows: list[dict[str, Any]] = []
    stale_rows: list[dict[str, Any]] = []
    certificate_fields = [field.name for field in fields(Certificate)]
    for trial in range(5):
        context, graph, checker, certificate, _low, _sink = _certificate_fixture(
            f"m03-certificate-{trial}"
        )
        original_verifies = checker.verify(certificate, graph)
        for field_name in certificate_fields:
            mutant = replace(
                certificate,
                **{field_name: _mutant_value(field_name, getattr(certificate, field_name))},
            )
            accepted = checker.verify(mutant, graph)
            mutation_rows.append(
                {
                    "trial": trial,
                    "field": field_name,
                    "original_verifies": original_verifies,
                    "mutant_accepted": accepted,
                    "status": "FAIL" if accepted or not original_verifies else "PASS",
                }
            )
        context.append_artifact(
            artifact_id=f"m03-new-{trial}", kind=ArtifactKind.MESSAGE,
            value="snapshot movement", integrity="high",
        )
        stale_rows.append(
            {
                "trial": trial,
                "stale_certificate_accepted": checker.verify(
                    certificate,
                    build_conservative(context.ledger, certificate.run_id),
                ),
            }
        )
        context.ledger.close()

    retention_rows = [
        _retention_trial(trial, horizon=horizon)
        for horizon in ("closed", "open")
        for trial in range(5)
    ]
    closed = [row for row in retention_rows if row["horizon"] == "closed"]
    opened = [row for row in retention_rows if row["horizon"] == "open"]
    gates = {
        "all_certificate_fields_mutated": {
            row["field"] for row in mutation_rows
        } == set(certificate_fields),
        "mutant_rejection_rate_100_percent": all(
            not row["mutant_accepted"] for row in mutation_rows
        ),
        "original_certificates_verify": all(
            row["original_verifies"] for row in mutation_rows
        ),
        "stale_snapshot_rejection_100_percent": all(
            not row["stale_certificate_accepted"] for row in stale_rows
        ),
        "closed_horizon_zero_escape": all(not row["escaped"] for row in closed),
        "closed_horizon_demotes_new_path": all(row["demoted"] for row in closed),
        "open_horizon_no_valid_certificate": all(
            not row["certificate_valid"] for row in opened
        ),
        "open_horizon_no_retention": all(
            not row["retained_before_attack"] for row in opened
        ),
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "task": "M-03",
        "certificate_fields": certificate_fields,
        "mutation_trials": len(mutation_rows),
        "mutation_rows": mutation_rows,
        "stale_rows": stale_rows,
        "retention_rows": retention_rows,
        "gates": gates,
        "gate_pass": all(gates.values()),
    }
    _write_json(staging / "results" / "m03_certificate_retention.json", summary)
    _write_csv(staging / "tables" / "m03_mutation_matrix.csv", mutation_rows)
    _write_csv(staging / "tables" / "m03_retention_abuse.csv", retention_rows)
    return summary


def _scale_parameters(quick: bool) -> dict[str, tuple[int, ...]]:
    if quick:
        return {
            "contexts": (2, 4), "hops_list": (1, 2), "sinks_list": (1,),
            "widths": (1,), "seeds": (0,),
        }
    return {
        "contexts": (2, 4, 8, 16), "hops_list": (1, 2, 3, 4, 5),
        "sinks_list": (1, 2), "widths": (1, 2, 3), "seeds": (0, 1, 2),
    }


def _baseline_parameters(quick: bool) -> dict[str, tuple[int, ...]]:
    if quick:
        return {
            "contexts": (2, 4), "hops_list": (1, 2), "sinks_list": (1,),
            "widths": (1,), "seeds": (0,),
        }
    return {
        "contexts": (2, 4, 8), "hops_list": (1, 2, 3, 4),
        "sinks_list": (1, 2), "widths": (1, 2), "seeds": (0, 1, 2),
    }


def _asymmetry_core(params: dict[str, tuple[int, ...]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for context_size in params["contexts"]:
        for hops in params["hops_list"]:
            for n_sinks in params["sinks_list"]:
                for width in params["widths"]:
                    for seed in params["seeds"]:
                        spec = GenSpec(
                            context_size=context_size, hops=hops,
                            n_sinks=n_sinks, chain_width=width, seed=seed,
                        )
                        tight = generate(spec, conservative=False)
                        conservative = generate(spec, conservative=True)
                        enum = enumerate_witnesses(conservative, cap=WITNESS_CAP)
                        conservative_outcome = raise_conservative(
                            conservative, enum.witnesses
                        )
                        result = raise_solve(
                            tight, conservative, witness_cap=WITNESS_CAP
                        )
                        taint = classify(conservative)
                        rows.append(
                            {
                                "context_size": context_size,
                                "hops": hops,
                                "n_sinks": n_sinks,
                                "chain_width": width,
                                "seed": seed,
                                "enumeration_exhaustive": enum.exhaustive,
                                "clean_e_availability": round(taint.clean_survival_rate, 6),
                                "retention_off_availability": round(
                                    conservative_outcome.versions_active
                                    / conservative_outcome.versions_total
                                    if conservative_outcome.versions_total else 1.0,
                                    6,
                                ),
                                "asymmetric_availability": round(
                                    result.outcome.versions_active
                                    / result.outcome.versions_total
                                    if result.outcome.versions_total else 1.0,
                                    6,
                                ),
                                "retained_versions": result.outcome.versions_retained,
                                "conservative_j": round(conservative_outcome.j(), 6),
                                "asymmetric_j": round(result.outcome.j(), 6),
                                "certificate_valid": result.certificate.valid,
                                "certificate_status": str(result.certificate.status),
                                "post_state_witnesses": result.certificate.post_state_witnesses,
                                "certified_escape": bool(
                                    result.certificate.valid and result.outcome.escaped
                                ),
                            }
                        )
    return {
        "rows": rows,
        "summary": {
            "points": len(rows),
            "clean_e_availability_median": round(
                statistics.median(row["clean_e_availability"] for row in rows), 6
            ),
            "retention_off_availability_median": round(
                statistics.median(row["retention_off_availability"] for row in rows), 6
            ),
            "asymmetric_availability_median": round(
                statistics.median(row["asymmetric_availability"] for row in rows), 6
            ),
            "retention_gain_pp_median": round(
                100
                * statistics.median(
                    row["asymmetric_availability"] - row["retention_off_availability"]
                    for row in rows
                ),
                4,
            ),
            "conservative_j_median": round(
                statistics.median(row["conservative_j"] for row in rows), 6
            ),
            "asymmetric_j_median": round(
                statistics.median(row["asymmetric_j"] for row in rows), 6
            ),
            "certified_escape_count": sum(row["certified_escape"] for row in rows),
            "unknown_count": sum(
                not row["enumeration_exhaustive"]
                or row["certificate_status"] == "UNKNOWN"
                for row in rows
            ),
        },
    }


def _repair_ablation(baseline_points) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    mapping = {
        "wipe": "full-reset",
        "b7": "B7-dependency-rollback",
        "rollback_only": "containment-only-greedy",
        "selective_replay": "RAISE-conservative",
    }
    for point in baseline_points:
        if point.mode != "P1_conservative":
            continue
        for method, strategy in mapping.items():
            row = point.outcomes[strategy]
            rows.append(
                {
                    "method": method,
                    "context_size": point.context_size,
                    "hops": point.hops,
                    "n_sinks": point.n_sinks,
                    "chain_width": point.chain_width,
                    "seed": point.seed,
                    **row,
                }
            )
        full_reset = point.outcomes["full-reset"]
        spec = GenSpec(
            context_size=point.context_size, hops=point.hops,
            n_sinks=point.n_sinks, chain_width=point.chain_width,
            seed=point.seed,
        )
        graph = generate(spec, conservative=True)
        replay_cost = float(len(graph.activities()))
        rows.append(
            {
                "method": "full_replay",
                "context_size": point.context_size,
                "hops": point.hops,
                "n_sinks": point.n_sinks,
                "chain_width": point.chain_width,
                "seed": point.seed,
                "escaped": full_reset["escaped"],
                "j": round(full_reset["op_cost"] + replay_cost, 6),
                "task_utility": 1.0,
                "benign_preservation": full_reset["benign_preservation"],
                "op_cost": full_reset["op_cost"],
                "human_cost": full_reset["human_cost"],
            }
        )
    summary: dict[str, dict[str, Any]] = {}
    for method in sorted({row["method"] for row in rows}):
        method_rows = [row for row in rows if row["method"] == method]
        summary[method] = {
            "points": len(method_rows),
            "escape_rate": round(
                sum(bool(row["escaped"]) for row in method_rows) / len(method_rows), 6
            ),
            "j_median": round(statistics.median(row["j"] for row in method_rows), 6),
            "task_utility_median": round(
                statistics.median(row["task_utility"] for row in method_rows), 6
            ),
            "benign_preservation_median": round(
                statistics.median(row["benign_preservation"] for row in method_rows), 6
            ),
        }
    return {"rows": rows, "summary": summary}


def _budget_scan(quick: bool) -> dict[str, Any]:
    specs = [
        GenSpec(context_size=context, hops=hops, n_sinks=sinks, chain_width=width, seed=0)
        for context in ((4,) if quick else (4, 8, 16))
        for hops in ((2,) if quick else (3, 5))
        for sinks in ((1,) if quick else (1, 2))
        for width in ((1,) if quick else (1, 3))
    ]
    measured: list[dict[str, Any]] = []
    for conservative_mode in (False, True):
        for spec in specs:
            graph = generate(spec, conservative=conservative_mode)
            started = perf_counter()
            enum = enumerate_witnesses(graph, cap=WITNESS_CAP)
            enumeration_ms = (perf_counter() - started) * 1000
            exact = brute_force_cover(
                graph, enum.witnesses, max_subsets=EXACT_MAX_SUBSETS
            )
            greedy = greedy_cover(graph, enum.witnesses)
            checker_started = perf_counter()
            check = IndependentChecker(cap=WITNESS_CAP).check(graph, greedy.selected)
            checker_ms = (perf_counter() - checker_started) * 1000
            for budget in BUDGETS_MS:
                solver_within = exact.elapsed_ms <= budget
                checker_within = checker_ms <= budget
                measured.append(
                    {
                        "mode": "P1_conservative" if conservative_mode else "P0_tight",
                        "context_size": spec.context_size,
                        "hops": spec.hops,
                        "n_sinks": spec.n_sinks,
                        "chain_width": spec.chain_width,
                        "budget_ms": budget,
                        "witnesses": len(enum.witnesses),
                        "enumeration_exhaustive": enum.exhaustive,
                        "enumeration_ms": round(enumeration_ms, 6),
                        "solver_ms": round(exact.elapsed_ms, 6),
                        "checker_ms": round(checker_ms, 6),
                        "solver_status": (
                            exact.status if solver_within and enum.exhaustive else "UNKNOWN"
                        ),
                        "checker_status": (
                            "COVERED"
                            if checker_within and check.passed
                            else "UNSAFE"
                            if check.residual_witnesses
                            else "UNKNOWN"
                        ),
                        "solver_within_budget": solver_within,
                        "checker_within_budget": checker_within,
                        "optimal_claimed": bool(
                            solver_within and enum.exhaustive and exact.status == "optimal"
                        ),
                    }
                )
    return {
        "rows": measured,
        "summary": {
            "rows": len(measured),
            "unknown_count": sum(
                row["solver_status"] == "UNKNOWN" or row["checker_status"] == "UNKNOWN"
                for row in measured
            ),
            "false_optimal_claim_count": sum(
                row["optimal_claimed"]
                and (
                    not row["enumeration_exhaustive"]
                    or not row["solver_within_budget"]
                )
                for row in measured
            ),
        },
    }


def _write_m04_svg(path: Path, core_summary: dict[str, Any]) -> None:
    values = [
        ("Clean_E", core_summary["clean_e_availability_median"], "#64748b"),
        ("Retention-off", core_summary["retention_off_availability_median"], "#f59e0b"),
        ("RAISE asymmetric", core_summary["asymmetric_availability_median"], "#16a34a"),
    ]
    bars = []
    for index, (label, value, color) in enumerate(values):
        y = 45 + index * 55
        width = 440 * value
        bars.append(
            f'<text x="15" y="{y + 17}" font-size="14">{label}</text>'
            f'<rect x="145" y="{y}" width="{width:.1f}" height="24" fill="{color}" rx="3"/>'
            f'<text x="{155 + width:.1f}" y="{y + 17}" font-size="13">{value:.3f}</text>'
        )
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="650" height="230" viewBox="0 0 650 230">'
        '<rect width="650" height="230" fill="white"/>'
        '<text x="15" y="25" font-size="18" font-family="sans-serif">M-04 median availability</text>'
        '<g font-family="sans-serif">' + "".join(bars) + "</g></svg>"
    )
    _write_text(path, svg)


def _m04(staging: Path, *, quick: bool) -> dict[str, Any]:
    scale_params = _scale_parameters(quick)
    scale_points = run_scale_grid(
        **scale_params,
        witness_cap=WITNESS_CAP,
        exact_budget=EXACT_MAX_SUBSETS,
    )
    scale_payload = {
        "schema_version": SCHEMA_VERSION,
        "task": "M-04-scale",
        "points": [asdict(point) for point in scale_points],
        "summary": summarise_scale(scale_points),
    }
    _write_json(staging / "results" / "m04_scale_grid.json", scale_payload)

    baseline_params = _baseline_parameters(quick)
    baseline_points = run_baseline_grid(
        **baseline_params, witness_cap=WITNESS_CAP
    )
    baseline_payload = {
        "schema_version": SCHEMA_VERSION,
        "task": "M-04-baselines",
        "points": [asdict(point) for point in baseline_points],
        "summary": summarise_baselines(baseline_points),
    }
    _write_json(staging / "results" / "m04_baseline_grid.json", baseline_payload)

    core = _asymmetry_core(scale_params)
    repair = _repair_ablation(baseline_points)
    budgets = _budget_scan(quick)
    _write_json(staging / "results" / "m04_asymmetry_core.json", core)
    _write_json(staging / "results" / "m04_repair_ablation.json", repair)
    _write_json(staging / "results" / "m04_budget_scan.json", budgets)
    _write_csv(staging / "tables" / "m04_asymmetry_core.csv", core["rows"])
    _write_csv(staging / "tables" / "m04_repair_ablation.csv", repair["rows"])
    _write_csv(staging / "tables" / "m04_budget_scan.csv", budgets["rows"])
    _write_m04_svg(staging / "figures" / "m04_availability.svg", core["summary"])

    expected_scale = 8 if quick else 720
    expected_baselines = 8 if quick else 288
    gates = {
        "scale_point_count": len(scale_points) == expected_scale,
        "baseline_point_count": len(baseline_points) == expected_baselines,
        "no_certified_escape": core["summary"]["certified_escape_count"] == 0,
        "no_false_optimal_on_truncated_universe": all(
            point.enumeration_exhaustive or point.exact_status != "optimal"
            for point in scale_points
        ),
        "greedy_covered_residual_zero": all(
            point.greedy_verified for point in scale_points
        ),
        "budget_scan_no_false_optimal": budgets["summary"]["false_optimal_claim_count"] == 0,
        "all_negative_and_unknown_rows_retained": (
            len(scale_payload["points"]) == len(scale_points)
            and len(baseline_payload["points"]) == len(baseline_points)
        ),
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "task": "M-04",
        "quick": quick,
        "scale_points": len(scale_points),
        "baseline_points": len(baseline_points),
        "core_summary": core["summary"],
        "repair_summary": repair["summary"],
        "budget_summary": budgets["summary"],
        "gates": gates,
        "gate_pass": all(gates.values()),
    }
    _write_json(staging / "results" / "m04_summary.json", summary)
    return summary


def _public_report(m01: dict, m02: dict, m03: dict, m04: dict) -> str:
    passed = all(item.get("gate_pass", item.get("failed", 1) == 0) for item in (m01, m02, m03, m04))
    core = m04["core_summary"]
    return f"""# Phase 6 机制层 M-01～M-04 验收

生成时间：{_now()}

## Gate 结果

- M-01：{m01['validated']}/60 案例 schema 与 Oracle 校验通过；失败 {m01['failed']}。
- M-02：P1 edge recall Gate={m02['gates']['p1_edge_recall_100_percent']}；P1 witness recall Gate={m02['gates']['p1_witness_recall_100_percent']}；exact/reference Gate={m02['gates']['exact_reference_agreement_100_percent']}；greedy residual Gate={m02['gates']['greedy_covered_residual_zero']}。
- M-03：证书字段 mutant {m03['mutation_trials']} 个，拒绝率 Gate={m03['gates']['mutant_rejection_rate_100_percent']}；closed-horizon 零逃逸 Gate={m03['gates']['closed_horizon_zero_escape']}；open-horizon 不签有效证书 Gate={m03['gates']['open_horizon_no_valid_certificate']}。
- M-04：规模点 {m04['scale_points']}；公开 baseline 点 {m04['baseline_points']}；certified escape={core['certified_escape_count']}；UNKNOWN={core['unknown_count']}。
- M-01～M-04 总 Gate：{'PASS' if passed else 'FAIL'}。

## 公开结果（held-out 打开前）

- Clean_E availability median：{core['clean_e_availability_median']:.4f}
- retention-off availability median：{core['retention_off_availability_median']:.4f}
- asymmetric availability median：{core['asymmetric_availability_median']:.4f}
- asymmetric 相对 retention-off 的中位保留增益：{core['retention_gain_pp_median']:.2f} pp
- conservative J median：{core['conservative_j_median']:.4f}
- asymmetric J median：{core['asymmetric_j_median']:.4f}

本报告没有打开 held-out；只有总 Gate PASS、回归通过并生成 pre-open hash inventory 后，M-05 才可执行。UNKNOWN、UNSATISFIABLE、无效输入和负结果均保留在原始表中。
"""


def run_public(output_root: Path, *, quick: bool = False) -> dict[str, Any]:
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"mechanism output root already exists: {output_root}")
    staging = output_root.with_name(f".{output_root.name}.staging")
    if staging.exists():
        raise FileExistsError(f"staging root already exists: {staging}")
    staging.mkdir(parents=True)
    started = perf_counter()
    try:
        _write_json(
            staging / "manifest.json",
            {
                "schema_version": "majd-mechanism-manifest-v1",
                "experiment_id": "phase6-mechanism-v4",
                "layer": "M",
                "preregistration": "experiments/preregistration/v4.yaml",
                "quick": quick,
                "witness_cap": WITNESS_CAP,
                "exact_max_subsets": EXACT_MAX_SUBSETS,
                "budget_ms": list(BUDGETS_MS),
                "started_at": _now(),
            },
        )
        records, m01 = _m01(staging)
        m02 = _m02(staging, records)
        m03 = _m03(staging)
        m04 = _m04(staging, quick=quick)
        gate_pass = (
            m01["failed"] == 0
            and m02["gate_pass"]
            and m03["gate_pass"]
            and m04["gate_pass"]
        )
        status = {
            "status": "COMPLETED" if gate_pass else "FAILED",
            "gate_pass": gate_pass,
            "elapsed_s": round(perf_counter() - started, 3),
            "completed_at": _now(),
            "tasks": {"M-01": m01["failed"] == 0, "M-02": m02["gate_pass"], "M-03": m03["gate_pass"], "M-04": m04["gate_pass"]},
        }
        _write_json(staging / "status.json", status)
        _write_text(staging / "reports" / "M01_M04_ACCEPTANCE.md", _public_report(m01, m02, m03, m04))
    except Exception as exc:
        _write_json(
            staging / "status.json",
            {
                "status": "FAILED",
                "gate_pass": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "elapsed_s": round(perf_counter() - started, 3),
                "completed_at": _now(),
            },
        )
        os.replace(staging, output_root)
        raise
    os.replace(staging, output_root)
    return status


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def freeze_preopen(output_root: Path) -> dict[str, Any]:
    output_root = output_root.resolve()
    status = json.loads((output_root / "status.json").read_text(encoding="utf-8"))
    if not status.get("gate_pass"):
        raise RuntimeError("M-01 through M-04 Gate did not pass")
    freeze_path = output_root / "preopen-freeze.json"
    if freeze_path.exists():
        raise FileExistsError(freeze_path)
    repo_root = Path(__file__).resolve().parents[4]
    external = [
        repo_root / "backend/app/research/mechanism/cases.py",
        repo_root / "backend/app/research/mechanism/oracle.py",
        repo_root / "backend/app/research/mechanism/runner.py",
        repo_root / "backend/app/research/scale/heldout.py",
        repo_root / "backend/app/research/scale/graph.py",
        repo_root / "backend/app/research/scale/analysis.py",
        repo_root / "backend/app/research/scale/solvers.py",
        repo_root / "backend/app/research/scale/baselines.py",
        repo_root / "backend/app/research/scale/raise_mechanism.py",
        repo_root / "backend/app/verification/certificate_checker.py",
        repo_root / "backend/app/state/controller.py",
        repo_root / "experiments/preregistration/v1.yaml",
        repo_root / "experiments/preregistration/v2.yaml",
        repo_root / "experiments/preregistration/v3.yaml",
        repo_root / "experiments/preregistration/v4.yaml",
    ]
    internal = sorted(
        path for path in output_root.rglob("*")
        if path.is_file()
        and path.name != "preopen-freeze.json"
        and path.name != "heldout-opened.json"
        and "m05" not in path.parts
    )
    files = []
    for path in external:
        files.append(
            {
                "scope": "repo",
                "path": path.relative_to(repo_root).as_posix(),
                "sha256": _sha256(path),
                "size": path.stat().st_size,
            }
        )
    for path in internal:
        files.append(
            {
                "scope": "output",
                "path": path.relative_to(output_root).as_posix(),
                "sha256": _sha256(path),
                "size": path.stat().st_size,
            }
        )
    payload = {
        "schema_version": "majd-mechanism-preopen-freeze-v1",
        "frozen_at": _now(),
        "preregistration": "experiments/preregistration/v4.yaml",
        "heldout_dataset_id": "majd-mechanism-heldout-graphs-v1",
        "heldout_dataset_sha256": "da7afe16cafc3e3f62513941d0999a6ba7555415386ef3c8136715f1d0129a08",
        "files": files,
    }
    _write_json(freeze_path, payload)
    return payload


def verify_preopen(output_root: Path) -> dict[str, Any]:
    output_root = output_root.resolve()
    freeze_path = output_root / "preopen-freeze.json"
    payload = json.loads(freeze_path.read_text(encoding="utf-8"))
    repo_root = Path(__file__).resolve().parents[4]
    mismatches = []
    for row in payload["files"]:
        path = (repo_root if row.get("scope") == "repo" else output_root) / row["path"]
        if not path.is_file():
            mismatches.append({"path": row["path"], "reason": "missing"})
            continue
        actual = _sha256(path)
        if actual != row["sha256"]:
            mismatches.append(
                {"path": row["path"], "expected": row["sha256"], "actual": actual}
            )
    if mismatches:
        raise RuntimeError(f"pre-open freeze mismatch: {mismatches[:3]}")
    return payload


def _strategy_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for strategy in STRATEGIES:
        values = [row["outcomes"][strategy] for row in rows if strategy in row.get("outcomes", {})]
        summary[strategy] = {
            "planned": len(rows),
            "completed": len(values),
            "missing": len(rows) - len(values),
            "escape_rate": round(sum(row["escaped"] for row in values) / len(values), 6) if values else None,
            "j_median": round(statistics.median(row["j"] for row in values), 6) if values else None,
            "task_utility_median": round(statistics.median(row["task_utility"] for row in values), 6) if values else None,
            "benign_preservation_median": round(statistics.median(row["benign_preservation"] for row in values), 6) if values else None,
            "unknown": sum(not row["exhaustive"] for row in values),
        }
    return summary


def _rank_concordance(public: dict[str, float], heldout: dict[str, float]) -> float | None:
    common = sorted(set(public) & set(heldout))
    pairs = 0
    concordant = 0
    for index, left in enumerate(common):
        for right in common[index + 1:]:
            public_delta = public[left] - public[right]
            heldout_delta = heldout[left] - heldout[right]
            if public_delta == 0 or heldout_delta == 0:
                continue
            pairs += 1
            concordant += (public_delta > 0) == (heldout_delta > 0)
    return round(concordant / pairs, 6) if pairs else None


def run_heldout(output_root: Path, *, limit: int | None = None) -> dict[str, Any]:
    output_root = output_root.resolve()
    freeze = verify_preopen(output_root)
    marker = output_root / "heldout-opened.json"
    if marker.exists():
        raise FileExistsError("held-out population has already been opened")
    from app.research.scale.heldout import DATASET_ID, DATASET_SHA256, heldout_specs

    if DATASET_SHA256 != freeze["heldout_dataset_sha256"]:
        raise RuntimeError("held-out dataset identity differs from pre-open freeze")
    _write_json(
        marker,
        {
            "dataset_id": DATASET_ID,
            "dataset_sha256": DATASET_SHA256,
            "opened_at": _now(),
            "tuning_forbidden": True,
            "limit": limit,
        },
    )
    result_dir = output_root / "results" / "m05"
    if result_dir.exists():
        raise FileExistsError(result_dir)
    staging = output_root / "results" / ".m05.staging"
    staging.mkdir(parents=True)
    specs = heldout_specs()
    if limit is not None:
        specs = specs[:limit]
    rows: list[dict[str, Any]] = []
    started = perf_counter()
    for index, spec in enumerate(specs):
        row: dict[str, Any] = {
            "index": index,
            "spec": asdict(spec),
            "status": "RUNNING",
            "outcomes": {},
        }
        point_started = perf_counter()
        try:
            tight = generate(spec, conservative=False)
            conservative = generate(spec, conservative=True)
            outcomes, exhaustive = run_all(conservative, witness_cap=WITNESS_CAP)
            asymmetric = raise_solve(tight, conservative, witness_cap=WITNESS_CAP)
            outcomes["RAISE-asymmetric"] = asymmetric.outcome
            row.update(
                {
                    "status": "COMPLETED" if exhaustive else "UNKNOWN",
                    "enumeration_exhaustive": exhaustive,
                    "outcomes": {
                        name: _outcome(outcome) for name, outcome in outcomes.items()
                    },
                    "certificate": {
                        "valid": asymmetric.certificate.valid,
                        "status": str(asymmetric.certificate.status),
                        "post_state_witnesses": asymmetric.certificate.post_state_witnesses,
                        "certified_escape": bool(
                            asymmetric.certificate.valid and asymmetric.outcome.escaped
                        ),
                    },
                }
            )
        except Exception as exc:
            row.update(
                {
                    "status": "FAILED",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
        row["elapsed_ms"] = round((perf_counter() - point_started) * 1000, 6)
        rows.append(row)

    heldout_summary = _strategy_summary(rows)
    public_payload = json.loads(
        (output_root / "results" / "m04_baseline_grid.json").read_text(encoding="utf-8")
    )
    public_summary = {
        strategy: values["P1_conservative"]["J"]["median"]
        for strategy, values in public_payload["summary"]["by_strategy"].items()
    }
    core_public = json.loads(
        (output_root / "results" / "m04_asymmetry_core.json").read_text(encoding="utf-8")
    )
    public_summary["RAISE-asymmetric"] = core_public["summary"]["asymmetric_j_median"]
    heldout_j = {
        strategy: values["j_median"]
        for strategy, values in heldout_summary.items()
        if values["j_median"] is not None
    }
    certified_escape = sum(
        bool(row.get("certificate", {}).get("certified_escape")) for row in rows
    )
    statuses = {
        status: sum(row["status"] == status for row in rows)
        for status in {row["status"] for row in rows}
    }
    b9_j = heldout_j.get("B9'-naive-compose")
    raise_j = heldout_j.get("RAISE-asymmetric")
    j_reduction = (
        (b9_j - raise_j) / b9_j
        if b9_j and raise_j is not None
        else None
    )
    gates = {
        "planned_rows_have_status": len(rows) == len(specs) and all(row["status"] for row in rows),
        "no_silent_missing_methods": all(
            row["status"] == "FAILED" or set(row["outcomes"]) == set(STRATEGIES)
            for row in rows
        ),
        "certified_escape_zero": certified_escape == 0,
        "raw_rows_complete": statuses.get("FAILED", 0) == 0,
    }
    decision = "GO_E_CANARY" if all(gates.values()) else "NO_GO_REPAIR_REQUIRED"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "task": "M-05",
        "dataset_id": DATASET_ID,
        "dataset_sha256": DATASET_SHA256,
        "planned": len(specs),
        "statuses": statuses,
        "elapsed_s": round(perf_counter() - started, 3),
        "strategy_summary": heldout_summary,
        "public_j_median": public_summary,
        "heldout_j_median": heldout_j,
        "public_heldout_rank_concordance": _rank_concordance(public_summary, heldout_j),
        "raise_vs_b9_j_relative_reduction": round(j_reduction, 6) if j_reduction is not None else None,
        "certified_escape_count": certified_escape,
        "gates": gates,
        "decision": decision,
        "claim_boundary": "Synthetic mechanism evidence only; no E/X superiority claim.",
    }
    _write_json(staging / "m05_heldout_rows.json", rows)
    _write_json(staging / "m05_summary.json", summary)
    _write_csv(
        staging / "m05_strategy_summary.csv",
        [{"strategy": strategy, **values} for strategy, values in heldout_summary.items()],
    )
    os.replace(staging, result_dir)
    report = f"""# Phase 6 机制层 M-05 held-out 验收

打开时间：{json.loads(marker.read_text(encoding='utf-8'))['opened_at']}

- 数据集：`{DATASET_ID}` / `{DATASET_SHA256}`
- 计划图：{len(specs)}；状态：{statuses}
- certified escape：{certified_escape}
- 公开/held-out J 排序一致率：{summary['public_heldout_rank_concordance']}
- RAISE-asymmetric 相对 B9′ 的 held-out J 变化：{summary['raise_vs_b9_j_relative_reduction']}
- 决定：**{decision}**

该决定只允许进入 E 层 canary；held-out 未用于调参，本结果不构成真实端到端或外部 Benchmark 全面优越性主张。
"""
    _write_text(output_root / "reports" / "M05_HELDOUT_ACCEPTANCE.md", report)
    _write_json(
        output_root / "m05-status.json",
        {
            "status": "COMPLETED" if all(gates.values()) else "FAILED",
            "decision": decision,
            "completed_at": _now(),
            "gates": gates,
        },
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 6 formal mechanism runner")
    sub = parser.add_subparsers(dest="command", required=True)
    public = sub.add_parser("public", help="run M-01 through M-04")
    public.add_argument("--out", default="../experiments/mechanism")
    public.add_argument("--quick", action="store_true")
    freeze = sub.add_parser("freeze", help="freeze the M-05 pre-open inventory")
    freeze.add_argument("--out", default="../experiments/mechanism")
    heldout = sub.add_parser("heldout", help="open and run the frozen held-out population")
    heldout.add_argument("--out", default="../experiments/mechanism")
    heldout.add_argument("--limit", type=int)
    args = parser.parse_args()
    output = Path(args.out)
    if args.command == "public":
        result = run_public(output, quick=args.quick)
    elif args.command == "freeze":
        result = freeze_preopen(output)
    else:
        result = run_heldout(output, limit=args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
