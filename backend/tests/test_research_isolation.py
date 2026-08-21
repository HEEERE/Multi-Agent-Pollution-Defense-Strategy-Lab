"""Static isolation checks.

Two boundaries the research design depends on, enforced by walking the AST
rather than by convention:

* the online runtime must not import the offline research package;
* the online runtime must not import the experiment Oracle.

Both are checked by parsing every module's import statements, so a violation is
caught even if the import sits inside a function and never executes in tests.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"

# Packages that make up the online request/run path.
ONLINE_DIRS = (
    "api",
    "services",
    "agents",
    "defense",
    "detectors",
    "policy",
    "tools",
    "llm",
    "skills",
    "monitoring",
    "gateway",
    "strategy",
    "trace_graph",
    "simulation",
)

FORBIDDEN_IN_ONLINE = ("app.research", "app.experiments.oracle")


def _imported_modules(path: Path) -> set[str]:
    """Every module name imported by ``path``, including function-local ones."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as exc:  # pragma: no cover
        raise AssertionError(f"could not parse {path}: {exc}") from exc

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                found.add(node.module)
    return found


def _online_files() -> list[Path]:
    files: list[Path] = []
    for d in ONLINE_DIRS:
        root = APP / d
        if root.is_dir():
            files.extend(root.rglob("*.py"))
    # Top-level online modules too.
    files.extend(p for p in APP.glob("*.py"))
    return sorted(files)


def test_online_runtime_does_not_import_research_or_oracle():
    violations: list[str] = []
    for path in _online_files():
        for mod in _imported_modules(path):
            for forbidden in FORBIDDEN_IN_ONLINE:
                if mod == forbidden or mod.startswith(forbidden + "."):
                    rel = path.relative_to(APP.parent)
                    violations.append(f"{rel} imports {mod}")
    assert not violations, (
        "online runtime reaches into offline-only code:\n  "
        + "\n  ".join(violations)
    )


def test_verification_layer_stays_independent_of_solvers():
    """Placeholder boundary for Phase 4.

    The v4 plan requires ``verification/`` to share no implementation with the
    optimiser or the tight-graph builder, so the residual checker cannot inherit
    an optimiser bug. The directory does not exist yet; when it does, this test
    starts enforcing the rule instead of skipping.
    """
    verification = APP / "verification"
    if not verification.is_dir():
        import pytest

        pytest.skip("app/verification does not exist yet (Phase 4)")

    forbidden = ("app.state.exact_solver", "app.state.greedy_solver",
                 "app.provenance.tight_builder")
    violations: list[str] = []
    for path in verification.rglob("*.py"):
        for mod in _imported_modules(path):
            if any(mod == f or mod.startswith(f + ".") for f in forbidden):
                violations.append(f"{path.name} imports {mod}")
    assert not violations, (
        "independent checker shares implementation with the optimiser:\n  "
        + "\n  ".join(violations)
    )


def test_scale_study_is_importable_without_the_runtime():
    """The scale study must stand alone: it produces the Phase 4 gate numbers.

    Only the scale subpackage is checked. ``app.research.e2e_probe`` deliberately
    drives the live runtime, so it is expected to import it; the constraint runs
    the other way (nothing in the runtime may import ``app.research``).
    """
    import importlib

    for name in (
        "app.research.scale.graph",
        "app.research.scale.analysis",
        "app.research.scale.solvers",
        "app.research.scale.experiment",
        "app.research.scale.frontier",
    ):
        mod = importlib.import_module(name)
        for imported in _imported_modules(Path(mod.__file__)):
            assert not imported.startswith("app.") or imported.startswith(
                "app.research."
            ), f"{name} depends on runtime module {imported}"
