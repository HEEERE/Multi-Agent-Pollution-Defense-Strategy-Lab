from time import time

from pydantic import BaseModel, Field

from app.schemas.common import new_id


class HoneyPotRecord(BaseModel):
    turn: int
    attacker_input: str
    agent_response: str
    tool_calls: list[str] = Field(default_factory=list)
    detected_technique: str = ""
    timestamp: float = Field(default_factory=time)


class ThreatIntelReport(BaseModel):
    report_id: str = Field(default_factory=new_id)
    honeypot_session_id: str = ""
    captured_at: float = Field(default_factory=time)
    attack_chain: list[HoneyPotRecord] = Field(default_factory=list)
    extracted_techniques: list[str] = Field(default_factory=list)
    novel_payloads: list[str] = Field(default_factory=list)
    total_turns: int = 0
    recommended_action: str = ""
