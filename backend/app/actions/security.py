from __future__ import annotations

import re

from app.actions.models import ActionRequest, EvidenceRecord


class SecurityKernel:
    """Normalization and evidence collection; never grants authority."""

    @staticmethod
    def normalize(request: ActionRequest) -> ActionRequest:
        arguments = tuple(
            argument.__class__(
                argument.name,
                re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", argument.value)
                if isinstance(argument.value, str) else argument.value,
                argument.artifact_refs,
                argument.semantic_role,
                argument.integrity,
            )
            for argument in request.arguments
        )
        return request.__class__(
            request.action_id, request.run_id, request.actor_agent_id,
            request.tool_id, request.operation, arguments,
            request.capability_requested, request.resource_scope,
            request.effect_class, request.idempotency_key, request.reversible,
            request.deadline, request.scope_level, request.approval_id,
            request.model_evidence,
        )

    async def collect(self, request: ActionRequest) -> tuple[EvidenceRecord, ...]:
        return request.model_evidence
