"""ダン用Notion: Pydantic スキーマ"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================================
# Block
# ============================================================

BLOCK_TYPES = {
    "page", "paragraph", "heading", "bullet_list", "numbered_list",
    "checklist", "task", "quote", "code", "divider", "callout",
    "image", "video", "audio", "pdf", "file", "embed",
    "email", "calendar_event", "table", "database", "bookmark",
    "invoice", "meeting_note", "proposal_ref",
}


class BlockCreate(BaseModel):
    type: str = Field(..., description="blocks.type のいずれか")
    parent_id: Optional[UUID] = None
    properties: dict[str, Any] = Field(default_factory=dict)
    content: Any = Field(default_factory=list)
    icon: Optional[str] = None
    cover_url: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    after_block_id: Optional[UUID] = Field(
        None, description="この block の直後に挿入。None なら parent 末尾"
    )
    source: str = "manual"
    source_id: Optional[str] = None


class BlockUpdate(BaseModel):
    properties: Optional[dict[str, Any]] = None
    content: Optional[Any] = None
    icon: Optional[str] = None
    cover_url: Optional[str] = None
    is_starred: Optional[bool] = None
    tags: Optional[list[str]] = None


class BlockMove(BaseModel):
    parent_id: Optional[UUID] = None
    after_block_id: Optional[UUID] = None
    before_block_id: Optional[UUID] = None


class BlockResponse(BaseModel):
    id: UUID
    user_id: UUID
    parent_id: Optional[UUID] = None
    type: str
    order_key: str
    properties: dict[str, Any]
    content: Any
    icon: Optional[str] = None
    cover_url: Optional[str] = None
    is_starred: bool
    tags: list[str]
    created_by: str
    source: str
    source_id: Optional[str] = None
    version: int
    created_at: datetime
    updated_at: datetime


# ============================================================
# Versions
# ============================================================

class BlockVersionResponse(BaseModel):
    id: UUID
    block_id: UUID
    version: int
    content: Any
    properties: dict[str, Any]
    changed_by: str
    change_summary: Optional[str] = None
    created_at: datetime


# ============================================================
# Triggers (Phase 3 で利用)
# ============================================================

class TriggerCreate(BaseModel):
    name: str
    description: Optional[str] = None
    kind: str
    config: dict[str, Any] = Field(default_factory=dict)
    logic: dict[str, Any] = Field(default_factory=dict)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    is_enabled: bool = True


class TriggerUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    logic: Optional[dict[str, Any]] = None
    actions: Optional[list[dict[str, Any]]] = None
    is_enabled: Optional[bool] = None


class TriggerResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    description: Optional[str] = None
    kind: str
    config: dict[str, Any]
    logic: dict[str, Any]
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
    status: str
    payload: dict[str, Any]
    result: dict[str, Any]
    error: Optional[str] = None
    cli_session_id: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None


class AgentTraceResponse(BaseModel):
    id: UUID
    user_id: UUID
    trigger_run_id: Optional[UUID] = None
    agent_name: str
    event_type: str
    content: dict[str, Any]
    parent_trace_id: Optional[UUID] = None
    created_at: datetime


# ============================================================
# Notifications
# ============================================================

class NotificationResponse(BaseModel):
    id: UUID
    user_id: UUID
    kind: str
    title: str
    body: Optional[str] = None
    block_id: Optional[UUID] = None
    trigger_run_id: Optional[UUID] = None
    severity: str
    due_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    created_at: datetime


# ============================================================
# Search (Phase 7)
# ============================================================

class SearchRequest(BaseModel):
    query: str
    limit: int = 20


class SearchHit(BaseModel):
    block_id: UUID
    similarity: float
    summary: Optional[str] = None
