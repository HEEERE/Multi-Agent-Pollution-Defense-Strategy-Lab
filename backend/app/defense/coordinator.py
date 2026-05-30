from __future__ import annotations

import asyncio

from app.defense.base import DefenseContext
from app.defense.consensus import aggregate_votes
from app.defense.containment import ContainmentPlanner
from app.defense.schemas import DefenderVerdict, JointDefenseDecision
from app.defense.threat_memory import ThreatMemory
from app.schemas import (
    ActionTaken,
    AgentEvent,
    EventSeverity,
    EventStatus,
    EventType,
    MonitorLevel,
    new_id,
)


class DefenseCoordinator:
    def __init__(
        self,
        defenders: list,
        bus=None,
        event_store=None,
        threat_memory: ThreatMemory | None = None,
        containment_planner: ContainmentPlanner | None = None,
        containment_registry=None,
        recovery_agent=None,
    ) -> None:
        self.defenders = defenders
        self.bus = bus
        self.event_store = event_store
        self.threat_memory = threat_memory or ThreatMemory()
        self.containment_planner = containment_planner or ContainmentPlanner(
            threat_memory=self.threat_memory
        )
        self.containment_registry = containment_registry
        self.recovery_agent = recovery_agent

    async def evaluate(self, event: AgentEvent) -> JointDefenseDecision:
        context = await self._build_context(event)

        raw_votes = await asyncio.gather(
            *(d.evaluate(event, context) for d in self.defenders),
            return_exceptions=True,
        )

        votes: list[DefenderVerdict] = []
        for defender, result in zip(self.defenders, raw_votes):
            if isinstance(result, Exception):
                votes.append(self._fallback_vote(defender.defender_id, str(result)))
            else:
                votes.append(result)

        final_action, confidence, consensus_type = aggregate_votes(votes)

        containment_plan = None
        if final_action in {"quarantine", "block", "isolate", "decoy"}:
            containment_plan = self.containment_planner.plan(
                event=event,
                votes=votes,
                final_action=final_action,
                context=context,
            )

        decision = JointDefenseDecision(
            decision_id=f"jdd_{new_id()}",
            source_event_id=event.event_id,
            trace_id=event.trace_id,
            final_action=final_action,
            confidence=confidence,
            votes=votes,
            consensus_type=consensus_type,
            containment_plan=containment_plan,
            rationale=self._build_rationale(votes, final_action, consensus_type),
        )

        self.threat_memory.record_decision(event, decision)

        if decision.containment_plan is not None and self.containment_registry is not None:
            self.containment_registry.apply_plan(decision.containment_plan)

            # Schedule recovery checks for quarantined nodes
            if (
                decision.containment_plan.recovery_required
                and self.recovery_agent is not None
                and self.bus is not None
            ):
                await self._check_recovery(decision.containment_plan, event.trace_id)

        if self.bus is not None:
            await self._emit_joint_decision(decision)

        return decision

    async def _build_context(self, event: AgentEvent) -> DefenseContext:
        trace_events: list[AgentEvent] = []
        trace_graph = None

        if self.event_store is not None and event.trace_id:
            try:
                trace_events = await self.event_store.get_events_by_trace(
                    event.trace_id
                )
                from app.trace_graph.builder import TraceGraphBuilder

                trace_graph = TraceGraphBuilder().build(trace_events).model_dump(
                    mode="json"
                )
            except Exception:
                trace_events = []
                trace_graph = None

        return DefenseContext(
            detection_log=event.metadata.get("detection_log", []),
            policy_decision=event.metadata.get("policy"),
            threat_memory=self.threat_memory.snapshot(),
            trace_events=trace_events,
            trace_graph=trace_graph,
            metadata=event.metadata,
        )

    def apply_decision(
        self,
        event: AgentEvent,
        decision: JointDefenseDecision,
    ) -> AgentEvent:
        action = decision.final_action
        status = event.status
        action_taken = event.action_taken
        severity = event.severity
        trust_level = event.trust_level
        contamination_score = event.contamination_score

        if action == "allow":
            pass
        elif action == "alert":
            status = EventStatus.CHALLENGED
            action_taken = ActionTaken.ALERT
            severity = EventSeverity.WARNING
            contamination_score = max(contamination_score, 0.35)
        elif action == "challenge":
            status = EventStatus.CHALLENGED
            action_taken = ActionTaken.CHALLENGE
            severity = EventSeverity.WARNING
            contamination_score = max(contamination_score, 0.35)
        elif action == "quarantine":
            status = EventStatus.QUARANTINED
            action_taken = ActionTaken.QUARANTINE
            severity = EventSeverity.CRITICAL
            trust_level = "untrusted"
            contamination_score = max(contamination_score, 0.65)
        elif action == "block":
            status = EventStatus.QUARANTINED
            action_taken = ActionTaken.BLOCK
            severity = EventSeverity.CRITICAL
            trust_level = "untrusted"
            contamination_score = max(contamination_score, 0.75)
        elif action == "isolate":
            status = EventStatus.ISOLATED
            action_taken = ActionTaken.ISOLATE
            severity = EventSeverity.CRITICAL
            trust_level = "untrusted"
            contamination_score = max(contamination_score, 0.9)
        elif action == "decoy":
            status = EventStatus.HONEYPOTTED
            action_taken = ActionTaken.DECOY
            severity = EventSeverity.WARNING
            contamination_score = max(contamination_score, 0.2)
        elif action == "recover":
            status = EventStatus.RECOVERED
            action_taken = ActionTaken.RECOVER
            severity = EventSeverity.INFO

        return event.model_copy(
            update={
                "status": status,
                "action_taken": action_taken,
                "severity": severity,
                "trust_level": trust_level,
                "contamination_score": contamination_score,
                "monitor_level": MonitorLevel.LLM_INTENT,
                "metadata": {
                    **event.metadata,
                    "joint_defense": decision.model_dump(mode="json"),
                    "containment_plan": (
                        decision.containment_plan.model_dump(mode="json")
                        if decision.containment_plan
                        else None
                    ),
                },
            }
        )

    async def _emit_joint_decision(self, decision: JointDefenseDecision) -> None:
        if self.bus is None:
            return
        event = AgentEvent(
            trace_id=decision.trace_id,
            parent_event_id=decision.source_event_id,
            event_type=EventType.JOINT_DEFENSE_DECISION,
            source_node="DefenseCoordinator",
            target_node="Dashboard",
            payload_snippet=decision.rationale[:500],
            status=EventStatus.SAFE,
            action_taken=ActionTaken.ALERT if decision.final_action != "allow" else ActionTaken.NONE,
            severity=EventSeverity.WARNING if decision.final_action != "allow" else EventSeverity.INFO,
            monitor_level=MonitorLevel.LLM_INTENT,
            metadata={
                "source_event_id": decision.source_event_id,
                "joint_defense": decision.model_dump(mode="json"),
            },
        )
        await self.bus.emit(event)

    async def _check_recovery(
        self, plan, trace_id: str
    ) -> None:
        for node_id in plan.quarantine_nodes:
            recovery_event = self.recovery_agent.build_recovery_event(
                node_id, trace_id
            )
            if recovery_event is not None:
                await self.bus.emit(recovery_event)

    @staticmethod
    def _fallback_vote(defender_id: str, error: str) -> DefenderVerdict:
        return DefenderVerdict(
            defender_id=defender_id,
            role="unknown",
            verdict="unknown",
            confidence=0.0,
            evidence=[f"error: {error}"],
            recommended_action="allow",
            weight=0.0,
        )

    @staticmethod
    def _build_rationale(
        votes: list[DefenderVerdict],
        final_action: str,
        consensus_type: str,
    ) -> str:
        malicious = [v for v in votes if v.verdict == "malicious"]
        suspicious = [v for v in votes if v.verdict == "suspicious"]
        parts = [
            f"{consensus_type} consensus selected {final_action}",
            f"({len(malicious)} malicious, {len(suspicious)} suspicious out of {len(votes)} defenders)",
        ]
        return "; ".join(parts)
