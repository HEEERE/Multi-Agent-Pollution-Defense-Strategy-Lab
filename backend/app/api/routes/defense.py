from __future__ import annotations

from fastapi import APIRouter

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


# ── Containment management ────────────────────────────────────────

@router.get("/containment/status")
async def get_containment_status() -> dict:
    registry = get_containment_registry()
    return {
        "quarantined_nodes": sorted(registry.quarantined_nodes),
        "isolated_tools": sorted(registry.isolated_tools),
        "blocked_edges": sorted(f"{s}->{t}" for s, t in registry.blocked_edges),
        "revoked_memory_keys": sorted(registry.revoked_memory_keys),
    }


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


# ── Recovery ───────────────────────────────────────────────────────

@router.post("/recovery/check/{node_id}")
async def check_recovery(node_id: str) -> dict:
    coordinator = get_defense_coordinator()
    if coordinator.recovery_agent is None:
        return {"node_id": node_id, "can_recover": False, "reason": "recovery agent not configured"}
    can_recover, reason = coordinator.recovery_agent.can_recover(node_id)
    return {"node_id": node_id, "can_recover": can_recover, "reason": reason}


@router.post("/recovery/approve/{node_id}")
async def approve_recovery(node_id: str) -> dict:
    coordinator = get_defense_coordinator()
    if coordinator.recovery_agent is None:
        return {"node_id": node_id, "status": "error", "reason": "recovery agent not configured"}

    can_recover, reason = coordinator.recovery_agent.can_recover(node_id)
    if not can_recover:
        return {"node_id": node_id, "status": "denied", "reason": reason}

    recovery_event = coordinator.recovery_agent.build_recovery_event(node_id)
    if recovery_event is None:
        return {"node_id": node_id, "status": "denied", "reason": "recovery check failed"}

    # Emit recovery event and release containment
    if coordinator.bus is not None:
        await coordinator.bus.emit(recovery_event)

    registry = get_containment_registry()
    registry.release_node(node_id)
    coordinator.threat_memory.node_risk[node_id] = 0.1

    return {"node_id": node_id, "status": "recovered", "reason": reason}
