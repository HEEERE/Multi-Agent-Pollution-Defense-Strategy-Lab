"""Demo task endpoints — trigger gateway→agent and agent→tool flows."""

from fastapi import APIRouter, Body

from app.demo_topology import run_gateway_to_agent, run_agent_to_tool
from app.schemas import AgentEvent

router = APIRouter(tags=["tasks"])


@router.post("/demo", response_model=AgentEvent | None)
async def submit_demo_task(
    payload: str = Body("Summarize the customer support context.", embed=True),
) -> AgentEvent | None:
    return await run_gateway_to_agent(payload)


@router.post("/tool-demo", response_model=AgentEvent | None)
async def submit_tool_demo(
    payload: str = Body("Search the shared incident notes.", embed=True),
) -> AgentEvent | None:
    return await run_agent_to_tool(payload)
