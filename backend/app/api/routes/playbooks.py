"""Playbook endpoints."""

from fastapi import APIRouter, HTTPException

from app.playbooks import PLAYBOOKS, list_playbooks, run_playbook
from app.schemas import AgentEvent

router = APIRouter(tags=["playbooks"])


@router.get("")
async def get_playbooks() -> list[dict[str, str]]:
    return list_playbooks()


@router.post("/{playbook_id}/run", response_model=list[AgentEvent])
async def run_named_playbook(playbook_id: str, delay_seconds: float = 0.85) -> list[AgentEvent]:
    if playbook_id not in PLAYBOOKS:
        raise HTTPException(status_code=404, detail=f"Unknown playbook: {playbook_id}")
    return await run_playbook(playbook_id, delay_seconds)
