"""Benchmark system for reproducible safety testing."""

from time import perf_counter, time
from typing import Any

from app.benchmark.payloads import BENCHMARK_PAYLOADS
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

        level_data: dict[int, dict[str, Any]] = {
            1: {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "latencies": []},
            2: {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "latencies": []},
            3: {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "latencies": []},
        }

        total_threats_gt = 0

        for payload_text, is_threat_gt, expected_level, inj_type in BENCHMARK_PAYLOADS:
            if is_threat_gt:
                total_threats_gt += 1

            event = AgentEvent(
                event_type=EventType.INPUT,
                source_node="Benchmark",
                target_node="Pipeline",
                payload_snippet=payload_text,
                severity=EventSeverity.WARNING if is_threat_gt else EventSeverity.INFO,
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

            for lv in (1, 2, 3):
                if lv <= detected_level:
                    level_data[lv]["latencies"].append(elapsed)

            if is_threat_gt:
                if action != "none":
                    level_data[detected_level or 1]["tp"] += 1
                else:
                    for lv in (1, 2, 3):
                        level_data[lv]["fn"] += 1
            else:
                if action != "none":
                    level_data[detected_level or 1]["fp"] += 1
                else:
                    for lv in (1, 2, 3):
                        level_data[lv]["tn"] += 1

        def _calc_stats(ld: dict) -> LevelStats:
            tp, fp, tn, fn = ld["tp"], ld["fp"], ld["tn"], ld["fn"]
            total = tp + fp + tn + fn
            lats = ld["latencies"]
            lats_sorted = sorted(lats)
            return LevelStats(
                level=MonitorLevel.NONE,
                total_tested=total,
                threats_detected=tp,
                false_positives=fp,
                true_negatives=tn,
                recall=round(tp / (tp + fn), 4) if (tp + fn) > 0 else 1.0,
                fpr=round(fp / (fp + tn), 4) if (fp + tn) > 0 else 0.0,
                avg_latency_ms=round(sum(lats) / len(lats), 2) if lats else 0.0,
                p95_latency_ms=round(lats_sorted[int(len(lats_sorted) * 0.95)], 2) if lats_sorted else 0.0,
            )

        per_level: list[LevelStats] = []
        for lv in (1, 2, 3):
            stats = _calc_stats(level_data[lv])
            stats.level = MonitorLevel(lv)
            per_level.append(stats)

        # Overall recall/FPR
        all_tp = sum(d["tp"] for d in level_data.values())
        all_fp = sum(d["fp"] for d in level_data.values())
        all_fn = sum(d["fn"] for d in level_data.values())
        all_tn = sum(d["tn"] for d in level_data.values())

        return BenchmarkReport(
            report_id=report_id,
            timestamp=time(),
            pipeline_config={
                "detectors": ["regex", "semantic", "llm_intent"],
                "short_circuit": True,
            },
            total_payloads=len(BENCHMARK_PAYLOADS),
            ground_truth_threats=total_threats_gt,
            per_level=per_level,
            overall_recall=round(all_tp / (all_tp + all_fn), 4) if (all_tp + all_fn) > 0 else 1.0,
            overall_fpr=round(all_fp / (all_fp + all_tn), 4) if (all_fp + all_tn) > 0 else 0.0,
        )
