# TraceGraph & Contamination Analysis

## Design Motivation

In multi-agent systems, a single compromised agent can propagate contamination through message passing, tool calls, shared memory, and RAG retrieval. The TraceGraph module reconstructs event streams into a graph representation, enabling quantitative analysis of how contamination spreads, how quickly it is detected, and whether recovery succeeds.

## Node / Edge Schema

### TraceNode

| Field | Type | Description |
|-------|------|-------------|
| `node_id` | `str` | Unique node identifier (matches `AgentEvent.source_node` / `target_node`) |
| `node_type` | `str` | Role: `agent`, `tool`, `memory`, `rag_doc`, `user`, `monitor`, `gateway` |
| `label` | `str` | Human-readable label |
| `contamination_score` | `float` | 0.0 (clean) to 1.0 (fully compromised) |
| `trust_level` | `str` | `trusted`, `untrusted`, or `unknown` |
| `metadata` | `dict` | Extensible metadata |

### TraceEdge

| Field | Type | Description |
|-------|------|-------------|
| `edge_id` | `str` | Unique edge identifier |
| `trace_id` | `str` | Parent trace |
| `source` / `target` | `str` | Node IDs |
| `event_id` | `str` | Source `AgentEvent.event_id` |
| `edge_kind` | `str` | `message`, `tool_call`, `memory_write`, `memory_read`, `rag_retrieval`, `intervention` |
| `timestamp` | `float` | Epoch timestamp |
| `risk_tags` | `list[str]` | Associated risk labels |
| `contamination_delta` | `float` | Score change from source to target |

## Event to Graph Mapping

Events are transformed into graph elements based on their type and metadata:

| `event_type` | Default `edge_kind` | Override via `metadata` |
|-------------|---------------------|--------------------------|
| `input` | `message` | — |
| `communication` | `message` | — |
| `tool_call` | `tool_call` | `memory_op=write` → `memory_write`, `memory_op=read` → `memory_read`, `rag_op` → `rag_retrieval` |
| `intervention` | `intervention` | — |
| `challenge` | `message` | — |

## Contamination Score Calculation

Base score derived from `AgentEvent.status`:

| Status | Score |
|--------|-------|
| `safe` | 0.00 |
| `honeypotted` | 0.20 |
| `exposed` | 0.25 |
| `challenged` | 0.35 |
| `quarantined` | 0.65 |
| `infected` | 0.80 |
| `recovered` | 0.10 |

Risk tag bonuses (additive, clamped to 1.0):

| Tag | Bonus |
|-----|-------|
| `prompt_injection` | +0.20 |
| `rag_poisoning` | +0.20 |
| `memory_poisoning` | +0.25 |
| `tool_pollution` | +0.20 |
| `inter_agent_spoofing` | +0.20 |
| `cascading_failure` | +0.15 |

Node contamination = max of all incoming event scores.

## Contamination Metrics

| Metric | Definition |
|--------|-----------|
| `propagation_depth` | BFS depth from first contaminated node through edges |
| `blast_radius` | Number of nodes with contamination_score >= 0.5 |
| `contaminated_nodes` | List of node IDs at or above threshold |
| `time_to_detection_ms` | Time from first high-risk event to first intervention |
| `recovery_success` | No `infected` status at trace end, and `recovered` or `quarantined` present |
| `max_contamination_score` | Highest score across all nodes |
| `contamination_persistence` | Fraction of tail 30% events still at score >= 0.5 |

## API Examples

### Get TraceGraph

```bash
curl http://127.0.0.1:8000/api/v1/traces/trace_abc123/graph
```

Response:
```json
{
  "trace_id": "trace_abc123",
  "nodes": [
    {"node_id": "gateway", "node_type": "agent", "label": "gateway", "contamination_score": 0.0, "trust_level": "unknown", "metadata": {}},
    {"node_id": "agent_a", "node_type": "agent", "label": "agent_a", "contamination_score": 0.85, "trust_level": "unknown", "metadata": {}}
  ],
  "edges": [
    {"edge_id": "...", "trace_id": "trace_abc123", "source": "gateway", "target": "agent_a", "event_id": "evt_001", "edge_kind": "message", "timestamp": 1000.0, "risk_tags": ["prompt_injection"], "contamination_delta": 0.85, "metadata": {"event_type": "input", "status": "infected"}}
  ],
  "metrics": {"total_nodes": 2, "total_edges": 1, "total_events": 1}
}
```

### Get Contamination Metrics

```bash
curl http://127.0.0.1:8000/api/v1/traces/trace_abc123/contamination
```

Response:
```json
{
  "trace_id": "trace_abc123",
  "propagation_depth": 1,
  "blast_radius": 1,
  "contaminated_nodes": ["agent_a"],
  "first_contaminated_event_id": "evt_001",
  "time_to_detection_ms": null,
  "recovery_success": false,
  "max_contamination_score": 0.85,
  "contamination_persistence": 0.0
}
```
