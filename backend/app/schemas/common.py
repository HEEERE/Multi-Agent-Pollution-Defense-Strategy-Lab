import uuid
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from time import time
from typing import Any

from pydantic import BaseModel, Field


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def new_trace_id() -> str:
    return f"trace_{new_id()}"


# ── Event enums ──────────────────────────────────────────────

class EventType(StrEnum):
    INPUT = "input"
    COMMUNICATION = "communication"
    TOOL_CALL = "tool_call"
    INTERVENTION = "intervention"
    CHALLENGE = "challenge"
    JOINT_DEFENSE_DECISION = "joint_defense_decision"
    RECOVERY = "recovery"


class EventStatus(StrEnum):
    SAFE = "safe"
    EXPOSED = "exposed"
    CHALLENGED = "challenged"
    HONEYPOTTED = "honeypotted"
    INFECTED = "infected"
    QUARANTINED = "quarantined"
    ISOLATED = "isolated"
    RECOVERED = "recovered"


class EventSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class MonitorLevel(IntEnum):
    NONE = 0
    HEURISTIC = 1
    FEATURE = 2
    LLM_INTENT = 3


class ActionTaken(StrEnum):
    NONE = "none"
    ALERT = "alert"
    BLOCK = "block"
    QUARANTINE = "quarantine"
    ISOLATE = "isolate"
    DECOY = "decoy"
    CHALLENGE = "challenge"
    RECOVER = "recover"


class ActionPolicy(StrEnum):
    ALERT = "alert"
    BLOCK = "block"
    QUARANTINE = "quarantine"
    ISOLATE = "isolate"
