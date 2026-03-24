"""
Studio Schemas - AI Vlog Production Dashboard
"""
from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime


# ==================== Channel ====================

class ChannelCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    concept: Optional[str] = None
    character_name: Optional[str] = None
    character_description: Optional[str] = None


class ChannelUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    concept: Optional[str] = None
    character_name: Optional[str] = None
    character_description: Optional[str] = None
    character_image_url: Optional[str] = None
    youtube_channel_id: Optional[str] = None
    youtube_channel_url: Optional[str] = None


class ChannelResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    concept: Optional[str] = None
    character_name: Optional[str] = None
    character_description: Optional[str] = None
    character_image_url: Optional[str] = None
    youtube_channel_id: Optional[str] = None
    youtube_channel_url: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime


# ==================== Episode ====================

class EpisodeCreateRequest(BaseModel):
    channel_id: str
    title: str
    episode_number: Optional[int] = None
    description: Optional[str] = None


class EpisodeUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    script: Optional[str] = None
    status: Optional[str] = None
    scheduled_at: Optional[datetime] = None


class EpisodeResponse(BaseModel):
    id: str
    channel_id: str
    episode_number: Optional[int] = None
    title: str
    description: Optional[str] = None
    script: Optional[str] = None
    script_messages: List[Any] = []
    status: str
    youtube_video_id: Optional[str] = None
    youtube_url: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# ==================== Script Chat ====================

class ScriptMessageRequest(BaseModel):
    episode_id: str
    message: str


class ScriptMessageResponse(BaseModel):
    role: str
    content: str


# ==================== Voice ====================

class VoiceGenerateRequest(BaseModel):
    episode_id: str
    text: str
    label: Optional[str] = None
    voice_id: Optional[str] = None


class VoiceTrackResponse(BaseModel):
    id: str
    episode_id: str
    label: Optional[str] = None
    text_content: str
    voice_id: Optional[str] = None
    file_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    status: str
    created_at: datetime


# ==================== Video ====================

class VideoGenerateRequest(BaseModel):
    episode_id: str
    prompt: str
    negative_prompt: Optional[str] = None
    duration: int = 5
    mode: str = "std"
    label: Optional[str] = None


class VideoClipResponse(BaseModel):
    id: str
    episode_id: str
    label: Optional[str] = None
    prompt: str
    file_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    kling_task_id: Optional[str] = None
    kling_status: str
    sort_order: int
    created_at: datetime
    updated_at: datetime
