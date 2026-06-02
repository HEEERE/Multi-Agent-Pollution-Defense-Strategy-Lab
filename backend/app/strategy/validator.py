from app.schemas.strategies import StrategyValidationIssue, StrategyValidationResult

VALID_NODE_TYPES = {"gateway", "agent", "tool", "monitor", "memory"}
VALID_INJECTION_TYPES = {
    "prompt_injection",
    "rag_poisoning",
    "tool_pollution",
    "cognitive_deception",
}
VALID_ACTIONS = {"allow", "alert", "block", "quarantine", "isolate", "human_review"}


def validate_strategy(content: dict) -> StrategyValidationResult:
    issues: list[StrategyValidationIssue] = []

    topology = content.get("topology")
    if not isinstance(topology, dict):
        return StrategyValidationResult(
            valid=False,
            issues=[
                StrategyValidationIssue(
                    path="topology",
                    message="topology is required and must be a dict",
                )
            ],
        )

    nodes = topology.get("nodes", [])
    if not nodes:
        issues.append(
            StrategyValidationIssue(
                path="topology.nodes", message="at least one node is required"
            )
        )

    node_ids: list[str] = []
    for i, node in enumerate(nodes):
        nid = node.get("node_id")
        if not nid:
            issues.append(
                StrategyValidationIssue(
                    path=f"topology.nodes[{i}].node_id",
                    message="node_id is required",
                )
            )
        else:
            node_ids.append(nid)

        nt = node.get("node_type")
        if nt not in VALID_NODE_TYPES:
            issues.append(
                StrategyValidationIssue(
                    path=f"topology.nodes[{i}].node_type",
                    message=f"invalid node_type '{nt}' (expected one of {sorted(VALID_NODE_TYPES)})",
                )
            )

    dupes = {n for n in node_ids if node_ids.count(n) > 1}
    for d in dupes:
        issues.append(
            StrategyValidationIssue(
                path="topology.nodes", message=f"duplicate node_id: '{d}'"
            )
        )

    node_set = set(node_ids)

    edges = topology.get("edges", [])
    for i, edge in enumerate(edges):
        src = edge.get("source")
        tgt = edge.get("target")
        if src and src not in node_set:
            issues.append(
                StrategyValidationIssue(
                    path=f"topology.edges[{i}].source",
                    message=f"source node '{src}' does not exist",
                )
            )
        if tgt and tgt not in node_set:
            issues.append(
                StrategyValidationIssue(
                    path=f"topology.edges[{i}].target",
                    message=f"target node '{tgt}' does not exist",
                )
            )

    injections = topology.get("injections", [])
    for i, inj in enumerate(injections):
        inj_type = inj.get("injection_type")
        if inj_type and inj_type not in VALID_INJECTION_TYPES:
            issues.append(
                StrategyValidationIssue(
                    path=f"topology.injections[{i}].injection_type",
                    message=f"invalid injection_type '{inj_type}'",
                )
            )
        src_node = inj.get("source_node")
        if src_node and src_node not in node_set:
            issues.append(
                StrategyValidationIssue(
                    path=f"topology.injections[{i}].source_node",
                    message=f"source_node '{src_node}' does not exist",
                )
            )
        tgt_node = inj.get("target_node")
        if tgt_node and tgt_node not in node_set:
            issues.append(
                StrategyValidationIssue(
                    path=f"topology.injections[{i}].target_node",
                    message=f"target_node '{tgt_node}' does not exist",
                )
            )
        if not inj.get("payload"):
            issues.append(
                StrategyValidationIssue(
                    path=f"topology.injections[{i}].payload",
                    message="payload cannot be empty",
                )
            )

    max_turns = topology.get("max_turns", 5)
    if not isinstance(max_turns, int) or max_turns < 1 or max_turns > 100:
        issues.append(
            StrategyValidationIssue(
                path="topology.max_turns",
                message="max_turns must be an integer between 1 and 100",
            )
        )
    elif max_turns > 50:
        issues.append(
            StrategyValidationIssue(
                path="topology.max_turns",
                message="max_turns > 50 may result in long run times",
                level="warning",
            )
        )

    policies = content.get("policies", [])
    if isinstance(policies, list):
        policy_ids: list[str] = []
        for i, policy in enumerate(policies):
            pid = policy.get("policy_id")
            if pid:
                policy_ids.append(pid)
            action = policy.get("action")
            if action and action not in VALID_ACTIONS:
                issues.append(
                    StrategyValidationIssue(
                        path=f"policies[{i}].action",
                        message=f"invalid action '{action}' (expected one of {sorted(VALID_ACTIONS)})",
                    )
                )
            condition = policy.get("condition", {})
            score = condition.get("min_contamination_score")
            if score is not None:
                if not isinstance(score, (int, float)) or score < 0 or score > 1:
                    issues.append(
                        StrategyValidationIssue(
                            path=f"policies[{i}].condition.min_contamination_score",
                            message="min_contamination_score must be between 0 and 1",
                        )
                    )

        pdupes = {p for p in policy_ids if policy_ids.count(p) > 1}
        for p in pdupes:
            issues.append(
                StrategyValidationIssue(
                    path="policies", message=f"duplicate policy_id: '{p}'"
                )
            )

    return StrategyValidationResult(
        valid=not any(i.level == "error" for i in issues), issues=issues
    )
