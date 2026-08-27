from __future__ import annotations

import ast
from collections import Counter
from dataclasses import fields
import json
from pathlib import Path

import pytest

from app.research.mechanism.cases import (
    SEMANTIC_CLASSES,
    generate_case_records,
    validate_case_record,
)
from app.research.mechanism.runner import (
    _m02,
    _m03,
    freeze_preopen,
    run_heldout,
    run_public,
    verify_preopen,
)
from app.research.scale.graph import GenSpec, generate
from app.research.scale.raise_mechanism import raise_solve
from app.verification.certificate_checker import Certificate


def test_m01_has_exactly_sixty_separate_schema_valid_case_oracle_pairs():
    records = generate_case_records()

    assert len(records) == 60
    assert Counter(case["semantic_class"] for case, _oracle in records) == {
        semantic_class: 5 for semantic_class in SEMANTIC_CLASSES
    }
    assert len({case["case_id"] for case, _oracle in records}) == 60
    for case, oracle in records:
        assert validate_case_record(case, oracle) == []
        assert "oracle" not in case
        assert "expected_status" not in case
        assert oracle["case_id"] == case["case_id"]


def test_reference_oracle_does_not_import_production_algorithm_or_runtime():
    oracle_path = (
        Path(__file__).resolve().parent.parent
        / "app/research/mechanism/oracle.py"
    )
    tree = ast.parse(oracle_path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    forbidden = (
        "app.research.scale.analysis",
        "app.research.scale.solvers",
        "app.research.scale.checker",
        "app.runtime",
        "app.state",
        "app.verification",
    )
    assert not {
        imported for imported in imports
        if any(imported == item or imported.startswith(item + ".") for item in forbidden)
    }


def test_m02_public_truth_and_solver_gates_pass(tmp_path):
    result = _m02(tmp_path, generate_case_records())

    assert result["gate_pass"]
    assert all(result["gates"].values())
    assert result["counts"] == {
        "COVERED": 48,
        "EXCLUDED": 2,
        "UNKNOWN": 7,
        "UNSATISFIABLE": 3,
    }
    assert (tmp_path / "tables/m02_correctness.csv").is_file()
    assert (tmp_path / "results/m02_counterexamples.json").is_file()


def test_m03_mutates_every_certificate_field_and_closes_retention_gates(tmp_path):
    result = _m03(tmp_path)

    assert result["gate_pass"]
    assert all(result["gates"].values())
    assert set(result["certificate_fields"]) == {
        field.name for field in fields(Certificate)
    }
    assert result["mutation_trials"] == len(fields(Certificate)) * 5
    assert all(not row["mutant_accepted"] for row in result["mutation_rows"])


def test_dual_graph_retention_translates_semantic_interventions_not_opaque_ids():
    spec = GenSpec(
        context_size=16, hops=5, n_sinks=2, chain_width=3, seed=2
    )
    tight = generate(spec, conservative=False)
    conservative = generate(spec, conservative=True)

    assert len(tight.derivations) != len(conservative.derivations)
    result = raise_solve(tight, conservative, witness_cap=20_000)

    assert result.certificate.post_state_witnesses == 0
    assert not (result.certificate.valid and result.outcome.escaped)


def test_quick_public_package_freeze_and_single_open_heldout_contract(tmp_path):
    root = tmp_path / "mechanism"
    status = run_public(root, quick=True)

    assert status["gate_pass"]
    assert json.loads((root / "status.json").read_text(encoding="utf-8"))["status"] == "COMPLETED"
    assert len(list((root / "cases").glob("*.json"))) == 60
    assert len(list((root / "oracle").glob("*.json"))) == 60
    assert not (root / "heldout-opened.json").exists()

    frozen = freeze_preopen(root)
    assert frozen["heldout_dataset_sha256"] == "da7afe16cafc3e3f62513941d0999a6ba7555415386ef3c8136715f1d0129a08"
    assert verify_preopen(root) == frozen

    heldout = run_heldout(root, limit=2)
    assert heldout["decision"] == "GO_E_CANARY"
    assert heldout["statuses"] == {"COMPLETED": 2}
    assert all(heldout["gates"].values())
    with pytest.raises(FileExistsError, match="already been opened"):
        run_heldout(root, limit=2)
