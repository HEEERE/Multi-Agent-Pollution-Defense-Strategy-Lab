from app.trace_graph.models import TraceGraph


class ContaminationMetrics:
    def __init__(
        self,
        trace_id: str = "",
        propagation_depth: int = 0,
        blast_radius: int = 0,
        contaminated_nodes: list[str] | None = None,
        first_contaminated_event_id: str | None = None,
        first_detection_event_id: str | None = None,
        time_to_detection_ms: float | None = None,
        recovery_success: bool = False,
        max_contamination_score: float = 0.0,
        contamination_persistence: float = 0.0,
    ):
        self.trace_id = trace_id
        self.propagation_depth = propagation_depth
        self.blast_radius = blast_radius
        self.contaminated_nodes = contaminated_nodes or []
        self.first_contaminated_event_id = first_contaminated_event_id
        self.first_detection_event_id = first_detection_event_id
        self.time_to_detection_ms = time_to_detection_ms
        self.recovery_success = recovery_success
        self.max_contamination_score = max_contamination_score
        self.contamination_persistence = contamination_persistence

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "propagation_depth": self.propagation_depth,
            "blast_radius": self.blast_radius,
            "contaminated_nodes": self.contaminated_nodes,
            "first_contaminated_event_id": self.first_contaminated_event_id,
            "first_detection_event_id": self.first_detection_event_id,
            "time_to_detection_ms": self.time_to_detection_ms,
            "recovery_success": self.recovery_success,
            "max_contamination_score": self.max_contamination_score,
            "contamination_persistence": self.contamination_persistence,
        }


class ContaminationAnalyzer:
    def analyze(self, graph: TraceGraph, events_sorted: list | None = None) -> ContaminationMetrics:
        nodes = graph.nodes
        edges = graph.edges

        if not nodes:
            return ContaminationMetrics(trace_id=graph.trace_id)

        max_score = max((n.contamination_score for n in nodes), default=0.0)

        contaminated = [n.node_id for n in nodes if n.contamination_score >= 0.5]

        # propagation_depth via BFS from first contaminated node
        depth = self._bfs_depth(nodes, edges, contaminated)

        # time_to_detection: find first high-contamination edge and first intervention
        ttd = self._compute_time_to_detection(edges)

        # recovery_success
        recovered = self._check_recovery(edges)

        # persistence: fraction of tail 30% edges with contamination
        persistence = self._compute_persistence(edges)

        first_contaminated = None
        for e in edges:
            if e.contamination_delta > 0:
                first_contaminated = e.event_id
                break

        first_detection = None
        for e in edges:
            if e.edge_kind == "intervention":
                first_detection = e.event_id
                break

        return ContaminationMetrics(
            trace_id=graph.trace_id,
            propagation_depth=depth,
            blast_radius=len(contaminated),
            contaminated_nodes=contaminated,
            first_contaminated_event_id=first_contaminated,
            first_detection_event_id=first_detection,
            time_to_detection_ms=ttd,
            recovery_success=recovered,
            max_contamination_score=round(max_score, 4),
            contamination_persistence=round(persistence, 4),
        )

    def _bfs_depth(self, nodes: list, edges: list, contaminated: list[str]) -> int:
        if not contaminated:
            return 0

        adj: dict[str, list[str]] = {}
        for e in edges:
            adj.setdefault(e.source, []).append(e.target)

        start = contaminated[0]
        visited: set[str] = set()
        queue = [(start, 0)]
        max_depth = 0

        while queue:
            node, depth = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            max_depth = max(max_depth, depth)
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    queue.append((neighbor, depth + 1))

        return max_depth

    def _compute_time_to_detection(self, edges: list) -> float | None:
        first_high_risk_ts = None
        first_intervention_ts = None

        for e in sorted(edges, key=lambda x: x.timestamp):
            if first_high_risk_ts is None and e.contamination_delta > 0:
                first_high_risk_ts = e.timestamp
            if first_intervention_ts is None and e.edge_kind == "intervention":
                first_intervention_ts = e.timestamp

        if first_high_risk_ts and first_intervention_ts:
            return round((first_intervention_ts - first_high_risk_ts) * 1000, 2)
        return None

    def _check_recovery(self, edges: list) -> bool:
        if not edges:
            return False
        sorted_edges = sorted(edges, key=lambda x: x.timestamp)

        has_infected = any(
            e.metadata.get("status") == "infected" for e in sorted_edges
        )

        tail_count = max(1, len(sorted_edges) * 3 // 10)
        tail = sorted_edges[-tail_count:]
        still_infected = any(
            e.metadata.get("status") == "infected" for e in tail
        )

        has_recovered = any(
            e.metadata.get("status") == "recovered" for e in sorted_edges
        )
        has_quarantined = any(
            e.metadata.get("status") == "quarantined" for e in sorted_edges
        )

        if has_infected and not still_infected and (has_recovered or has_quarantined):
            return True
        if not has_infected:
            return True
        return False

    def _compute_persistence(self, edges: list) -> float:
        if not edges:
            return 0.0
        sorted_edges = sorted(edges, key=lambda x: x.timestamp)
        tail_count = max(1, len(sorted_edges) * 3 // 10)
        tail = sorted_edges[-tail_count:]
        contaminated = sum(
            1 for e in tail if e.metadata.get("status") in ("infected", "quarantined")
            or e.contamination_delta >= 0.5
        )
        return contaminated / len(tail) if tail else 0.0
