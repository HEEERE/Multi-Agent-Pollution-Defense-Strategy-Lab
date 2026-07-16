from app.detectors.base import BaseDetector
from app.detectors.llm_detector import LLMIntentDetector
from app.detectors.pipeline import DetectorPipeline
from app.detectors.rag_detector import RAGFeatureDetector
from app.detectors.regex_detector import RegexDetector
from app.detectors.semantic_detector import SemanticDetector
from app.llm.base import LLMClient
from app.message_bus import MessageBus
from app.policy.engine import PolicyEngine
from app.schemas import (
    ActionPolicy,
    DetectorConfig,
    DetectorPipelineConfig,
    DetectorType,
    EventSeverity,
    MonitorLevel,
)


def create_detector(cfg: DetectorConfig, llm_client: LLMClient | None = None) -> BaseDetector | None:
    if not cfg.enabled:
        return None

    if cfg.detector_type == DetectorType.REGEX:
        det = RegexDetector(
            custom_patterns=cfg.params.get("patterns") if cfg.params else None,
        )
    elif cfg.detector_type == DetectorType.RAG_FEATURE:
        det = RAGFeatureDetector(
            custom_markers=set(cfg.params.get("markers", [])) if cfg.params else None,
        )
    elif cfg.detector_type == DetectorType.SEMANTIC:
        det = SemanticDetector(
            threshold=cfg.params.get("threshold", 0.65) if cfg.params else 0.65,
            top_k=cfg.params.get("top_k", 5) if cfg.params else 5,
        )
    elif cfg.detector_type == DetectorType.LLM_INTENT:
        det = LLMIntentDetector(llm_client=llm_client)
    else:
        return None

    det.action_policy = cfg.action_policy
    det.level = cfg.level
    return det


def create_pipeline(
    config: DetectorPipelineConfig,
    llm_client: LLMClient | None = None,
    bus: MessageBus | None = None,
    defense_coordinator=None,
    policy_engine=None,
) -> DetectorPipeline:
    detectors: list[BaseDetector] = []
    for cfg in config.detectors:
        det = create_detector(cfg, llm_client)
        if det is not None:
            detectors.append(det)

    return DetectorPipeline(
        detectors=detectors,
        short_circuit=config.short_circuit,
        log_all=config.log_all_detections,
        min_severity_for_llm=config.min_severity_for_llm,
        bus=bus,
        policy_engine=policy_engine or PolicyEngine(),
        defense_coordinator=defense_coordinator,
    )


def create_default_pipeline(
    llm_client: LLMClient | None = None,
    bus: MessageBus | None = None,
    defense_coordinator=None,
) -> DetectorPipeline:
    from app.settings_manager import get_settings_manager
    mgr = get_settings_manager()

    l1_enabled = mgr.get_value_sync("detectors", "regex.enabled", True)
    l1_action = mgr.get_value_sync("detectors", "regex.action_policy", "block")
    l2_enabled = mgr.get_value_sync("detectors", "semantic.enabled", True)
    l2_threshold = mgr.get_value_sync("detectors", "semantic.threshold", 0.65)
    l2_top_k = mgr.get_value_sync("detectors", "semantic.top_k", 5)
    l2_action = mgr.get_value_sync("detectors", "semantic.action_policy", "quarantine")
    l3_enabled = mgr.get_value_sync("detectors", "llm_intent.enabled", True)
    l3_action = mgr.get_value_sync("detectors", "llm_intent.action_policy", "quarantine")
    short_circuit = mgr.get_value_sync("detectors", "pipeline.short_circuit", True)
    log_all = mgr.get_value_sync("detectors", "pipeline.log_all_detections", True)
    min_sev = mgr.get_value_sync("detectors", "pipeline.min_severity_for_llm", "warning")

    config = DetectorPipelineConfig(
        detectors=[
            DetectorConfig(
                detector_id="regex",
                detector_type=DetectorType.REGEX,
                enabled=bool(l1_enabled),
                level=MonitorLevel.HEURISTIC,
                action_policy=ActionPolicy(str(l1_action)),
            ),
            DetectorConfig(
                detector_id="semantic",
                detector_type=DetectorType.SEMANTIC,
                enabled=bool(l2_enabled),
                level=MonitorLevel.FEATURE,
                action_policy=ActionPolicy(str(l2_action)),
                params={"threshold": float(l2_threshold), "top_k": int(l2_top_k)},
            ),
            DetectorConfig(
                detector_id="llm_intent",
                detector_type=DetectorType.LLM_INTENT,
                enabled=bool(l3_enabled),
                level=MonitorLevel.LLM_INTENT,
                action_policy=ActionPolicy(str(l3_action)),
            ),
        ],
        short_circuit=bool(short_circuit),
        log_all_detections=bool(log_all),
        min_severity_for_llm=EventSeverity(str(min_sev)),
    )
    return create_pipeline(config, llm_client, bus, defense_coordinator=defense_coordinator)
