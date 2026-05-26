from app.detectors.base import BaseDetector
from app.detectors.llm_detector import LLMIntentDetector
from app.detectors.pipeline import DetectorPipeline
from app.detectors.rag_detector import RAGFeatureDetector
from app.detectors.regex_detector import RegexDetector
from app.detectors.semantic_detector import SemanticDetector
from app.llm.base import LLMClient
from app.message_bus import MessageBus
from app.schemas import (
    ActionPolicy,
    DetectorConfig,
    DetectorPipelineConfig,
    DetectorType,
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
    )


def create_default_pipeline(
    llm_client: LLMClient | None = None,
    bus: MessageBus | None = None,
) -> DetectorPipeline:
    config = DetectorPipelineConfig(
        detectors=[
            DetectorConfig(
                detector_id="regex",
                detector_type=DetectorType.REGEX,
                level=MonitorLevel.HEURISTIC,
                action_policy=ActionPolicy.BLOCK,
            ),
            DetectorConfig(
                detector_id="semantic",
                detector_type=DetectorType.SEMANTIC,
                level=MonitorLevel.FEATURE,
                action_policy=ActionPolicy.QUARANTINE,
                params={"threshold": 0.65, "top_k": 5},
            ),
            DetectorConfig(
                detector_id="llm_intent",
                detector_type=DetectorType.LLM_INTENT,
                level=MonitorLevel.LLM_INTENT,
                action_policy=ActionPolicy.QUARANTINE,
            ),
        ],
        short_circuit=True,
        log_all_detections=True,
    )
    return create_pipeline(config, llm_client, bus)
