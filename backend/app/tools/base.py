from uuid import uuid4

from app.actions import ActionArgument, ActionGateway, ActionRequest, EffectClass, SecurityDecision
from app.message_bus import MessageBus
from app.schemas import ActionTaken, AgentEvent, EventStatus, EventType, new_trace_id


class BaseTool:
    def __init__(self, node_id: str, bus: MessageBus, gateway: ActionGateway | None = None, *, metadata: dict | None = None) -> None:
        self.node_id = node_id
        self.bus = bus
        self.gateway = gateway or bus.action_gateway
        self.metadata = dict(metadata or {})
        if self.gateway is not None:
            async def _authorize_return(_request):
                return None
            self.gateway.register(self.node_id, "return_result", _authorize_return)
        self.bus.subscribe(self.node_id, self.handle_event)

    async def handle_event(self, event: AgentEvent) -> None:
        if event.action_taken in (ActionTaken.BLOCK, ActionTaken.ISOLATE):
            return

        await self.return_result(
            target_node=event.source_node,
            payload=f"{self.node_id} processed: {event.payload_snippet}",
            status=event.status,
            trace_id=event.trace_id,
            parent_event_id=event.event_id,
            run_id=str((event.metadata or {}).get("run_id") or "runtime"),
            artifact_refs=list(dict.fromkeys(
                list(event.artifact_refs or (event.metadata or {}).get("artifact_refs", ()) or ())
                + [f"event_{event.event_id}"]
            )),
        )

    async def return_result(
        self,
        target_node: str,
        payload: str,
        status: EventStatus = EventStatus.SAFE,
        trace_id: str | None = None,
        parent_event_id: str | None = None,
        run_id: str = "runtime",
        artifact_refs: list[str] | None = None,
    ) -> AgentEvent | None:
        if self.gateway is not None:
            request = ActionRequest(
                action_id=f"act_{uuid4().hex[:16]}",
                run_id=run_id,
                actor_agent_id=self.node_id,
                tool_id=self.node_id,
                operation="return_result",
                arguments=(ActionArgument(
                    "payload", payload, tuple(artifact_refs or ()),
                    semantic_role="content", integrity="high",
                ),),
                effect_class=EffectClass.E0,
            )
            result = await self.gateway.submit(request)
            if result.decision is not SecurityDecision.ALLOW:
                return None
        return await self.bus.publish(
            AgentEvent(
                trace_id=trace_id or new_trace_id(),
                parent_event_id=parent_event_id,
                event_type=EventType.TOOL_CALL,
                source_node=self.node_id,
                target_node=target_node,
                payload_snippet=payload,
                status=status,
                action_taken=ActionTaken.NONE,
                artifact_refs=list(artifact_refs or ()),
                metadata={
                    "artifact_refs": list(artifact_refs or ()),
                    "effect_class": "E0",
                    "resource_scope": str(self.metadata.get("resource_scope", "default")),
                    "reversible": True,
                },
            )
        )
