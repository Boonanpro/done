"""note投稿システムのPydanticスキーマ"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone
from enum import Enum


# ==================== Enums ====================

class DraftStatus(str, Enum):
    DRAFT = "draft"
    POLISHED = "polished"
    POSTED = "posted"
    PUBLISHED = "published"


class PostStatus(str, Enum):
    DRAFT_ON_NOTE = "draft_on_note"
    PUBLISHED = "published"


# ==================== Draft Schemas ====================

class DraftCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list, max_length=10)


class DraftUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    content: Optional[str] = Field(None, min_length=1)
    tags: Optional[list[str]] = None


class DraftResponse(BaseModel):
    id: str
    title: str
    content: str
    tags: list[str] = []
    status: str
    created_at: datetime


class DraftListResponse(BaseModel):
    drafts: list[DraftResponse]


# ==================== Polish Schemas ====================

class ArticleType(str, Enum):
    FREE = "free"
    PAID = "paid"


class PolishRequest(BaseModel):
    draft_id: str


class PolishExecuteRequest(BaseModel):
    article_type: ArticleType = ArticleType.FREE
    price: Optional[int] = Field(None, ge=100, le=50000, description="有料記事の価格（円）")


class PolishPromptResponse(BaseModel):
    draft_id: str
    prompt: str
    draft_title: str
    draft_content: str


class PolishSaveRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    tags: list[str] = Field(default_factory=list)
    full_text: str = Field(..., min_length=1)
    hook: Optional[str] = None
    summary: Optional[str] = None


class PolishedResponse(BaseModel):
    draft_id: str
    title: str
    tags: list[str] = []
    full_text: str
    hook: Optional[str] = None
    summary: Optional[str] = None
    polished_at: datetime
    status: str


# ==================== Post Schemas ====================

class PostRecordRequest(BaseModel):
    draft_id: str
    note_url: str
    published: bool = False


class PostResponse(BaseModel):
    draft_id: str
    note_url: str
    title: str
    published: bool
    posted_at: datetime
    status: str


class PostListResponse(BaseModel):
    posts: list[PostResponse]


# ==================== Schedule Schemas ====================


class ScheduleStatus(str, Enum):
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScheduleCreateRequest(BaseModel):
    draft_id: str
    scheduled_at: datetime = Field(..., description="投稿予定日時（ISO8601）")
    article_type: ArticleType = ArticleType.FREE
    price: Optional[int] = Field(None, ge=100, le=50000, description="有料記事の価格（円）")


class ScheduleUpdateRequest(BaseModel):
    scheduled_at: Optional[datetime] = None
    article_type: Optional[ArticleType] = None
    price: Optional[int] = Field(None, ge=100, le=50000)


class ScheduleResponse(BaseModel):
    id: str
    draft_id: str
    scheduled_at: datetime
    status: str
    article_type: str = "free"
    price: Optional[int] = None
    error_message: Optional[str] = None
    published_url: Optional[str] = None
    draft_title: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ScheduleListResponse(BaseModel):
    schedules: list[ScheduleResponse]


class ScheduleDueResponse(BaseModel):
    """実行すべきスケジュール一覧（ワーカー用）"""
    schedules: list[ScheduleResponse]


# ==================== Stats Schema ====================

class StatsResponse(BaseModel):
    total_drafts: int = 0
    total_posts: int = 0
    published: int = 0
    draft_on_note: int = 0
    pending_drafts: int = 0
    polished_drafts: int = 0
    scheduled: int = 0
