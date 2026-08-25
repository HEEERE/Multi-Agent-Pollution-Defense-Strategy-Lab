""""Experiment metrics computation with statistical significance.

MetricsComputer — single-run metrics from raw events.
AggregateMetrics — multi-run bootstrap confidence intervals and A/B comparison.
"""

import random
from statistics import mean, stdev

from app.schemas import (
    ActionTaken,
    AgentEvent,
    EventStatus,
    EventType,
    ExperimentMetrics,
)


class MetricsComputer:
    """Post-run metric computation.

    Runs strictly after a run has terminated, which is the only point at which
    ground-truth labels may be consulted. Labels arrive either as the legacy
    payload-keyed ``ground_truth`` map or, preferably, as an ``oracle`` keyed by
    event id (:class:`app.experiments.oracle.GroundTruthOracle`).
    """

    def __init__(
        self,
        events: list[AgentEvent],
        ground_truth: dict[str, bool] | None = None,
        oracle=None,
    ) -> None:
        self.events = sorted(events, key=lambda e: e.timestamp)
        self.ground_truth = ground_truth or {}
        self.oracle = oracle

    def compute(self) -> ExperimentMetrics:
        return ExperimentMetrics(
            propagation_depth=self._propagation_depth(),
            time_to_detection_ms=self._time_to_detection(),
            false_positive_rate=self._false_positive_rate(),
            intervention_effectiveness=self._intervention_effectiveness(),
            detection_latency_ms=self._detection_latency(),
            contamination_spread_rate=self._contamination_spread_rate(),
            total_events=len(self.events),
            threats_detected=self._threats_detected(),
            threats_blocked=self._threats_blocked(),
            cascade_depth=self._cascade_depth(),
        )

    def _propagation_depth(self) -> int:
        contaminated = {
            e.event_id
            for e in self.events
            if e.event_type != EventType.INTERVENTION
            and e.status in (
                EventStatus.EXPOSED,
                EventStatus.INFECTED,
                EventStatus.QUARANTINED,
                EventStatus.ISOLATED,
            )
        }
        parent_map = {e.event_id: e.parent_event_id for e in self.events}
        max_depth = 0
        for event_id in contaminated:
            depth = 0
            current = event_id
            visited: set[str] = set()
            while current not in visited:
                visited.add(current)
                parent = parent_map.get(current)
                if parent not in contaminated:
                    break
                depth += 1
                current = parent
            max_depth = max(max_depth, depth)
        return max_depth

    def _ground_truth_label(self, event: AgentEvent) -> bool | None:
        """Resolve the hidden label for one event.

        Order: the offline Oracle (keyed by event id) first, then the legacy
        payload-keyed map. Event metadata is deliberately *not* consulted -- a
        label carried in metadata is visible to online detectors, and one of them
        was in fact calibrating itself on it.
        """
        if self.oracle is not None:
            label = self.oracle.label_for(event.event_id)
            if label is not None:
                return label
        key = event.payload_snippet[:50]
        if key in self.ground_truth:
            return self.ground_truth[key]
        return None

    def _time_to_detection(self) -> float:
        first_inject = None
        first_detect = None
        for e in self.events:
            is_injection = (
                e.event_type == EventType.INPUT
                and (
                    self._ground_truth_label(e) is True
                    or e.status != EventStatus.SAFE
                )
            )
            if is_injection:
                if first_inject is None:
                    first_inject = e.timestamp
            if e.event_type == EventType.INTERVENTION:
                if first_detect is None:
                    first_detect = e.timestamp
        if first_inject is not None and first_detect is not None:
            return (first_detect - first_inject) * 1000
        return 0.0

    def _false_positive_rate(self) -> float:
        safe_events = [
            e
            for e in self.events
            if e.event_type != EventType.INTERVENTION
            and self._ground_truth_label(e) is False
        ]
        total_safe = len(safe_events)
        fp = sum(e.action_taken != ActionTaken.NONE for e in safe_events)
        return fp / total_safe if total_safe else 0.0

    def _intervention_effectiveness(self) -> float:
        labeled_threats = [
            e for e in self.events if self._ground_truth_label(e) is True
        ]
        threats = labeled_threats or [
            e for e in self.events
            if e.event_type != EventType.INTERVENTION
            and e.status in (EventStatus.INFECTED, EventStatus.QUARANTINED)
        ]
        if not threats:
            return 1.0
        blocked = [e for e in threats if e.action_taken in (ActionTaken.BLOCK, ActionTaken.QUARANTINE)]
        return len(blocked) / len(threats)

    def _detection_latency(self) -> float:
        latencies: list[float] = []
        for e in self.events:
            if "detection" in e.metadata:
                det = e.metadata["detection"]
                if "latency_ms" in det:
                    latencies.append(det["latency_ms"])
        return sum(latencies) / len(latencies) if latencies else 0.0

    def _contamination_spread_rate(self) -> float:
        all_nodes: set[str] = set()
        contaminated_nodes: set[str] = set()
        for e in self.events:
            if e.event_type == EventType.INTERVENTION:
                continue
            all_nodes.update((e.source_node, e.target_node))
            if e.status in (
                EventStatus.EXPOSED,
                EventStatus.INFECTED,
                EventStatus.QUARANTINED,
                EventStatus.ISOLATED,
            ):
                contaminated_nodes.update((e.source_node, e.target_node))
        return len(contaminated_nodes) / len(all_nodes) if all_nodes else 0.0

    def _threats_detected(self) -> int:
        return len([
            e for e in self.events
            if e.event_type != EventType.INTERVENTION
            and e.action_taken != ActionTaken.NONE
        ])

    def _threats_blocked(self) -> int:
        return len([
            e for e in self.events
            if e.event_type != EventType.INTERVENTION
            and e.action_taken in (ActionTaken.BLOCK, ActionTaken.QUARANTINE)
        ])

    def _cascade_depth(self) -> int:
        parent_map: dict[str, str | None] = {}
        for e in self.events:
            parent_map[e.event_id] = e.parent_event_id

        max_depth = 0
        for event_id in parent_map:
            depth = 0
            current = event_id
            while current in parent_map and parent_map[current] is not None:
                depth += 1
                current = parent_map[current]
                if depth > 100:
                    break
            max_depth = max(max_depth, depth)
        return max_depth


class AggregateMetrics:
    """Multi-run statistical analysis with bootstrap confidence intervals.

    Takes multiple ExperimentMetrics objects from repeated runs of the same
    experiment configuration and computes means, standard deviations, and
    95% confidence intervals via bootstrap resampling.
    """

    N_BOOTSTRAP = 2000

    def __init__(self, metrics_list: list[dict], seed: int = 0) -> None:
        self.metrics_list = metrics_list
        self._random = random.Random(seed)
        self._field_names = [
            name for name, model_field in ExperimentMetrics.model_fields.items()
            if name != "metadata" and model_field.annotation in {int, float}
        ]

    def compute(self) -> dict:
        """Return aggregated stats with CIs for each metric field."""
        result: dict = {
            "n_runs": len(self.metrics_list),
            "fields": {},
        }

        for field in self._field_names:
            values = [m.get(field, 0.0) for m in self.metrics_list if field in m]
            if len(values) < 2:
                result["fields"][field] = {
                    "mean": values[0] if values else 0,
                    "std": 0,
                    "ci_95_lower": values[0] if values else 0,
                    "ci_95_upper": values[0] if values else 0,
                    "n": len(values),
                }
                continue

            mu = mean(values)
            sd = stdev(values) if len(values) >= 2 else 0.0
            ci_low, ci_high = self._bootstrap_ci(values)

            result["fields"][field] = {
                "mean": round(mu, 4),
                "std": round(sd, 4),
                "ci_95_lower": round(ci_low, 4),
                "ci_95_upper": round(ci_high, 4),
                "n": len(values),
            }

        return result

    def _bootstrap_ci(self, values: list[float]) -> tuple[float, float]:
        """Percentile bootstrap 95% CI."""
        n = len(values)
        means: list[float] = []
        for _ in range(self.N_BOOTSTRAP):
            sample = [self._random.choice(values) for _ in range(n)]
            means.append(mean(sample))
        means.sort()
        lo_idx = int(self.N_BOOTSTRAP * 0.025)
        hi_idx = int(self.N_BOOTSTRAP * 0.975)
        return means[lo_idx], means[hi_idx]

    @staticmethod
    def compare(baseline: dict, treatment: dict) -> dict:
        """Compute p-value and effect size between two metric sets."""
        comparisons: dict = {}
        fields = set(baseline.get("fields", {}).keys()) & set(treatment.get("fields", {}).keys())
        for field in fields:
            b = baseline["fields"][field]
            t = treatment["fields"][field]
            diff = t["mean"] - b["mean"]
            pooled_sd = ((b["std"] ** 2 + t["std"] ** 2) / 2) ** 0.5 if (b["std"] + t["std"]) > 0 else 0.001
            cohens_d = diff / pooled_sd if pooled_sd else 0.0
            overlaps = (t["ci_95_lower"] <= b["ci_95_upper"]) and (b["ci_95_lower"] <= t["ci_95_upper"])
            comparisons[field] = {
                "baseline_mean": b["mean"],
                "treatment_mean": t["mean"],
                "delta": round(diff, 4),
                "cohens_d": round(cohens_d, 3),
                "significant": not overlaps,
            }
        return comparisons
