"""
chat_artifact のデータスキーマ
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID


class ChatArtifactCreate(BaseModel):
    project_id: Optional[UUID] = None
    message_id: Optional[UUID] = None
    slug: str = Field(..., min_length=1)
    kind: str = Field(default="production")
    artifact_type: str = Field(default="tool")
    label: Optional[str] = None
    preview_url: str
    share_url: Optional[str] = None
    draft_url: Optional[str] = None
    production_url: Optional[str] = None
    custom_domain: Optional[str] = None
    publish_status: str = Field(default="preview_live")
    last_publish_error: Optional[str] = None


class ChatArtifactUpdate(BaseModel):
    label: Optional[str] = None
    preview_url: Optional[str] = None
    share_url: Optional[str] = None
    draft_url: Optional[str] = None
    production_url: Optional[str] = None
    custom_domain: Optional[str] = None
    publish_status: Optional[str] = None
    last_publish_error: Optional[str] = None
    kind: Optional[str] = None
    artifact_type: Optional[str] = None


class ChatArtifactDomainRequest(BaseModel):
    domain: str = Field(..., min_length=3)


class ChatArtifactResponse(BaseModel):
    id: UUID
    project_id: Optional[UUID] = None
    message_id: Optional[UUID] = None
    slug: str
    kind: str
    artifact_type: str = "tool"
    label: Optional[str] = None
    preview_url: str
    share_url: Optional[str] = None
    draft_url: Optional[str] = None
    production_url: Optional[str] = None
    custom_domain: Optional[str] = None
    publish_status: str = "preview_live"
    last_publish_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime] = None

    class Config:
        from_attributes = True
