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


SOLVER_AND_TIGHT_MODULES = (
    "app.state.exact_solver",
    "app.state.greedy_solver",
    "app.state.asymmetric_repair",
    "app.provenance.tight_builder",
)


def _forbidden_imports(root: Path, forbidden: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for mod in _imported_modules(path):
            if any(mod == f or mod.startswith(f + ".") for f in forbidden):
                violations.append(f"{path.name} imports {mod}")
    return violations


def test_forbidden_modules_all_exist():
    """Guard against the boundary test passing because its targets are missing.

    ``test_verification_layer_stays_independent_of_solvers`` can only catch a
    violation of modules that exist. If one is renamed or deleted, the check
    silently degrades into a tautology, so assert presence separately.
    """
    missing = [
        name for name in SOLVER_AND_TIGHT_MODULES
        if not (APP / Path(*name.split(".")[1:])).with_suffix(".py").is_file()
    ]
    assert not missing, (
        "boundary test would be vacuous — these modules no longer exist: "
        + ", ".join(missing)
    )


def test_verification_layer_stays_independent_of_solvers():
    """``verification/`` must share no implementation with the optimiser.

    The v4 plan (§4.2, §11.1) requires the independent checker to re-derive its
    own conclusions. If it imported the solver it could inherit the solver's
    bug and then certify it; if it imported the tight builder it could inherit
    the tight view's optimism. Enforced structurally, not by convention.
    """
    violations = _forbidden_imports(APP / "verification", SOLVER_AND_TIGHT_MODULES)
    assert not violations, (
        "independent checker shares implementation with the optimiser:\n  "
        + "\n  ".join(violations)
    )


def test_verification_layer_does_not_import_state_at_all():
    """``verification/`` depends only on ``provenance/`` and itself.

    Stronger than §11.1, and it earns its keep twice over. ``state/`` imports
    ``verification/`` (the repair plan calls the independent checker), so any
    import back the other way is a cycle waiting to happen — one did happen, via
    ``state.costs``, and this is what keeps it from coming back. It also removes
    the need to argue case-by-case about which ``state`` modules are safe to
    share: the checker takes the residual view as plain sets and re-derives the
    rest.
    """
    allowed = ("app.provenance", "app.verification")
    violations: list[str] = []
    for path in sorted((APP / "verification").rglob("*.py")):
        for mod in _imported_modules(path):
            if mod.startswith("app.") and not mod.startswith(allowed):
                violations.append(f"{path.name} imports {mod}")
    assert not violations, (
        "verification/ must depend only on provenance/ and itself:\n  "
        + "\n  ".join(violations)
    )


def test_actions_layer_does_not_import_the_state_authority():
    """``actions/`` is the policy and execution boundary; ``state/`` is the state
    authority. The dependency may only run state -> actions.

    v4 §8.4 requires the gateway to invoke the asymmetric repair at every
    contamination denial, which is a pull in the forbidden direction. It is
    resolved by injection: ``ActionGateway`` holds a duck-typed
    ``boundary_repair`` handle that ``RunEngine.create_run`` supplies, because
    only the run knows its ``horizon_closure``. If someone later imports
    ``app.state`` here to "simplify" that, the cycle comes back.
    """
    violations = _forbidden_imports(APP / "actions", ("app.state",))
    assert not violations, (
        "actions/ must not depend on the state authority; inject instead:\n  "
        + "\n  ".join(violations)
    )


def test_tight_builder_is_not_reachable_through_the_graph_type():
    """The graph *type* must not drag the tight builder in with it.

    ``verification/`` legitimately imports ``provenance.projection`` for the
    ProvenanceGraph type. That import must not transitively expose the tight
    builder, otherwise the boundary above is trivially bypassable.
    """
    imported = _imported_modules(APP / "provenance" / "projection.py")
    assert "app.provenance.tight_builder" not in imported
    assert "app.provenance.conservative_builder" not in imported


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
