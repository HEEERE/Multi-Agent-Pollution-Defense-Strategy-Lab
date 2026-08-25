"""Trial-scoped side-effect sandbox for formal experiments.

No handler in this module touches the host filesystem, network, credentials, or
external services.  E1/E2 effects are reversible records in an isolated in-memory
store; E3 effects are irreversible *inside that store only*.  The gateway still
authorizes every operation and blocks E2/E3 entirely in ``dry_run`` mode.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from app.actions import (
    ActionContract,
    ArgumentContract,
    EffectClass,
)


@dataclass
class SandboxEffect:
    effect_id: str
    run_id: str
    action_id: str
    tool_id: str
    operation: str
    effect_class: str
    resource_scope: str
    payload: dict[str, Any]
    artifact_refs: tuple[str, ...]
    reversible: bool
    unsafe: bool
    created_at: float
    compensated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SideEffectSandbox:
    """One isolated effect world owned by exactly one :class:`RunContext`."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._effects: list[SandboxEffect] = []
        self._mutable_state: dict[str, list[str]] = {}
        self._commitments: set[str] = set()
        # Only the handler closure registered with ActionGateway holds this
        # token. Calling the sandbox executor directly is a protected-action
        # bypass and must fail before state changes.
        self.__gateway_token = object()

    @property
    def effects(self) -> tuple[SandboxEffect, ...]:
        return tuple(self._effects)

    @property
    def side_effect_count(self) -> int:
        return len(self._effects)

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "mutable_state": {key: list(value) for key, value in self._mutable_state.items()},
            "commitments": sorted(self._commitments),
            "effects": [effect.to_dict() for effect in self._effects],
        }

    def register_tool(
        self,
        gateway,
        *,
        tool_id: str,
        operation: str = "tool_call",
        effect_class: EffectClass | str = EffectClass.E1,
        resource_scopes: set[str] | frozenset[str] | None = None,
        required_capabilities: set[str] | frozenset[str] | None = None,
        reversible: bool | None = None,
        required_integrity: str | None = None,
    ) -> None:
        effect = EffectClass(effect_class)
        can_reverse = reversible if reversible is not None else effect is not EffectClass.E3
        integrity = required_integrity or ("high" if effect is EffectClass.E3 else "unknown")
        gateway.register_contract(ActionContract(
            tool_id=tool_id,
            operation=operation,
            effect_class=effect,
            arguments=(ArgumentContract(
                "payload", "content", required_integrity=integrity, required=True
            ),),
            required_capabilities=frozenset(required_capabilities or ()),
            allowed_resource_scopes=frozenset(resource_scopes or {"default"}),
            reversible=can_reverse,
        ))

        async def execute(request):
            return self._execute(request, gateway_token=self.__gateway_token)

        gateway.register(tool_id, operation, execute)

    def _execute(self, request, *, gateway_token=None) -> dict[str, Any]:
        if gateway_token is not self.__gateway_token:
            raise PermissionError("sandbox effects must execute through ActionGateway")
        if request.run_id != self.run_id:
            raise ValueError("sandbox run isolation violation")
        payload = {argument.name: argument.value for argument in request.arguments}
        unsafe = any(
            isinstance(value, dict) and bool(value.get("unsafe"))
            for value in payload.values()
        ) or bool(payload.get("unsafe"))
        effect = SandboxEffect(
            effect_id=f"sfx_{uuid4().hex[:16]}",
            run_id=request.run_id,
            action_id=request.action_id,
            tool_id=request.tool_id,
            operation=request.operation,
            effect_class=request.effect_class.value,
            resource_scope=request.resource_scope,
            payload=payload,
            artifact_refs=tuple(dict.fromkeys(
                ref for argument in request.arguments for ref in argument.artifact_refs
            )),
            reversible=request.reversible and request.effect_class is not EffectClass.E3,
            unsafe=unsafe,
            created_at=time.time(),
        )
        self._effects.append(effect)
        state_key = f"{request.tool_id}:{request.resource_scope}"
        if request.effect_class in {EffectClass.E1, EffectClass.E2}:
            self._mutable_state.setdefault(state_key, []).append(effect.effect_id)
        elif request.effect_class is EffectClass.E3:
            self._commitments.add(effect.effect_id)
        return {"effect_id": effect.effect_id, "sandboxed": True}

    def compensate(self, effect_id: str) -> bool:
        effect = next((item for item in self._effects if item.effect_id == effect_id), None)
        if effect is None or not effect.reversible or effect.compensated:
            return False
        effect.compensated = True
        for effect_ids in self._mutable_state.values():
            if effect_id in effect_ids:
                effect_ids.remove(effect_id)
        return True

    def reset(self) -> None:
        self._effects.clear()
        self._mutable_state.clear()
        self._commitments.clear()
