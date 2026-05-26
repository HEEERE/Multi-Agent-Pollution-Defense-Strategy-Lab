from app.schemas import (
    ActionTaken,
    AgentEvent,
    EventStatus,
    EventType,
    ExperimentMetrics,
)


class MetricsComputer:
    def __init__(self, events: list[AgentEvent], ground_truth: dict[str, bool] | None = None) -> None:
        self.events = sorted(events, key=lambda e: e.timestamp)
        self.ground_truth = ground_truth or {}

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
        infected_nodes: set[str] = set()
        for e in self.events:
            if e.status in (EventStatus.INFECTED, EventStatus.QUARANTINED):
                infected_nodes.add(e.target_node)
                infected_nodes.add(e.source_node)
        return len(infected_nodes)

    def _time_to_detection(self) -> float:
        first_inject = None
        first_detect = None
        for e in self.events:
            if e.event_type == EventType.INPUT and e.status != EventStatus.SAFE:
                if first_inject is None:
                    first_inject = e.timestamp
            if e.event_type == EventType.INTERVENTION:
                if first_detect is None:
                    first_detect = e.timestamp
        if first_inject is not None and first_detect is not None:
            return (first_detect - first_inject) * 1000
        return 0.0

    def _false_positive_rate(self) -> float:
        if not self.ground_truth:
            safe_events = [e for e in self.events if e.status == EventStatus.SAFE]
            flagged_safe = [e for e in safe_events if e.action_taken != ActionTaken.NONE]
            return len(flagged_safe) / len(safe_events) if safe_events else 0.0

        fp = 0
        total_safe = 0
        for e in self.events:
            is_threat = self.ground_truth.get(e.payload_snippet[:50], False)
            if not is_threat:
                total_safe += 1
                if e.action_taken != ActionTaken.NONE:
                    fp += 1
        return fp / total_safe if total_safe else 0.0

    def _intervention_effectiveness(self) -> float:
        threats = [e for e in self.events if e.status in (EventStatus.INFECTED, EventStatus.QUARANTINED)]
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
        infected_nodes: set[str] = set()
        turns = 0
        for e in self.events:
            if e.status in (EventStatus.INFECTED, EventStatus.QUARANTINED):
                if e.target_node not in infected_nodes:
                    infected_nodes.add(e.target_node)
                    turns += 1
        return len(infected_nodes) / max(turns, 1)

    def _threats_detected(self) -> int:
        return len([e for e in self.events if e.action_taken != ActionTaken.NONE])

    def _threats_blocked(self) -> int:
        return len([e for e in self.events if e.action_taken in (ActionTaken.BLOCK, ActionTaken.QUARANTINE)])

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
