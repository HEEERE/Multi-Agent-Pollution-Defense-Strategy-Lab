"""Trace business logic — trace CRUD, graph building, and contamination analysis."""

from fastapi import HTTPException

from app.event_store import get_event_store
from app.schemas import AgentEvent
from app.trace_graph.builder import TraceGraphBuilder
from app.trace_graph.analyzer import ContaminationAnalyzer


async def list_traces(limit: int = 50, offset: int = 0) -> list[dict]:
    store = await get_event_store()
    trace_ids = await store.get_trace_ids(limit=limit, offset=offset)
    summaries = []
    for tid in trace_ids:
        summary = await store.get_trace_summary(tid)
        if summary:
            summaries.append(summary.model_dump())
    return summaries


async def get_trace(trace_id: str) -> list[AgentEvent]:
    store = await get_event_store()
    return await store.get_events_by_trace(trace_id)


async def get_trace_summary(trace_id: str) -> dict:
    store = await get_event_store()
    summary = await store.get_trace_summary(trace_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return summary.model_dump()


async def delete_trace(trace_id: str) -> dict:
    store = await get_event_store()
    count = await store.delete_trace(trace_id)
    return {"deleted": count, "trace_id": trace_id}


async def get_trace_graph(trace_id: str) -> dict:
    store = await get_event_store()
    events = await store.get_events_by_trace(trace_id)
    if not events:
        raise HTTPException(status_code=404, detail="trace not found")
    builder = TraceGraphBuilder()
    graph = builder.build(events)
    return graph.model_dump(mode="json")


async def get_trace_contamination(trace_id: str) -> dict:
    store = await get_event_store()
    events = await store.get_events_by_trace(trace_id)
    if not events:
        raise HTTPException(status_code=404, detail="trace not found")
    builder = TraceGraphBuilder()
    graph = builder.build(events)
    analyzer = ContaminationAnalyzer()
    metrics = analyzer.analyze(graph, events)
    return metrics.to_dict()
