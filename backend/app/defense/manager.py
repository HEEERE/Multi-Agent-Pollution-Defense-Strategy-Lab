from __future__ import annotations

from app.defense.consensus import DEFENDER_WEIGHTS
from app.defense.containment import ContainmentPlanner, ContainmentRegistry
from app.defense.coordinator import DefenseCoordinator
from app.defense.guards.honeypot_guard import HoneypotGuardAgent
from app.defense.guards.memory_guard import MemoryGuardAgent
from app.defense.guards.policy_guard import PolicyGuardAgent
from app.defense.guards.prompt_guard import PromptGuardAgent
from app.defense.guards.propagation_guard import PropagationGuardAgent
from app.defense.guards.rag_guard import RAGGuardAgent
from app.defense.guards.recovery_agent import RecoveryAgent
from app.defense.guards.tool_guard import ToolGuardAgent
from app.defense.threat_memory import ThreatMemory
from app.policy.engine import PolicyEngine

_threat_memory: ThreatMemory | None = None
_containment_registry: ContainmentRegistry | None = None
_defense_coordinator: DefenseCoordinator | None = None


def get_threat_memory() -> ThreatMemory:
    global _threat_memory
    if _threat_memory is None:
        _threat_memory = ThreatMemory()
    return _threat_memory


def get_containment_registry() -> ContainmentRegistry:
    global _containment_registry
    if _containment_registry is None:
        _containment_registry = ContainmentRegistry()
    return _containment_registry


def create_defense_coordinator(bus=None, event_store=None) -> DefenseCoordinator:
    threat_memory = ThreatMemory()
    containment_registry = ContainmentRegistry()
    defenders = [
        PromptGuardAgent(weight=DEFENDER_WEIGHTS.get("prompt_guard", 1.2)),
        RAGGuardAgent(weight=DEFENDER_WEIGHTS.get("rag_guard", 1.1)),
        ToolGuardAgent(weight=DEFENDER_WEIGHTS.get("tool_guard", 1.3)),
        MemoryGuardAgent(weight=DEFENDER_WEIGHTS.get("memory_guard", 1.2)),
        PolicyGuardAgent(
            policy_engine=PolicyEngine(),
            weight=DEFENDER_WEIGHTS.get("policy_guard", 1.4),
        ),
        PropagationGuardAgent(
            weight=DEFENDER_WEIGHTS.get("propagation_guard", 1.5),
        ),
        HoneypotGuardAgent(
            weight=DEFENDER_WEIGHTS.get("honeypot_guard", 0.8),
        ),
    ]
    return DefenseCoordinator(
        defenders=defenders,
        bus=bus,
        event_store=event_store,
        threat_memory=threat_memory,
        containment_planner=ContainmentPlanner(threat_memory=threat_memory),
        containment_registry=containment_registry,
        recovery_agent=RecoveryAgent(threat_memory=threat_memory),
    )


def get_defense_coordinator(bus=None, event_store=None) -> DefenseCoordinator:
    global _defense_coordinator
    if _defense_coordinator is None:
        _defense_coordinator = create_defense_coordinator(bus, event_store)
    else:
        if bus is not None:
            _defense_coordinator.bus = bus
        if event_store is not None:
            _defense_coordinator.event_store = event_store
    return _defense_coordinator
