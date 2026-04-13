"""Pydantic schemas for triggers, trigger runs, agent traces."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

TriggerKind = Literal["gmail", "calendar", "file", "cron", "collab", "chat_command"]
TriggerRunStatus = Literal["running", "succeeded", "failed", "cancelled"]
AgentEventType = Literal[
    "thinking",
    "tool_call",
    "tool_result",
    "message",
    "decision",
    "error",
    "complete",
    "sub_agent_start",
]


class TriggerCreate(BaseModel):
    name: str
    description: Optional[str] = None
    kind: TriggerKind
    config: dict[str, Any] = Field(default_factory=dict)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    is_enabled: bool = True


class TriggerUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    actions: Optional[list[dict[str, Any]]] = None
    is_enabled: Optional[bool] = None


class TriggerResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    description: Optional[str] = None
    kind: TriggerKind
    config: dict[str, Any]
    actions: list[dict[str, Any]]
    is_enabled: bool
    last_fired_at: Optional[datetime] = None
    fire_count: int
    created_at: datetime
    updated_at: datetime


class TriggerRunResponse(BaseModel):
    id: UUID
    trigger_id: UUID
    user_id: UUID
    status: TriggerRunStatus
    payload: dict[str, Any]
    result: dict[str, Any]
    error: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None


class TriggerFireRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentTraceResponse(BaseModel):
    id: UUID
    user_id: UUID
    trigger_run_id: Optional[UUID] = None
    agent_name: str
    event_type: AgentEventType
    content: dict[str, Any]
    parent_trace_id: Optional[UUID] = None
    created_at: datetime
