"""Benchmark system for reproducible safety testing."""

from time import perf_counter, time
from typing import Any

from app.benchmark.heldout import DATASET_ID, DATASET_SHA256, HELDOUT_PAYLOADS
from app.detectors.factory import create_pipeline
from app.detectors.pipeline import DetectorPipeline
from app.event_store import EventStore
from app.llm.base import LLMClient
from app.message_bus import MessageBus
from app.schemas import (
    ActionPolicy,
    AgentEvent,
    DetectorConfig,
    DetectorPipelineConfig,
    DetectorType,
    EventSeverity,
    EventType,
    LevelStats,
    BenchmarkReport,
    MonitorLevel,
)

# Kept as a module-level alias so tests can inject small deterministic corpora.
BENCHMARK_PAYLOADS = HELDOUT_PAYLOADS


def _new_id() -> str:
    import uuid
    return uuid.uuid4().hex[:12]


class BenchmarkRunner:
    def __init__(
        self,
        llm_client: LLMClient | None = None,
        event_store: EventStore | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.event_store = event_store

    async def run(self) -> BenchmarkReport:
        report_id = f"bench_{_new_id()}"
        bus = MessageBus()
        if self.event_store:
            bus.bind_event_store(self.event_store)

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

        pipeline = create_pipeline(config, self.llm_client, bus)

        total_threats_gt = 0
        outcomes: list[dict[str, Any]] = []
        categories: set[str] = set()
        expected_level_counts: dict[int, int] = {}

        for payload_text, is_threat_gt, expected_level, inj_type in BENCHMARK_PAYLOADS:
            if is_threat_gt:
                total_threats_gt += 1
            categories.add(inj_type)
            expected_level_counts[expected_level] = expected_level_counts.get(expected_level, 0) + 1

            event = AgentEvent(
                event_type=EventType.INPUT,
                source_node="Benchmark",
                target_node="Pipeline",
                payload_snippet=payload_text,
                # Every sample receives the same observable severity. Ground truth
                # must never decide whether the L3 detector is allowed to run.
                severity=EventSeverity.WARNING,
            )

            t0 = perf_counter()
            result = await pipeline.inspect(event)
            elapsed = (perf_counter() - t0) * 1000

            if result is None:
                detected_level = 3  # ISOLATE drops the event
                action = "isolate"
            else:
                detected_level = result.monitor_level.value
                action = result.action_taken.value
            detected = action != "none"
            if detected and detected_level == 0:
                detected_level = 1
            outcomes.append({
                "is_threat": is_threat_gt,
                "detected": detected,
                "detected_level": detected_level,
                "elapsed": elapsed,
                "expected_level": expected_level,
                "category": inj_type,
            })

        def _calc_stats(level: int) -> LevelStats:
            tp = fp = tn = fn = 0
            for outcome in outcomes:
                detected_by_level = (
                    outcome["detected"] and outcome["detected_level"] <= level
                )
                if outcome["is_threat"]:
                    tp += int(detected_by_level)
                    fn += int(not detected_by_level)
                else:
                    fp += int(detected_by_level)
                    tn += int(not detected_by_level)

            lats = [
                item["elapsed"]
                for item in outcomes
                if item["detected"] and item["detected_level"] == level
            ]
            lats_sorted = sorted(lats)
            return LevelStats(
                level=MonitorLevel(level),
                total_tested=len(outcomes),
                threats_detected=tp,
                false_positives=fp,
                true_negatives=tn,
                recall=round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0,
                fpr=round(fp / (fp + tn), 4) if (fp + tn) > 0 else 0.0,
                avg_latency_ms=round(sum(lats) / len(lats), 2) if lats else 0.0,
                p95_latency_ms=round(lats_sorted[int((len(lats_sorted) - 1) * 0.95)], 2) if lats_sorted else 0.0,
            )

        per_level = [_calc_stats(level) for level in (1, 2, 3)]
        all_tp = sum(1 for item in outcomes if item["is_threat"] and item["detected"])
        all_fp = sum(1 for item in outcomes if not item["is_threat"] and item["detected"])
        all_fn = sum(1 for item in outcomes if item["is_threat"] and not item["detected"])
        all_tn = sum(1 for item in outcomes if not item["is_threat"] and not item["detected"])

        return BenchmarkReport(
            report_id=report_id,
            timestamp=time(),
            pipeline_config={
                "detectors": ["regex", "semantic", "llm_intent"],
                "short_circuit": True,
                "dataset_id": DATASET_ID,
                "dataset_sha256": DATASET_SHA256,
                "categories": sorted(categories),
                "expected_level_counts": expected_level_counts,
            },
            total_payloads=len(BENCHMARK_PAYLOADS),
            ground_truth_threats=total_threats_gt,
            per_level=per_level,
            overall_recall=round(all_tp / (all_tp + all_fn), 4) if (all_tp + all_fn) > 0 else 1.0,
            overall_fpr=round(all_fp / (all_fp + all_tn), 4) if (all_fp + all_tn) > 0 else 0.0,
        )
