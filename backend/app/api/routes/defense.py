from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.defense.manager import get_defense_coordinator, get_containment_registry

router = APIRouter(tags=["defense"])


@router.get("/memory")
async def get_threat_memory() -> dict:
    coordinator = get_defense_coordinator()
    return coordinator.threat_memory.snapshot()


@router.get("/decisions/latest")
async def get_latest_decisions(limit: int = 50) -> dict:
    coordinator = get_defense_coordinator()
    decisions = coordinator.threat_memory.snapshot()["recent_decisions"]
    return {"items": decisions[-limit:]}


@router.post("/containment/release/node/{node_id}")
async def release_node(node_id: str) -> dict:
    registry = get_containment_registry()
    registry.release_node(node_id)
    coordinator = get_defense_coordinator()
    coordinator.threat_memory.node_risk[node_id] = 0.2
    return {"node_id": node_id, "status": "release_requested"}


@router.post("/containment/release/tool/{tool_id}")
async def release_tool(tool_id: str) -> dict:
    registry = get_containment_registry()
    registry.release_tool(tool_id)
    return {"tool_id": tool_id, "status": "release_requested"}


@router.post("/containment/release/edge")
async def release_edge(source: str, target: str) -> dict:
    registry = get_containment_registry()
    registry.release_edge(source, target)
    return {"source": source, "target": target, "status": "release_requested"}


@router.post("/containment/release/memory/{memory_key}")
async def release_memory_key(memory_key: str) -> dict:
    registry = get_containment_registry()
    registry.release_memory_key(memory_key)
    return {"memory_key": memory_key, "status": "release_requested"}
