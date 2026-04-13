"""Pydantic schemas for Dan Workspace blocks."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

BlockType = Literal[
    "page", "paragraph", "heading", "bullet_list", "numbered_list",
    "checklist", "task", "quote", "code", "divider", "callout",
    "image", "video", "audio", "pdf", "file", "embed",
    "email", "calendar_event", "table", "database", "bookmark",
]

BlockSource = Literal[
    "manual", "gmail", "calendar", "collab", "chat", "file_upload", "agent",
]

CreatedBy = Literal["user", "ai", "system"]


class BlockBase(BaseModel):
    type: BlockType
    parent_id: UUID | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    content: list[Any] = Field(default_factory=list)
    icon: str | None = None
    cover_url: str | None = None
    tags: list[str] = Field(default_factory=list)


class BlockCreate(BlockBase):
    """新規ブロック作成用。order_keyは未指定なら末尾に自動配置。"""
    after_block_id: UUID | None = None  # このブロックの直後に配置
    before_block_id: UUID | None = None  # このブロックの直前に配置
    source: BlockSource = "manual"
    source_id: str | None = None
    created_by: CreatedBy = "user"


class BlockUpdate(BaseModel):
    type: BlockType | None = None
    properties: dict[str, Any] | None = None
    content: list[Any] | None = None
    icon: str | None = None
    cover_url: str | None = None
    is_starred: bool | None = None
    tags: list[str] | None = None


class BlockMove(BaseModel):
    """ブロックの親変更・並び替え用。"""
    parent_id: UUID | None = None
    after_block_id: UUID | None = None
    before_block_id: UUID | None = None


class BlockFileResponse(BaseModel):
    id: UUID
    storage_path: str
    original_name: str
    mime_type: str
    file_size: int
    version: int
    is_current: bool
    thumbnail_path: str | None = None
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    created_at: datetime


class BlockResponse(BaseModel):
    id: UUID
    user_id: UUID
    parent_id: UUID | None
    type: BlockType
    order_key: str
    properties: dict[str, Any]
    content: list[Any]
    icon: str | None
    cover_url: str | None
    is_starred: bool
    tags: list[str]
    created_by: CreatedBy
    source: BlockSource
    source_id: str | None
    created_at: datetime
    updated_at: datetime
    files: list[BlockFileResponse] = Field(default_factory=list)
    children_count: int = 0


class BlockTreeNode(BaseModel):
    """サイドバー・ツリー表示用の軽量スキーマ。"""
    id: UUID
    parent_id: UUID | None
    type: BlockType
    title: str
    icon: str | None
    is_starred: bool
    order_key: str
    has_children: bool


class BlockListResponse(BaseModel):
    blocks: list[BlockResponse]
    total: int
