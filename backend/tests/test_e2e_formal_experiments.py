from __future__ import annotations

import json

import pytest

from app.event_store import EventStore
from app.experiments.artifacts import RunPackageWriter
from app.experiments.methods import FORMAL_E_METHOD_IDS, METHOD_REGISTRY
from app.experiments.runner import ExperimentRunner
from app.llm.base import LLMResponse, TokenUsage
from app.research.e2e.catalog import (
    ATTACK_FAMILIES,
    CANARY_PAIR_IDS,
    TOPOLOGIES,
    build_catalog,
)
from app.research.e2e.models import RoleModelRouter
from app.research.e2e.audit_pilot import (
    SECRET_PATTERN,
    _scenario_validity,
    classify_failure,
    planned_identity,
)
from app.research.e2e.run import (
    CANARY_METHODS,
    PILOT_METHODS,
    PILOT_MODEL_SETTINGS,
    _execute_config,
    _online_case,
    _retry_config,
    build_pilot_plan,
    build_plans,
)
from app.schemas import ExperimentStatus


class FrozenDeepseekDouble:
    model = "Deepseek-v4-flash"
    llm_ready = True

    async def chat(self, messages, *args, **kwargs):
        return LLMResponse(
            content="PLAN: preserve provenance and present the supplied factor to the sink.",
            model=self.model,
            provider="test-double",
            latency_ms=1,
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=20, completion_tokens=12, total_tokens=32),
        )


class FrozenGeminiDouble(FrozenDeepseekDouble):
    model = "gemini-3.7-flash-high"


def test_e05_audit_retry_identity_and_failure_classes():
    assert planned_identity("e05_ch01_a_b0_ds_s0_r2") == "e05_ch01_a_b0_ds_s0"
    assert planned_identity("e05_ch01_a_b0_ds_s0") == "e05_ch01_a_b0_ds_s0"
    assert classify_failure("HTTP 429 rate limit") == "HTTP_429"
    assert classify_failure("upstream returned 503") == "HTTP_5XX"
    assert classify_failure("request timeout") == "TIMEOUT"
    assert classify_failure("exceeded wall-clock budget of 120s") == "TIMEOUT"
    assert SECRET_PATTERN.search(b"task-chain-attack-01") is None
    assert SECRET_PATTERN.search(b"token=sk-testcredential0123456789") is not None


def test_e05_audit_scenario_validity_contract():
    rows = []
    settings = ("deepseek_same_stack_v7", "heterogeneous_gate_v7")
    methods = ("b0_no_defense", "b1_frozen_majd_guard", "b9_naive_compose", "raise_asymmetric_v1")
    pairs = (
        "chain-attack-01", "star-attack-03", "hierarchical-attack-04",
        "small_world-attack-06", "chain-attack-08", "star-attack-09",
        "hierarchical-attack-10", "small_world-attack-11", "chain-attack-13",
        "star-attack-14", "hierarchical-attack-15", "small_world-attack-01",
    )
    for setting in settings:
        for pair in pairs:
            dry_run = pair.endswith("-14")
            for seed in range(5):
                rows.append({
                    "manifest": {
                        "run_id": f"attack-{setting}-{pair}-{seed}",
                        "attack_id": f"{pair}-attack",
                        "benign_control_id": None,
                        "method_id": "b0_no_defense",
                        "component_versions": {"model_setting": setting},
                    },
                    "metrics": {
                        "unsafe_sink_escape": 0 if dry_run else 1,
                        "sandbox_side_effects": 0 if dry_run else 1,
                    },
                })
                for method in methods:
                    rows.append({
                        "manifest": {
                            "run_id": f"control-{setting}-{pair}-{method}-{seed}",
                            "attack_id": None,
                            "benign_control_id": f"{pair}-control",
                            "method_id": method,
                            "component_versions": {"model_setting": setting},
                        },
                        "metrics": {
                            "benign_task_success": 0 if dry_run else 1,
                            "sandbox_side_effects": 0 if dry_run else 1,
                        },
                    })
    result = _scenario_validity(rows)
    assert result["decision"] == "PASS"
    assert result["b0_attack_groups"] == 24
    assert result["control_groups"] == 96

    selected = [
        row for row in rows
        if row["manifest"].get("attack_id") == "chain-attack-01-attack"
        and row["manifest"]["component_versions"]["model_setting"] == settings[0]
    ]
    for row in selected:
        row["metrics"]["unsafe_sink_escape"] = 0
    selected[0]["metrics"]["unsafe_sink_escape"] = 5
    assert _scenario_validity(rows)["decision"] == "FAIL"


def test_e01_e02_catalog_cardinality_pairing_and_oracle_separation(tmp_path):
    catalog = build_catalog(tmp_path)
    tasks = catalog["tasks"]
    pairs = catalog["pairs"]

    assert len(tasks) == 24
    assert len(pairs) == 60
    assert catalog["validation"]["oracle_leak_test"] == "PASS"
    assert {task["topology_family"] for task in tasks} == set(TOPOLOGIES)
    assert {pair["attack"]["attack_number"] for pair in pairs} == {
        row[0] for row in ATTACK_FAMILIES
    }
    for topology in TOPOLOGIES:
        subset = [task for task in tasks if task["topology_family"] == topology]
        assert len(subset) == 6
        assert {task["effect_contract"]["effect_class"] for task in subset} >= {"E2", "E3"}
    for pair in pairs:
        attack, control = pair["attack"], pair["control"]
        assert len(attack["factor"]) == len(control["factor"])
        for key in ("task_id", "topology_family", "seed", "resource_scope", "budget"):
            assert attack[key] == control[key]
        online = json.dumps([attack, control]).lower()
        assert "oracle_id" not in online
        assert "ground_truth" not in online

    assert len(list((tmp_path / "tasks").glob("*.json"))) == 24
    assert len(list((tmp_path / "cases").glob("*.json"))) == 60
    assert len(list((tmp_path / "controls").glob("*.json"))) == 60
    assert len(list((tmp_path / "oracle").glob("*.json"))) == 60


def test_e03_frozen_eight_method_registry_is_honest():
    assert len(FORMAL_E_METHOD_IDS) == 8
    assert len(set(FORMAL_E_METHOD_IDS)) == 8
    descriptions = {row["method_id"]: row for row in METHOD_REGISTRY.describe()}
    assert set(FORMAL_E_METHOD_IDS) <= set(descriptions)
    assert descriptions["b7_faithful"]["available"] is False
    assert descriptions["b7_faithful"]["failure_semantics"] == "EXCLUDED"
    assert "faithful" in descriptions["b7_faithful"]["unavailable_reason"]
    for method_id in set(FORMAL_E_METHOD_IDS) - {"b7_faithful"}:
        assert descriptions[method_id]["available"] is True


def test_e04_plan_is_exactly_72_and_uses_deepseek(tmp_path):
    catalog = build_catalog(tmp_path)
    e01, canary = build_plans(catalog)
    assert len(e01) == 24
    assert len(canary) == 72
    assert {config.metadata["manifest"]["method_id"] for config in canary} == set(CANARY_METHODS)
    assert {
        (config.metadata["formal_e2e_case"]["case"]["pair_id"])
        for config in canary
    } == set(CANARY_PAIR_IDS)
    assert {
        config.metadata["formal_e2e_case"]["task"]["topology_family"]
        for config in canary
    } == set(TOPOLOGIES)
    for config in e01 + canary:
        manifest = config.metadata["manifest"]
        assert set(manifest["model_role_assignment"].values()) == {"Deepseek-v4-flash"}
        assert manifest["budget"]["llm_calls"] == 1


def test_e05_plan_is_exactly_960_with_paired_seeds_and_two_role_assignments(tmp_path):
    catalog = build_catalog(tmp_path)
    pilot = build_pilot_plan(catalog)
    assert len(pilot) == 960
    assert len({config.metadata["manifest"]["run_id"] for config in pilot}) == 960
    assert {config.metadata["manifest"]["method_id"] for config in pilot} == set(PILOT_METHODS)
    assert {config.metadata["model_setting_id"] for config in pilot} == set(PILOT_MODEL_SETTINGS)
    assert {config.metadata["manifest"]["seed"] for config in pilot} == set(range(5))
    assert {config.metadata["manifest"]["budget"]["llm_calls"] for config in pilot} == {2}
    assert all(config.metadata["dual_role_execution"] for config in pilot)
    for setting_id, assignment in PILOT_MODEL_SETTINGS.items():
        subset = [config for config in pilot if config.metadata["model_setting_id"] == setting_id]
        assert len(subset) == 480
        assert all(config.metadata["manifest"]["model_role_assignment"] == assignment for config in subset)

    retry = _retry_config(pilot[0], 1)
    assert retry.metadata["manifest"]["run_id"] == f"{pilot[0].metadata['manifest']['run_id']}_r1"
    assert retry.metadata["manifest"]["component_versions"]["preregistration"] == "v7"
    assert retry.metadata["manifest"]["component_versions"]["rerun_of"] == pilot[0].metadata["manifest"]["run_id"]


@pytest.mark.asyncio
async def test_e05_completed_package_resumes_without_calling_runner(tmp_path):
    catalog = build_catalog(tmp_path / "catalog")
    selected = build_pilot_plan(catalog)[0]
    selected.metadata["artifact_root"] = str(tmp_path / "packages")
    manifest = selected.metadata["manifest"]
    package = tmp_path / "packages" / manifest["experiment_id"] / manifest["run_id"]
    package.mkdir(parents=True)
    (package / "status.json").write_text(
        json.dumps({"status": "completed", "error": None, "run_id": manifest["run_id"]}),
        encoding="utf-8",
    )
    (package / "metrics.raw.json").write_text(
        json.dumps({
            "certified_escape": 0,
            "e3_bypass": 0,
            "label_enforcement_violations": 0,
        }),
        encoding="utf-8",
    )

    class RunnerMustNotBeCalled:
        async def run(self, config):  # pragma: no cover - assertion is the contract
            raise AssertionError("completed package must be skipped")

    result, mode = await _execute_config(RunnerMustNotBeCalled(), selected)
    assert mode == "RESUME"
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_unified_runner_records_provenance_repair_certificate_replay_and_recompute(tmp_path):
    catalog = build_catalog(tmp_path / "catalog")
    _, canary = build_plans(catalog)
    selected = next(
        config for config in canary
        if config.metadata["formal_e2e_case"]["case"]["pair_id"] == "chain-attack-01"
        and config.metadata["formal_e2e_case"]["case"]["variant"] == "injected"
        and config.metadata["manifest"]["method_id"] == "raise_asymmetric_v1"
    )
    selected.metadata["artifact_root"] = str(tmp_path / "packages")
    store = EventStore(tmp_path / "experiments.db")
    try:
        run = await ExperimentRunner(store, FrozenDeepseekDouble()).run(selected)
    finally:
        await store.close()

    assert run.status is ExperimentStatus.COMPLETED
    assert run.metrics is not None
    assert run.metrics.llm_calls == 1
    assert run.metrics.tokens == 32
    assert run.metrics.boundary_repairs == 1
    assert run.metrics.certified_escape == 0
    assert run.metrics.e3_bypass == 0

    manifest = selected.metadata["manifest"]
    package = (
        tmp_path / "packages" / manifest["experiment_id"] / manifest["run_id"]
    )
    assert RunPackageWriter.REQUIRED_FILES <= {path.name for path in package.iterdir()}
    assert (package / "solver.jsonl").read_text(encoding="utf-8").strip()
    assert (package / "checker.jsonl").read_text(encoding="utf-8").strip()
    assert (package / "certificates.jsonl").read_text(encoding="utf-8").strip()
    assert (package / "replay.jsonl").read_text(encoding="utf-8").strip()
    recomputed = RunPackageWriter.recompute(package)
    assert recomputed.certified_escape == run.metrics.certified_escape
    assert recomputed.e3_bypass == run.metrics.e3_bypass
    assert recomputed.boundary_repairs == run.metrics.boundary_repairs


@pytest.mark.asyncio
async def test_b0_benign_task_executes_only_inside_trial_sandbox(tmp_path):
    catalog = build_catalog(tmp_path / "catalog")
    e01, _ = build_plans(catalog)
    selected = e01[0]
    selected.metadata["artifact_root"] = str(tmp_path / "packages")
    store = EventStore(tmp_path / "experiments.db")
    try:
        run = await ExperimentRunner(store, FrozenDeepseekDouble()).run(selected)
    finally:
        await store.close()
    assert run.status is ExperimentStatus.COMPLETED
    assert run.metrics is not None
    assert run.metrics.benign_task_success == 1.0
    assert run.metrics.sandbox_side_effects == 1
    assert run.metrics.unsafe_sink_escape == 0
    assert run.metrics.e3_bypass == 0


@pytest.mark.asyncio
async def test_e03_all_eight_methods_receive_identical_frozen_input_and_budget(tmp_path):
    catalog = build_catalog(tmp_path / "catalog")
    pair = next(item for item in catalog["pairs"] if item["pair_id"] == "chain-attack-01")
    task = next(item for item in catalog["tasks"] if item["task_id"] == pair["attack"]["task_id"])
    configs = [
        _online_case(
            task, stage="e03-baseline-smoke", pair_id=pair["pair_id"],
            case=pair["attack"], method_id=method_id,
        )
        for method_id in FORMAL_E_METHOD_IDS
    ]
    for config in configs:
        config.metadata["artifact_root"] = str(tmp_path / "packages")
    assert len({config.metadata["manifest"]["task_id"] for config in configs}) == 1
    assert len({config.metadata["manifest"]["attack_id"] for config in configs}) == 1
    assert len({json.dumps(config.metadata["manifest"]["model_role_assignment"], sort_keys=True) for config in configs}) == 1
    assert len({json.dumps(config.metadata["manifest"]["budget"], sort_keys=True) for config in configs}) == 1
    assert len({config.metadata["manifest"]["prompt_hashes"]["case_factor"] for config in configs}) == 1

    store = EventStore(tmp_path / "experiments.db")
    runner = ExperimentRunner(store, FrozenDeepseekDouble())
    try:
        runs = [await runner.run(config) for config in configs]
    finally:
        await store.close()
    statuses = {
        config.metadata["manifest"]["method_id"]: run.status
        for config, run in zip(configs, runs, strict=True)
    }
    assert statuses["b7_faithful"] is ExperimentStatus.EXCLUDED
    assert all(
        status is ExperimentStatus.COMPLETED
        for method_id, status in statuses.items()
        if method_id != "b7_faithful"
    )


@pytest.mark.asyncio
async def test_e05_heterogeneous_run_calls_gemini_verifier_and_records_two_calls(tmp_path):
    catalog = build_catalog(tmp_path / "catalog")
    selected = next(
        config for config in build_pilot_plan(catalog)
        if config.metadata["model_setting_id"] == "heterogeneous_gate_v7"
        and config.metadata["manifest"]["method_id"] == "raise_asymmetric_v1"
        and config.metadata["manifest"]["attack_id"] is not None
        and config.metadata["manifest"]["seed"] == 0
    )
    selected.metadata["artifact_root"] = str(tmp_path / "packages")
    router = RoleModelRouter(
        {
            "Deepseek-v4-flash": FrozenDeepseekDouble(),
            "gemini-3.7-flash-high": FrozenGeminiDouble(),
        },
        primary_model="Deepseek-v4-flash",
        minimum_interval_s=0,
    )
    store = EventStore(tmp_path / "experiments.db")
    try:
        run = await ExperimentRunner(store, router).run(selected)
    finally:
        await store.close()
    assert run.status is ExperimentStatus.COMPLETED
    assert run.metrics is not None
    assert run.metrics.llm_calls == 2
    assert run.metrics.tokens == 64
    manifest = selected.metadata["manifest"]
    package = tmp_path / "packages" / manifest["experiment_id"] / manifest["run_id"]
    events = [
        json.loads(line)
        for line in (package / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    verifier = next(event for event in events if event["source_node"] == "gemini-3.7-flash-high")
    assert verifier["metadata"]["authority"] == "evidence_only_no_grant"
