from app.schemas.common import ActionPolicy, EventSeverity, MonitorLevel
from app.schemas.experiments import (
    DetectorConfig,
    DetectorPipelineConfig,
    DetectorType,
    EdgeConfig,
    ExperimentConfig,
    InjectionConfig,
    InjectionType,
    NodeConfig,
    TopologyConfig,
)


def compile_strategy(
    content: dict,
    *,
    run_id: str = "",
    strategy_id: str = "",
    strategy_version: int = 1,
) -> ExperimentConfig:
    topology = content.get("topology", {})

    nodes = [
        NodeConfig(
            node_id=node["node_id"],
            node_type=node.get("node_type", "agent"),
            system_prompt=node.get("system_prompt", ""),
            tools=node.get("tools", []),
            metadata=node.get("metadata", {}),
        )
        for node in topology.get("nodes", [])
    ]

    edges = [
        EdgeConfig(
            source=edge["source"],
            target=edge["target"],
            edge_type=edge.get("edge_type", "direct"),
        )
        for edge in topology.get("edges", [])
    ]

    monitors = topology.get("monitors", [])

    injections = [
        InjectionConfig(
            injection_type=InjectionType(inj["injection_type"]),
            source_node=inj.get("source_node", ""),
            target_node=inj.get("target_node", ""),
            payload=inj.get("payload", ""),
            turn=inj.get("turn", 0),
            metadata=inj.get("metadata", {}),
        )
        for inj in topology.get("injections", [])
    ]

    topology_metadata = dict(topology.get("metadata", {}))
    topology_metadata["run_id"] = run_id
    topology_metadata["strategy_id"] = strategy_id
    topology_metadata["strategy_version"] = strategy_version

    topology_config = TopologyConfig(
        name=topology.get("name", content.get("name", "unnamed-strategy")),
        nodes=nodes,
        edges=edges,
        monitors=monitors,
        injections=injections,
        max_turns=topology.get("max_turns", 5),
        metadata=topology_metadata,
    )

    detector_settings = content.get("detector_settings", {})
    detector_pipeline = _build_detector_pipeline(detector_settings)

    metadata = dict(content.get("metadata", {}))
    metadata["run_id"] = run_id
    metadata["strategy_id"] = strategy_id
    metadata["strategy_version"] = strategy_version
    metadata["policies"] = content.get("policies", [])
    metadata["detector_settings"] = detector_settings

    return ExperimentConfig(
        name=content.get("name", "compiled-strategy"),
        description=content.get("description", ""),
        topology=topology_config,
        detector_pipeline=detector_pipeline,
        num_runs=content.get("num_runs", 1),
        metadata=metadata,
    )


def _build_detector_pipeline(settings: dict) -> DetectorPipelineConfig:
    detectors: list[DetectorConfig] = []

    regex = settings.get("regex", {})
    if regex.get("enabled", True):
        detectors.append(
            DetectorConfig(
                detector_id="regex_0",
                detector_type=DetectorType.REGEX,
                enabled=True,
                action_policy=ActionPolicy(
                    regex.get("action_policy", "block")
                ),
                level=MonitorLevel.HEURISTIC,
                params=regex,
            )
        )

    semantic = settings.get("semantic", {})
    if semantic.get("enabled"):
        detectors.append(
            DetectorConfig(
                detector_id="semantic_0",
                detector_type=DetectorType.SEMANTIC,
                enabled=True,
                action_policy=ActionPolicy(
                    semantic.get("action_policy", "alert")
                ),
                level=MonitorLevel.FEATURE,
                params=semantic,
            )
        )

    llm = settings.get("llm_intent", {})
    if llm.get("enabled"):
        detectors.append(
            DetectorConfig(
                detector_id="llm_0",
                detector_type=DetectorType.LLM_INTENT,
                enabled=True,
                action_policy=ActionPolicy(
                    llm.get("action_policy", "alert")
                ),
                level=MonitorLevel.LLM_INTENT,
                params=llm,
            )
        )

    return DetectorPipelineConfig(
        detectors=detectors,
        short_circuit=settings.get("short_circuit", True),
        log_all_detections=settings.get("log_all_detections", True),
        min_severity_for_llm=EventSeverity.WARNING,
    )
