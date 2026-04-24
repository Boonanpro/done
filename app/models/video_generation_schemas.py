"""
video_generation のデータスキーマ
"""
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
from uuid import UUID


class VideoGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    project_id: Optional[UUID] = None
    message_id: Optional[UUID] = None
    aspect_ratio: Literal["16:9", "9:16", "1:1"] = "16:9"
    duration: Literal["5", "10"] = "5"
    reference_image_url: Optional[str] = None  # 指定時は image-to-video


class GeneratedVideoResponse(BaseModel):
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
    duration_seconds: Optional[int] = None
    aspect_ratio: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
