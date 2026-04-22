"""
image_generation のデータスキーマ
"""
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
from uuid import UUID


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    project_id: Optional[UUID] = None
    message_id: Optional[UUID] = None
    size: Literal["1024x1024", "1024x1536", "1536x1024"] = "1024x1024"


class ImageEditRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    reference_url: str = Field(..., min_length=1)
    project_id: Optional[UUID] = None
    message_id: Optional[UUID] = None


class GeneratedImageResponse(BaseModel):
    id: UUID
    project_id: Optional[UUID] = None
    message_id: Optional[UUID] = None
    prompt: str
    url: str
    storage_path: Optional[str] = None
    model: Optional[str] = None
    kind: str
    reference_url: Optional[str] = None
    mime_type: Optional[str] = None
    size: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
