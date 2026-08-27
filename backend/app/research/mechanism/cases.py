"""Deterministic M-01 case population and JSON serialization."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any

from app.research.mechanism.oracle import (
    authority_atoms,
    enumerate_reference_witnesses,
    validation_issues,
)
from app.research.scale.graph import (
    Derivation,
    GenSpec,
    Goal,
    Hypergraph,
    Integrity,
    Intervention,
    InterventionKind,
    Sink,
    SupportGroup,
    Version,
    VersionKind,
    generate,
)


SEMANTIC_CLASSES = (
    "single_path",
    "multi_path",
    "shared_choke_point",
    "and_or_support",
    "multi_source_multi_sink",
    "empty_duplicate_isolated_cycle_unsat",
    "snapshot_change",
    "stale_certificate_replay",
    "retained_new_path",
    "missing_provenance",
    "timeout_unknown_unsatisfiable",
    "greedy_exact_divergence",
)

DIVERGENCE_SEEDS = (4, 7, 28, 31, 32)


class _Builder:
    def __init__(self) -> None:
        self.graph = Hypergraph()
        self._topo = 0
        self._did = 0

    def version(
        self,
        version_id: str,
        kind: VersionKind,
        integrity: Integrity = Integrity.HIGH,
        *,
        agent: str = "agent_0",
    ) -> str:
        self.graph.versions[version_id] = Version(
            version_id, kind, integrity, self._topo, agent
        )
        self._topo += 1
        return version_id

    def edge(
        self,
        parents: tuple[str, ...],
        child: str,
        *,
        activity: str | None = None,
        derivation_id: str | None = None,
    ) -> str:
        did = derivation_id or f"d{self._did}"
        self._did += 1
        self.graph.derivations[did] = Derivation(
            did, parents, child, activity or f"activity_{did}"
        )
        return did

    def sink(self, qid: str, version_id: str, effect_class: str = "E3") -> None:
        self.graph.sinks.append(Sink(qid, version_id, effect_class))

    def support(self, goal: str, *members: str, verified: bool = True) -> None:
        if goal not in self.graph.goals:
            self.graph.goals[goal] = Goal(goal, True, 1.0)
        sid = f"s{len(self.graph.support)}"
        self.graph.support[sid] = SupportGroup(sid, goal, tuple(members), verified)

    def finish(self, *, interventions: bool = True) -> Hypergraph:
        if interventions:
            _install_interventions(self.graph)
        self.graph.index()
        return self.graph


def _install_interventions(graph: Hypergraph) -> None:
    graph.interventions.clear()
    iid = 0

    def add(kind: InterventionKind, target: str, cost: float) -> None:
        nonlocal iid
        graph.interventions[f"i{iid}"] = Intervention(
            f"i{iid}", kind, target, cost
        )
        iid += 1

    for version in sorted(graph.versions.values(), key=lambda item: item.topo_index):
        if version.kind is not VersionKind.ARGUMENT:
            add(
                InterventionKind.REVOKE_VERSION,
                version.vid,
                1.0 if version.is_source else 2.0,
            )
    for derivation in sorted(graph.derivations.values(), key=lambda item: item.did):
        add(InterventionKind.DISABLE_EDGE, derivation.did, 1.5)
    for sink in sorted(graph.sinks, key=lambda item: item.qid):
        add(InterventionKind.DENY_ACTION, sink.qid, 8.0)
    agents = sorted({version.agent for version in graph.versions.values() if version.agent})
    for agent in agents:
        add(InterventionKind.QUARANTINE_AGENT, agent, 3.0)


def _conservative_from_tight(tight: Hypergraph) -> Hypergraph:
    conservative = deepcopy(tight)
    conservative.derivations.clear()
    did = 0
    seen: set[tuple[str, str, str]] = set()
    for derivation in sorted(tight.derivations.values(), key=lambda item: item.did):
        for parent in derivation.parents:
            signature = (parent, derivation.child, derivation.activity)
            if signature in seen:
                continue
            seen.add(signature)
            conservative.derivations[f"p1d{did}"] = Derivation(
                f"p1d{did}", (parent,), derivation.child, derivation.activity
            )
            did += 1
    _install_interventions(conservative)
    conservative._by_child = None
    conservative._by_parent = None
    conservative.index()
    return conservative


def _path_case(variant: int) -> Hypergraph:
    builder = _Builder()
    previous = builder.version("low", VersionKind.MESSAGE, Integrity.LOW)
    clean = builder.version("clean", VersionKind.RAG_CHUNK)
    for index in range(variant + 1):
        current = builder.version(f"step_{index}", VersionKind.SUMMARY)
        builder.edge((previous,), current)
        previous = current
    argument = builder.version("arg", VersionKind.ARGUMENT)
    builder.edge((previous,), argument, activity="sink")
    builder.sink("q0", argument)
    builder.support("g0", clean)
    return builder.finish()


def _multi_path_case(variant: int) -> Hypergraph:
    builder = _Builder()
    low = builder.version("low", VersionKind.MESSAGE, Integrity.LOW)
    clean = builder.version("clean", VersionKind.RAG_CHUNK)
    branches = []
    for index in range(2 + (variant % 3)):
        branch = builder.version(f"branch_{index}", VersionKind.SUMMARY)
        builder.edge((low if index % 2 == 0 else clean,), branch)
        if index % 2 == 0:
            branches.append(branch)
    argument = builder.version("arg", VersionKind.ARGUMENT)
    for branch in branches:
        builder.edge((branch,), argument, activity="sink")
    builder.sink("q0", argument)
    builder.support("g0", clean)
    return builder.finish()


def _choke_case(variant: int) -> Hypergraph:
    builder = _Builder()
    lows = [
        builder.version(f"low_{index}", VersionKind.MESSAGE, Integrity.LOW)
        for index in range(2 + (variant % 3))
    ]
    choke = builder.version("choke", VersionKind.PLAN)
    for low in lows:
        builder.edge((low,), choke, activity="merge")
    argument = builder.version("arg", VersionKind.ARGUMENT)
    builder.edge((choke,), argument, activity="sink")
    builder.sink("q0", argument)
    builder.support("g0", choke)
    return builder.finish()


def _and_or_case(variant: int) -> Hypergraph:
    builder = _Builder()
    low = builder.version("low", VersionKind.MESSAGE, Integrity.LOW)
    clean_a = builder.version("clean_a", VersionKind.RAG_CHUNK)
    clean_b = builder.version("clean_b", VersionKind.MESSAGE)
    mixed = builder.version("mixed", VersionKind.SUMMARY)
    builder.edge((low, clean_a), mixed, activity="and_merge")
    builder.edge((clean_b,), mixed, activity="or_alternative")
    if variant % 2:
        extra = builder.version("extra", VersionKind.TOOL_RESULT)
        builder.edge((mixed, clean_a), extra, activity="verified_and")
        tail = extra
    else:
        tail = mixed
    argument = builder.version("arg", VersionKind.ARGUMENT)
    builder.edge((tail,), argument, activity="sink")
    builder.sink("q0", argument)
    builder.support("g0", mixed)
    builder.support("g0", clean_b)
    builder.support("g1", clean_a, clean_b)
    return builder.finish()


def _multi_source_sink_case(variant: int) -> Hypergraph:
    builder = _Builder()
    lows = [
        builder.version(f"low_{index}", VersionKind.MESSAGE, Integrity.LOW)
        for index in range(2 + (variant % 2))
    ]
    clean = builder.version("clean", VersionKind.RAG_CHUNK)
    merged = builder.version("merged", VersionKind.PLAN)
    for low in lows:
        builder.edge((low,), merged, activity="merge")
    sink_count = 1 + (variant % 3)
    for index in range(sink_count):
        argument = builder.version(f"arg_{index}", VersionKind.ARGUMENT)
        builder.edge((merged,), argument, activity=f"sink_{index}")
        builder.sink(f"q{index}", argument, "E3" if index == 0 else "E2")
    builder.support("g0", clean)
    return builder.finish()


def _edge_condition_case(variant: int) -> tuple[Hypergraph, str, str]:
    builder = _Builder()
    if variant == 0:
        clean = builder.version("clean", VersionKind.MESSAGE)
        argument = builder.version("arg", VersionKind.ARGUMENT)
        builder.edge((clean,), argument, activity="sink")
        builder.sink("q0", argument)
        return builder.finish(), "VALID", "COVERED"
    low = builder.version("low", VersionKind.MESSAGE, Integrity.LOW)
    if variant == 1:
        middle = builder.version("middle", VersionKind.SUMMARY)
        builder.edge((low,), middle, activity="duplicate")
        builder.edge((low,), middle, activity="duplicate")
        argument = builder.version("arg", VersionKind.ARGUMENT)
        builder.edge((middle,), argument, activity="sink")
        builder.sink("q0", argument)
        return builder.finish(), "INVALID_DUPLICATE", "EXCLUDED"
    if variant == 2:
        builder.version("isolated", VersionKind.MEMORY)
        argument = builder.version("arg", VersionKind.ARGUMENT)
        builder.edge((low,), argument, activity="sink")
        builder.sink("q0", argument)
        return builder.finish(), "VALID", "COVERED"
    if variant == 3:
        first = builder.version("first", VersionKind.SUMMARY)
        second = builder.version("second", VersionKind.PLAN)
        argument = builder.version("arg", VersionKind.ARGUMENT)
        builder.edge((low,), first)
        builder.edge((first,), second)
        builder.edge((second,), first, activity="cycle")
        builder.edge((second,), argument, activity="sink")
        builder.sink("q0", argument)
        return builder.finish(), "INVALID_CYCLE", "EXCLUDED"
    argument = builder.version("arg", VersionKind.ARGUMENT)
    builder.edge((low,), argument, activity="sink")
    builder.sink("q0", argument)
    return builder.finish(interventions=False), "VALID", "UNSATISFIABLE"


def _retention_case() -> Hypergraph:
    builder = _Builder()
    low = builder.version("low", VersionKind.MESSAGE, Integrity.LOW)
    stash = builder.version("stash", VersionKind.MEMORY)
    clean = builder.version("clean", VersionKind.MESSAGE)
    argument = builder.version("arg", VersionKind.ARGUMENT)
    builder.edge((low,), stash, activity="park")
    builder.edge((clean,), argument, activity="sink")
    builder.sink("q0", argument)
    builder.support("g0", clean)
    return builder.finish()


def _missing_provenance_case(variant: int) -> Hypergraph:
    builder = _Builder()
    builder.version("visible_low", VersionKind.MESSAGE, Integrity.LOW)
    argument = builder.version("arg", VersionKind.ARGUMENT)
    builder.sink("q0", argument, "E2" if variant % 2 else "E3")
    return builder.finish()


def _base_for_class(semantic_class: str, variant: int) -> tuple[Hypergraph, str, str, dict[str, Any]]:
    metadata: dict[str, Any] = {}
    if semantic_class == "single_path":
        return _path_case(variant), "VALID", "COVERED", metadata
    if semantic_class == "multi_path":
        return _multi_path_case(variant), "VALID", "COVERED", metadata
    if semantic_class == "shared_choke_point":
        return _choke_case(variant), "VALID", "COVERED", metadata
    if semantic_class == "and_or_support":
        return _and_or_case(variant), "VALID", "COVERED", metadata
    if semantic_class == "multi_source_multi_sink":
        return _multi_source_sink_case(variant), "VALID", "COVERED", metadata
    if semantic_class == "empty_duplicate_isolated_cycle_unsat":
        graph, validation, status = _edge_condition_case(variant)
        return graph, validation, status, {"edge_condition": variant}
    if semantic_class in {"snapshot_change", "stale_certificate_replay"}:
        metadata["certificate_scenario"] = semantic_class
        return _path_case(variant), "VALID", "COVERED", metadata
    if semantic_class == "retained_new_path":
        metadata["dynamic_edge"] = {"parents": ["stash"], "child": "arg"}
        return _retention_case(), "VALID", "COVERED", metadata
    if semantic_class == "missing_provenance":
        metadata["missing_artifact_refs"] = True
        return _missing_provenance_case(variant), "VALID", "UNKNOWN", metadata
    if semantic_class == "timeout_unknown_unsatisfiable":
        graph = _path_case(variant)
        if variant < 2:
            metadata["witness_cap"] = 0
            return graph, "VALID", "UNKNOWN", metadata
        if variant < 4:
            graph.interventions.clear()
            return graph, "VALID", "UNSATISFIABLE", metadata
        return graph, "VALID", "COVERED", metadata
    if semantic_class == "greedy_exact_divergence":
        seed = DIVERGENCE_SEEDS[variant]
        spec = GenSpec(
            context_size=3,
            hops=4,
            n_sinks=2,
            chain_width=1,
            side_branch_per_hop=1,
            n_goals=2,
            seed=seed,
        )
        metadata["selected_counterexample_seed"] = seed
        metadata["expect_greedy_strictly_worse"] = True
        return generate(spec, conservative=False), "VALID", "COVERED", metadata
    raise KeyError(semantic_class)


def graph_to_dict(graph: Hypergraph) -> dict[str, Any]:
    return {
        "versions": [
            {
                **asdict(version),
                "kind": str(version.kind),
                "integrity": str(version.integrity),
            }
            for version in sorted(graph.versions.values(), key=lambda item: item.topo_index)
        ],
        "derivations": [asdict(item) for item in sorted(graph.derivations.values(), key=lambda item: item.did)],
        "sinks": [asdict(item) for item in sorted(graph.sinks, key=lambda item: item.qid)],
        "interventions": [
            {**asdict(item), "kind": str(item.kind)}
            for item in sorted(graph.interventions.values(), key=lambda item: item.iid)
        ],
        "goals": [asdict(item) for item in sorted(graph.goals.values(), key=lambda item: item.gid)],
        "support": [asdict(item) for item in sorted(graph.support.values(), key=lambda item: item.sid)],
    }


def graph_from_dict(payload: dict[str, Any]) -> Hypergraph:
    graph = Hypergraph()
    for row in payload["versions"]:
        version = Version(
            row["vid"], VersionKind(row["kind"]), Integrity(row["integrity"]),
            int(row["topo_index"]), row.get("agent", ""),
        )
        graph.versions[version.vid] = version
    for row in payload["derivations"]:
        derivation = Derivation(
            row["did"], tuple(row["parents"]), row["child"], row["activity"]
        )
        graph.derivations[derivation.did] = derivation
    graph.sinks = [Sink(**row) for row in payload["sinks"]]
    for row in payload["interventions"]:
        intervention = Intervention(
            row["iid"], InterventionKind(row["kind"]), row["target"], float(row["cost"])
        )
        graph.interventions[intervention.iid] = intervention
    for row in payload["goals"]:
        goal = Goal(**row)
        graph.goals[goal.gid] = goal
    for row in payload["support"]:
        support = SupportGroup(
            row["sid"], row["goal"], tuple(row["members"]), bool(row.get("verified", True))
        )
        graph.support[support.sid] = support
    graph.index()
    return graph


def _oracle_payload(case_id: str, tight: Hypergraph, expected_status: str, validation: str) -> dict[str, Any]:
    issues = validation_issues(tight)
    invalid = validation.startswith("INVALID")
    witnesses = [] if invalid else enumerate_reference_witnesses(tight)
    return {
        "schema_version": "majd-mechanism-oracle-v1",
        "case_id": case_id,
        "expected_validation": validation,
        "expected_status": expected_status,
        "validation_issues": issues,
        "truth_authority_edges": [list(edge) for edge in sorted(authority_atoms(tight))],
        "truth_witness_signatures": [
            {"sink": sink, "low_sources": [source]}
            for sink, source in sorted(
                {
                    (witness.root_qid, source)
                    for witness in witnesses
                    for source in witness.versions & tight.low_integrity_sources
                }
            )
        ],
        "truth_support": [
            {
                "goal": goal,
                "groups": [
                    {"members": list(group.members), "verified": group.verified}
                    for group in sorted(tight.support_for(goal), key=lambda item: item.sid)
                ],
            }
            for goal in sorted(tight.goals)
        ],
    }


def generate_case_records() -> list[tuple[dict[str, Any], dict[str, Any]]]:
    records: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for class_index, semantic_class in enumerate(SEMANTIC_CLASSES, start=1):
        for variant in range(5):
            case_id = f"M01-{class_index:02d}-{variant + 1:02d}"
            tight, validation, expected_status, metadata = _base_for_class(
                semantic_class, variant
            )
            if semantic_class == "greedy_exact_divergence":
                seed = DIVERGENCE_SEEDS[variant]
                spec = GenSpec(
                    context_size=3, hops=4, n_sinks=2, chain_width=1,
                    side_branch_per_hop=1, n_goals=2, seed=seed,
                )
                conservative = generate(spec, conservative=True)
            else:
                conservative = _conservative_from_tight(tight)
                if not tight.interventions:
                    conservative.interventions.clear()
            case = {
                "schema_version": "majd-mechanism-case-v1",
                "case_id": case_id,
                "semantic_class": semantic_class,
                "variant": variant + 1,
                "expected_validation": validation,
                "metadata": metadata,
                "tight_graph": graph_to_dict(tight),
                "conservative_graph": graph_to_dict(conservative),
            }
            records.append(
                (case, _oracle_payload(case_id, tight, expected_status, validation))
            )
    return records


def validate_case_record(case: dict[str, Any], oracle: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    required_case = {
        "schema_version", "case_id", "semantic_class", "variant",
        "expected_validation", "metadata", "tight_graph", "conservative_graph",
    }
    required_oracle = {
        "schema_version", "case_id", "expected_validation", "expected_status",
        "validation_issues", "truth_authority_edges", "truth_witness_signatures",
        "truth_support",
    }
    if set(case) != required_case:
        issues.append("case_schema_keys")
    if set(oracle) != required_oracle:
        issues.append("oracle_schema_keys")
    if case.get("case_id") != oracle.get("case_id"):
        issues.append("case_oracle_id_mismatch")
    if case.get("semantic_class") not in SEMANTIC_CLASSES:
        issues.append("unknown_semantic_class")
    if not isinstance(case.get("variant"), int) or not 1 <= case["variant"] <= 5:
        issues.append("variant_range")
    if "oracle" in case or "expected_status" in case:
        issues.append("oracle_leak_in_case")
    if not issues:
        graph = graph_from_dict(case["tight_graph"])
        found = validation_issues(graph)
        expected_validation = case["expected_validation"]
        if expected_validation == "VALID" and found:
            issues.append(f"unexpected_validation_issue:{found}")
        if expected_validation == "INVALID_DUPLICATE" and not any(
            item.startswith("duplicate_derivation") for item in found
        ):
            issues.append("duplicate_not_detected")
        if expected_validation == "INVALID_CYCLE" and "cycle" not in found:
            issues.append("cycle_not_detected")
        if found != oracle["validation_issues"]:
            issues.append("oracle_validation_mismatch")
    return issues
