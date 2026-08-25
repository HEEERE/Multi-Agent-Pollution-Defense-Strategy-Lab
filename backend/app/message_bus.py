from collections import deque
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from time import time

from app.schemas import ActionTaken, AgentEvent, EventSeverity, EventStatus
from app.provenance.models import ArtifactState

EventHandler = Callable[[AgentEvent], Awaitable[None]]
MonitorHook = Callable[[AgentEvent], Awaitable[AgentEvent | None]]
BroadcastHook = Callable[[AgentEvent], Awaitable[None]]


async def _noop_action():
    return None


def integrity_of(trust_level: str) -> str:
    """Map the event ``trust_level`` vocabulary onto the integrity vocabulary.

    Two different vocabularies meet here. Events carry
    ``trusted | untrusted | unknown``; the ledger and ``ActionArgument`` carry
    ``high | low | unknown``. Both the provenance write and the ActionRequest
    must use the same mapping, otherwise the policy compares an event-level
    word against an integrity-level word and the comparison silently never
    matches. Keep this the single definition.
    """
    if trust_level == "trusted":
        return "high"
    if trust_level == "untrusted":
        return "low"
    return "unknown"

# Actions and statuses that stop delivery. ALERT/CHALLENGE/DECOY are observation
# outcomes and stay deliverable; only these mean "contained".
_CONTAINED_ACTIONS = frozenset(
    {ActionTaken.BLOCK, ActionTaken.ISOLATE, ActionTaken.QUARANTINE}
)
_CONTAINED_STATUSES = frozenset({EventStatus.QUARANTINED, EventStatus.ISOLATED})

_current_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_pending_events: ContextVar[list[AgentEvent] | None] = ContextVar("pending_events", default=None)
_current_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)


def get_current_trace_id() -> str | None:
    return _current_trace_id.get()


def get_current_run_id() -> str | None:
    return _current_run_id.get()


def set_run_context(run_id: str | None) -> None:
    _current_run_id.set(run_id)


def clear_run_context() -> None:
    _current_run_id.set(None)


def set_trace_context(trace_id: str) -> None:
    _current_trace_id.set(trace_id)
    _pending_events.set([])


def clear_trace_context() -> list[AgentEvent]:
    events = _pending_events.get() or []
    _current_trace_id.set(None)
    _pending_events.set(None)
    return events


def collect_event(event: AgentEvent) -> None:
    pending = _pending_events.get()
    if pending is not None:
        pending.append(event)


class MessageBus:
    """Central async bus. Agents never call each other directly."""

    def __init__(self, max_history: int = 500) -> None:
        self._handlers: dict[str, EventHandler] = {}
        self._all_listeners: list[EventHandler] = []
        self._monitors: list[MonitorHook] = []
        self._broadcast_hooks: list[BroadcastHook] = []
        self.history: deque[AgentEvent] = deque(maxlen=max_history)
        self._event_store = None
        self._containment_registry = None
        self._allowed_edges: set[tuple[str, str]] | None = None
        self._topology_monitors: tuple[str, ...] = ()
        self._provenance_ledger = None
        self._provenance_run_id: str | None = None
        self._action_gateway = None
        self._effect_sandbox = None

    def bind_event_store(self, event_store) -> None:
        self._event_store = event_store

    def bind_containment_registry(self, registry) -> None:
        self._containment_registry = registry

    def bind_provenance_ledger(self, ledger, run_id: str | None = None) -> None:
        """Attach the v4 immutable provenance projection to this bus."""
        self._provenance_ledger = ledger
        self._provenance_run_id = run_id
        if run_id:
            ledger.ensure_run(run_id)

    def bind_action_gateway(self, gateway) -> None:
        self._action_gateway = gateway

    def bind_effect_sandbox(self, sandbox) -> None:
        self._effect_sandbox = sandbox

    @property
    def effect_sandbox(self):
        return self._effect_sandbox

    @property
    def action_gateway(self):
        return self._action_gateway

    @property
    def provenance_ledger(self):
        return self._provenance_ledger

    @property
    def provenance_run_id(self) -> str | None:
        return self._provenance_run_id

    def bind_topology(self, edges, monitors: list[str] | None = None) -> None:
        """Bind strategy routing constraints and passive monitor identities."""
        edge_set = {(edge.source, edge.target) for edge in edges}
        for edge in edges:
            if edge.edge_type == "bidirectional":
                edge_set.add((edge.target, edge.source))
        self._allowed_edges = edge_set or None
        self._topology_monitors = tuple(monitors or [])

    @property
    def event_store(self):
        return self._event_store

    def subscribe(self, node_id: str, handler: EventHandler) -> None:
        self._handlers[node_id] = handler

    def subscribe_all(self, handler: EventHandler) -> None:
        """Register a handler that receives ALL events regardless of target_node.
        Used by Auditor agents to monitor the entire bus for threat detection."""
        self._all_listeners.append(handler)

    def unsubscribe(self, node_id: str) -> None:
        self._handlers.pop(node_id, None)

    def attach_monitor(self, hook: MonitorHook) -> None:
        self._monitors.append(hook)

    def replace_monitors(self, monitors: list[MonitorHook]) -> None:
        self._monitors = list(monitors)

    def attach_broadcast_hook(self, hook: BroadcastHook) -> None:
        self._broadcast_hooks.append(hook)

    def remove_broadcast_hook(self, hook: BroadcastHook) -> None:
        try:
            self._broadcast_hooks.remove(hook)
        except ValueError:
            pass

    async def publish(self, event: AgentEvent) -> AgentEvent | None:
        trace_id = get_current_trace_id()
        if trace_id and event.trace_id != trace_id:
            event = event.model_copy(update={"trace_id": trace_id})

        run_id_from_ctx = get_current_run_id()
        if run_id_from_ctx:
            event = event.model_copy(
                update={
                    "metadata": {
                        **event.metadata,
                        "run_id": run_id_from_ctx,
                    }
                }
            )

        if self._topology_monitors:
            event = event.model_copy(
                update={
                    "metadata": {
                        **event.metadata,
                        "topology_monitors": list(self._topology_monitors),
                    }
                }
            )

        inspected_event: AgentEvent | None = event

        for monitor in self._monitors:
            if inspected_event is None:
                break
            inspected_event = await monitor(inspected_event)

        if inspected_event is None:
            return None

        # Optional v4 action boundary. Existing event producers remain
        # backwards-compatible, while tool/effect metadata opts into the
        # structured ActionRequest path before persistence or delivery.
        if self._action_gateway is not None:
            inspected_event = self._materialize_context_inputs(inspected_event)
            inspected_event = await self._authorize_event_action(inspected_event)

        if (
            self._allowed_edges is not None
            and (inspected_event.source_node, inspected_event.target_node)
            not in self._allowed_edges
        ):
            inspected_event = inspected_event.model_copy(
                update={
                    "status": EventStatus.QUARANTINED,
                    "action_taken": ActionTaken.BLOCK,
                    "severity": EventSeverity.CRITICAL,
                    "metadata": {
                        **inspected_event.metadata,
                        "topology_blocked": True,
                        "topology_reason": "edge is not declared by the strategy",
                    },
                }
            )

        # Containment check: intercept BEFORE store/broadcast so downstream
        # only sees the blocked version.
        if self._containment_registry is not None:
            blocked, reason = self._containment_registry.blocks_event(inspected_event)
            if blocked:
                inspected_event = inspected_event.model_copy(
                    update={
                        "status": EventStatus.QUARANTINED,
                        "action_taken": ActionTaken.BLOCK,
                        "severity": EventSeverity.CRITICAL,
                        "metadata": {
                            **inspected_event.metadata,
                            "containment_blocked": True,
                            "containment_reason": reason,
                        },
                    }
                )

        # F-C2: persist BEFORE recording in history or delivering. A store
        # failure must fail the publish loudly instead of leaving the in-memory
        # view and the ledger disagreeing while the run still looks healthy.
        if self._event_store is not None:
            await self._event_store.store_event(inspected_event)

        await self._record_provenance(inspected_event)

        # Per-run linking: if event carries a run_id, link it and
        # broadcast to the run-specific WebSocket room.
        run_id = (
            inspected_event.metadata.get("run_id")
            if inspected_event.metadata
            else None
        )
        if run_id and self._event_store is not None:
            await self._event_store.store_run_event(
                {
                    "run_id": run_id,
                    "event_id": inspected_event.event_id,
                    "trace_id": inspected_event.trace_id,
                    "event_json": inspected_event.model_dump_json(
                        exclude_none=True
                    ),
                    "created_at": time(),
                }
            )

        self.history.append(inspected_event)
        collect_event(inspected_event)

        # Broadcast hooks are transport-facing (the default hook is the global
        # WebSocket room), so they must receive the same label-aware projection
        # as per-run rooms. Internal handlers/listeners above still receive the
        # committed event for enforcement and auditing.
        public_event = self._project_event(inspected_event)
        await self._broadcast(public_event)

        if run_id:
            from app.websocket_manager import websocket_manager

            await websocket_manager.broadcast(
                public_event, room_id=str(run_id)
            )

        # F-C1: QUARANTINE is a containment action just like BLOCK and ISOLATE.
        # DefenseCoordinator emits it directly for the `quarantine` decision, so
        # it reaches this point without the containment branch above having
        # rewritten it to BLOCK. Status is checked too, because several paths set
        # status and action_taken independently.
        if inspected_event.action_taken in _CONTAINED_ACTIONS:
            return inspected_event
        if inspected_event.status in _CONTAINED_STATUSES:
            return inspected_event

        target_handler = self._handlers.get(inspected_event.target_node)
        if target_handler is not None:
            await target_handler(inspected_event)

        for listener in self._all_listeners:
            try:
                await listener(inspected_event)
            except Exception:
                pass

        return inspected_event

    def _project_event(self, event: AgentEvent) -> AgentEvent:
        """Public transport projection; payload bodies never bypass state labels."""
        ledger = self._provenance_ledger
        if ledger is None:
            return event
        refs = tuple(event.artifact_refs or (event.metadata or {}).get("artifact_refs", ()) or ())
        unavailable = False
        retained = False
        for ref in refs:
            artifact = ledger.get_artifact(ref)
            state = ledger.current_state(ref)
            # A missing reference is not evidence that the payload is safe.
            # For public transport it is treated as unavailable and redacted;
            # the policy path separately fail-closes E1-E3 on unknown refs.
            if artifact is None:
                unavailable = True
                continue
            if state in {ArtifactState.QUARANTINED, ArtifactState.INVALIDATED}:
                unavailable = True
            if state is ArtifactState.RETAINED:
                retained = True
        if not unavailable and not retained:
            return event
        metadata = {
            **event.metadata,
            "projection_filtered": True,
            "retained_label": retained,
            "confidentiality": "restricted" if retained else "unavailable",
        }
        return event.model_copy(update={
            "payload_snippet": "[REDACTED: unavailable provenance]" if unavailable else "[REDACTED: retained label required]",
            "metadata": metadata,
        })

    async def _authorize_event_action(self, event: AgentEvent) -> AgentEvent:
        from app.actions.models import ActionArgument, ActionRequest, EffectClass, SecurityDecision
        metadata = event.metadata or {}
        raw_effect = str(metadata.get("effect_class", "E0"))
        try:
            effect = EffectClass(raw_effect)
        except ValueError:
            effect = EffectClass.E1
        refs = self._visible_input_ids(event)
        operation = str(metadata.get("operation") or event.event_type.value)
        request = ActionRequest(
            action_id=event.event_id,
            run_id=str(metadata.get("run_id") or self._provenance_run_id or "default"),
            actor_agent_id=event.source_node,
            tool_id=event.target_node,
            operation=operation,
            arguments=(ActionArgument("payload", event.payload_snippet, refs, "content",
                                      integrity_of(event.trust_level)),),
            capability_requested=frozenset(metadata.get("capabilities", ()) or ()),
            resource_scope=str(metadata.get("resource_scope", "default")),
            effect_class=effect,
            reversible=bool(metadata.get("reversible", effect in {EffectClass.E0, EffectClass.E1, EffectClass.E2})),
            deadline=metadata.get("deadline"),
        )
        if not self._action_gateway.has_handler(event.target_node, operation):
            self._action_gateway.register(
                event.target_node, operation, lambda _request: _noop_action()
            )
        result = await self._action_gateway.submit(request)
        if result.decision is SecurityDecision.ALLOW:
            return event
        action = ActionTaken.QUARANTINE if result.decision in {SecurityDecision.QUARANTINE, SecurityDecision.UNKNOWN} else ActionTaken.BLOCK
        return event.model_copy(update={
            "status": EventStatus.QUARANTINED,
            "action_taken": action,
            "severity": EventSeverity.CRITICAL,
            "metadata": {
                **metadata,
                "gateway_denied": True,
                "gateway_reason": result.reason_code,
                "public_reason": result.public_reason or "denied: policy",
            },
        })

    @staticmethod
    def _visible_input_ids(event: AgentEvent) -> tuple[str, ...]:
        metadata = event.metadata or {}
        return tuple(dict.fromkeys(str(item) for item in (
            list(event.artifact_refs or metadata.get("artifact_refs", ()) or ())
            + ([metadata["system_prompt_id"]] if metadata.get("system_prompt_id") else [])
            + list(metadata.get("few_shot_ids", ()) or ())
            + list(metadata.get("tool_description_ids", ()) or ())
        )))

    def _materialize_context_inputs(self, event: AgentEvent) -> AgentEvent:
        """Commit declared prompts/examples/tool descriptions before authorization.

        Formal E1--E3 actions fail closed on an unknown reference.  Context that
        was actually visible to an agent therefore needs a real immutable
        artifact version, not merely a string in event metadata.
        """
        ledger = self._provenance_ledger
        if ledger is None:
            return event
        from app.provenance.models import ArtifactKind, ArtifactVersion
        import hashlib
        import json

        metadata = dict(event.metadata or {})
        run_id = str(metadata.get("run_id") or self._provenance_run_id or "default")
        ledger.ensure_run(run_id)

        def ensure(logical_id: str, value: object, kind: ArtifactKind, integrity: str) -> str:
            if ledger.get_artifact(logical_id) is not None:
                return logical_id
            material = json.dumps(
                [run_id, logical_id, value], ensure_ascii=False, sort_keys=True, default=str
            ).encode()
            version_id = f"ctx_{hashlib.sha256(material).hexdigest()[:24]}"
            if ledger.get_artifact(version_id) is None:
                ledger.append_artifact(ArtifactVersion(
                    version_id=version_id,
                    artifact_id=logical_id,
                    run_id=run_id,
                    kind=kind,
                    value_hash=hashlib.sha256(
                        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
                    ).hexdigest(),
                    origin_principals=frozenset({"platform_configuration"}),
                    integrity=integrity,
                    metadata={"context_input": True, "logical_id": logical_id},
                ))
            return version_id

        if metadata.get("system_prompt_id"):
            metadata["system_prompt_id"] = ensure(
                str(metadata["system_prompt_id"]), metadata.get("system_prompt", ""),
                ArtifactKind.MESSAGE, "high",
            )

        few_shot_ids = []
        few_shot_values = metadata.get("few_shot_values", {}) or {}
        for logical_id in metadata.get("few_shot_ids", ()) or ():
            few_shot_ids.append(ensure(
                str(logical_id), few_shot_values.get(str(logical_id), logical_id),
                ArtifactKind.MESSAGE, "high",
            ))
        metadata["few_shot_ids"] = few_shot_ids

        tool_description_ids = []
        tool_descriptions = metadata.get("tool_descriptions", {}) or {}
        description_integrity = str(metadata.get("tool_description_integrity", "high"))
        for logical_id in metadata.get("tool_description_ids", ()) or ():
            tool_description_ids.append(ensure(
                str(logical_id), tool_descriptions.get(str(logical_id), logical_id),
                ArtifactKind.TOOL_RESULT, description_integrity,
            ))
        metadata["tool_description_ids"] = tool_description_ids

        refs = tuple(dict.fromkeys(
            list(event.artifact_refs or metadata.get("artifact_refs", ()) or ())
            + ([f"event_{event.parent_event_id}"] if event.parent_event_id else [])
        ))
        return event.model_copy(update={"metadata": metadata, "artifact_refs": list(refs)})

    async def emit(self, event: AgentEvent) -> AgentEvent:
        trace_id = get_current_trace_id()
        if trace_id and event.trace_id != trace_id:
            event = event.model_copy(update={"trace_id": trace_id})

        run_id_from_ctx = get_current_run_id()
        if run_id_from_ctx:
            event = event.model_copy(
                update={
                    "metadata": {
                        **event.metadata,
                        "run_id": run_id_from_ctx,
                    }
                }
            )

        self.history.append(event)
        collect_event(event)

        if self._event_store is not None:
            await self._event_store.store_event(event)

        await self._record_provenance(event)

        run_id = (
            event.metadata.get("run_id") if event.metadata else None
        )
        if run_id and self._event_store is not None:
            await self._event_store.store_run_event(
                {
                    "run_id": run_id,
                    "event_id": event.event_id,
                    "trace_id": event.trace_id,
                    "event_json": event.model_dump_json(
                        exclude_none=True
                    ),
                    "created_at": time(),
                }
            )

        public_event = self._project_event(event)
        await self._broadcast(public_event)

        if run_id:
            from app.websocket_manager import websocket_manager

            await websocket_manager.broadcast(
                public_event, room_id=str(run_id)
            )

        return event

    async def _record_provenance(self, event: AgentEvent) -> None:
        ledger = self._provenance_ledger
        if ledger is None:
            return
        from app.provenance.models import ActivityRecord, ArtifactKind, ArtifactState, ArtifactVersion, Derivation, ProvenanceLevel, StateTransition
        import hashlib
        import json

        run_id = str(
            (event.metadata or {}).get("run_id")
            or self._provenance_run_id
            or "default"
        )
        ledger.ensure_run(run_id)
        kind_map = {
            "input": ArtifactKind.MESSAGE,
            "communication": ArtifactKind.MESSAGE,
            "tool_call": ArtifactKind.TOOL_RESULT,
        }
        kind = kind_map.get(event.event_type.value, ArtifactKind.MESSAGE)
        integrity = integrity_of(event.trust_level)
        metadata = event.metadata or {}
        visible_inputs = self._visible_input_ids(event)
        parent_versions = list(visible_inputs)
        if event.parent_event_id:
            parent_versions.append(f"event_{event.parent_event_id}")
        origins = {event.source_node}
        for parent_id in parent_versions:
            normalized_parent = parent_id if str(parent_id).startswith("event_") else f"event_{parent_id}"
            parent = ledger.get_artifact(normalized_parent) or ledger.get_artifact(str(parent_id))
            if parent is not None:
                origins.update(parent.origin_principals)

        artifact = ArtifactVersion(
            version_id=f"event_{event.event_id}", artifact_id=event.event_id, run_id=run_id,
            kind=kind, value_hash=hashlib.sha256(event.payload_snippet.encode()).hexdigest(),
            origin_principals=frozenset(origins), integrity=integrity,
            metadata={
                "event_id": event.event_id,
                "event_type": event.event_type.value,
                "visible_input_ids": list(dict.fromkeys(str(item) for item in (
                    list(event.artifact_refs or (event.metadata or {}).get("artifact_refs", ()) or ())
                    + ([(event.metadata or {})["system_prompt_id"]] if (event.metadata or {}).get("system_prompt_id") else [])
                    + list((event.metadata or {}).get("few_shot_ids", ()) or ())
                    + list((event.metadata or {}).get("tool_description_ids", ()) or ())
                ))),
                "system_prompt": (event.metadata or {}).get("system_prompt"),
                "few_shot_ids": list((event.metadata or {}).get("few_shot_ids", ())),
                "tool_description_ids": list((event.metadata or {}).get("tool_description_ids", ())),
            },
        )
        ledger.append_artifact(artifact)
        ledger.append_activity(ActivityRecord(
            activity_id=f"activity_{event.event_id}", run_id=run_id,
            actor_agent_id=event.source_node, kind=event.event_type.value,
            visible_input_ids=visible_inputs,
            tool_id=event.target_node if event.event_type.value == "tool_call" else None,
            operation=event.event_type.value,
            effect_class=str((event.metadata or {}).get("effect_class", "E0")),
        ))
        if event.parent_event_id:
            parent_id = f"event_{event.parent_event_id}"
            if ledger.get_artifact(parent_id) is not None:
                ledger.append_derivation(Derivation(
                    relation_id=f"event_rel_{event.event_id}", run_id=run_id,
                    child_version_id=artifact.version_id, parent_version_ids=(parent_id,),
                    activity_id=event.event_type.value, relation_type="derived_from",
                ))
        for index, parent_id in enumerate(visible_inputs):
            raw_id = str(parent_id)
            prefixed_id = raw_id if raw_id.startswith("event_") else f"event_{raw_id}"
            p1_id = raw_id if ledger.get_artifact(raw_id) is not None else prefixed_id
            if p1_id == artifact.version_id or ledger.get_artifact(p1_id) is None:
                continue
            ledger.append_derivation(Derivation(
                relation_id=f"event_p1_rel_{event.event_id}_{index}",
                run_id=run_id, child_version_id=artifact.version_id,
                parent_version_ids=(p1_id,), activity_id=f"activity_{event.event_id}",
                relation_type="conservative_influence",
                provenance_level=ProvenanceLevel.P1,
                effect_class=str((event.metadata or {}).get("effect_class", "E0")),
            ))
        if event.action_taken in {ActionTaken.BLOCK, ActionTaken.QUARANTINE, ActionTaken.ISOLATE}:
            target_state = ArtifactState.QUARANTINED if event.action_taken is ActionTaken.QUARANTINE else ArtifactState.INVALIDATED
            current = ledger.current_state(artifact.version_id) or ArtifactState.ACTIVE
            ledger.transition_state(StateTransition(
                transition_id=f"event_state_{event.event_id}", run_id=run_id,
                version_id=artifact.version_id, from_state=current, to_state=target_state,
                seq=0, reason=f"event_action:{event.action_taken.value}", action_id=event.event_id,
            ))

    async def _broadcast(self, event: AgentEvent) -> None:
        stale_hooks: list[BroadcastHook] = []

        for hook in self._broadcast_hooks:
            try:
                await hook(event)
            except RuntimeError:
                stale_hooks.append(hook)

        for hook in stale_hooks:
            self._broadcast_hooks.remove(hook)


message_bus = MessageBus()
