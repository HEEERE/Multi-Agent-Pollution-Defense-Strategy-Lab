from app.detectors.base import BaseDetector
from app.detectors.llm_detector import LLMIntentDetector
from app.detectors.pipeline import DetectorPipeline
from app.detectors.rag_detector import RAGFeatureDetector
from app.detectors.regex_detector import RegexDetector
from app.llm.base import LLMClient
from app.schemas import DetectorConfig, DetectorPipelineConfig, DetectorType


def create_detector(cfg: DetectorConfig, llm_client: LLMClient | None = None) -> BaseDetector | None:
    if not cfg.enabled:
        return None

    if cfg.detector_type == DetectorType.REGEX:
        return RegexDetector(
            custom_patterns=cfg.params.get("patterns") if cfg.params else None,
        )
    elif cfg.detector_type == DetectorType.RAG_FEATURE:
        return RAGFeatureDetector(
            custom_markers=set(cfg.params.get("markers", [])) if cfg.params else None,
        )
    elif cfg.detector_type == DetectorType.LLM_INTENT:
        return LLMIntentDetector(llm_client=llm_client)

    return None


def create_pipeline(
    config: DetectorPipelineConfig,
    llm_client: LLMClient | None = None,
) -> DetectorPipeline:
    detectors: list[BaseDetector] = []
    for cfg in config.detectors:
        det = create_detector(cfg, llm_client)
        if det is not None:
            det.action_policy = cfg.action_policy
            det.level = cfg.level
            detectors.append(det)

    return DetectorPipeline(
        detectors=detectors,
        short_circuit=config.short_circuit,
        log_all=config.log_all_detections,
        min_severity_for_llm=config.min_severity_for_llm,
    )


def create_default_pipeline(llm_client: LLMClient | None = None) -> DetectorPipeline:
    config = DetectorPipelineConfig(
        detectors=[
            DetectorConfig(
                detector_id="regex",
                detector_type=DetectorType.REGEX,
                level=1,
                action_policy="block",
            ),
            DetectorConfig(
                detector_id="rag_feature",
                detector_type=DetectorType.RAG_FEATURE,
                level=2,
                action_policy="quarantine",
            ),
            DetectorConfig(
                detector_id="llm_intent",
                detector_type=DetectorType.LLM_INTENT,
                level=3,
                action_policy="quarantine",
            ),
        ],
        short_circuit=True,
        log_all_detections=True,
    )
    return create_pipeline(config, llm_client)
