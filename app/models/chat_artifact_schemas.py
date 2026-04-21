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
    kind: str = Field(default="demo")
    label: Optional[str] = None
    preview_url: str


class ChatArtifactUpdate(BaseModel):
    label: Optional[str] = None
    preview_url: Optional[str] = None
    kind: Optional[str] = None


class ChatArtifactResponse(BaseModel):
    id: UUID
    project_id: Optional[UUID] = None
    message_id: Optional[UUID] = None
    slug: str
    kind: str
    label: Optional[str] = None
    preview_url: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
