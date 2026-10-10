from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TraceEvent(StrictModel):
    id: str
    parent_event_id: str | None = None
    timestamp: str
    actor: str
    type: str
    title: str
    description: str
    tool: str
    resource: str
    result: Literal["allowed", "blocked", "flagged"]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "parent_event_id")
    @classmethod
    def uuid_value(cls, value):
        if value is not None:
            UUID(value)
        return value

    @field_validator("timestamp")
    @classmethod
    def timestamp_value(cls, value):
        if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("Une date avec fuseau horaire est nécessaire.")
        return value


class RunRequest(StrictModel):
    question: str = Field(min_length=1, max_length=4000)
    agent_id: str = Field(default="dev-01", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    scenario: Literal["normal", "tool_poisoning"] = "normal"


class RAGChatRequest(StrictModel):
    question: str = Field(min_length=1, max_length=4000)
    agent_id: str = Field(default="dev-01", pattern=r"^[a-zA-Z0-9_-]{1,64}$")


class ConfinementRequest(StrictModel):
    incident_id: str = Field(min_length=1, max_length=120)
    action: str
    cible: str = Field(min_length=1, max_length=120)
    agent_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    approuve_par: str = Field(min_length=1, max_length=120)


class SearchArgs(StrictModel):
    query: str = Field(min_length=1, max_length=300)


class ReadArgs(StrictModel):
    path: Literal["README.md", ".env.demo", ".npmrc.demo"]


class PublishArgs(StrictModel):
    content: str = Field(min_length=1, max_length=8000)


class ReceiverPayload(StrictModel):
    run_id: UUID
    agent_id: str
    attempt_id: UUID
    content: str = Field(min_length=1, max_length=8000)
