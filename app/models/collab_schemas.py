"""
Pydantic Schemas for Collaboration Rooms
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class CollabSenderType(str, Enum):
    OWNER = "owner"
    GUEST = "guest"
    DAN_OWNER = "dan_owner"
    DAN_GUEST = "dan_guest"


class CollabRoomStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class InviteStatus(str, Enum):
    PENDING = "pending"
    JOINED = "joined"
    EXPIRED = "expired"


class InviteRole(str, Enum):
    REVIEWER = "reviewer"
    EDITOR = "editor"


# ==================== AI Assist Config ====================

class AIAssistConfig(BaseModel):
    summarize_feedback: bool = True
    auto_organize_files: bool = True
    auto_suggest_fixes: bool = False


# ==================== Room ====================

class CollabRoomCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    project_ref: Optional[str] = None
    ai_auto_assist: bool = True
    ai_assist_config: Optional[AIAssistConfig] = None
    # 紐づけ先の本体チャットルーム。指定するとゲスト発言でその部屋のダンが自動起動する
    origin_chat_room_id: Optional[str] = None


class CollabRoomUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[CollabRoomStatus] = None
    ai_auto_assist: Optional[bool] = None
    ai_assist_config: Optional[AIAssistConfig] = None


class CollabRoomResponse(BaseModel):
    id: str
    owner_id: str
    title: str
    description: Optional[str] = None
    project_ref: Optional[str] = None
    status: str
    ai_auto_assist: bool
    ai_assist_config: Optional[dict] = None
    guest_count: int = 0
    last_message: Optional[str] = None
    last_message_at: Optional[datetime] = None
    # 未読=相手（ゲスト）の公開メッセージがオーナーの既読位置より後にあるか。
    # サーバーが唯一の真実（PC/APKどちらで読んでも全端末で消える）。
    unread: bool = False
    unread_count: int = 0
    created_at: datetime
    updated_at: datetime


class CollabRoomListResponse(BaseModel):
    rooms: List[CollabRoomResponse]


# ==================== Invite ====================

class CollabInviteCreateRequest(BaseModel):
    role: InviteRole = InviteRole.REVIEWER
    expires_hours: int = Field(default=72, ge=1, le=720)


class CollabInviteResponse(BaseModel):
    id: str
    room_id: str
    token: str
    invite_url: str
    role: str
    status: str
    guest_name: Optional[str] = None
    expires_at: datetime
    joined_at: Optional[datetime] = None
    created_at: datetime


class CollabJoinRequest(BaseModel):
    guest_name: str = Field(..., min_length=1, max_length=50)


class CollabJoinResponse(BaseModel):
    room_id: str
    room_title: str
    guest_token: str
    guest_name: str
    role: str
    # 本人専用URL用トークン（/collab/join/<personal_token>）。端末・ブラウザを問わず本人を特定する
    personal_token: Optional[str] = None


# ==================== Messages ====================

class CollabMessageSendRequest(BaseModel):
    # 添付だけのメッセージ（metadata.files）は本文空でよい。ルート側で「本文か添付のどちらか必須」を検証
    content: str = ""
    metadata: Optional[dict] = None


class CollabMessageResponse(BaseModel):
    id: str
    room_id: str
    sender_type: str
    sender_name: str
    content: str
    metadata: Optional[dict] = None
    created_at: datetime


class CollabMessageListResponse(BaseModel):
    messages: List[CollabMessageResponse]


# ==================== Generate Reply ====================

class GenerateReplyRequest(BaseModel):
    message_id: str
    content: str


# ==================== Files ====================

class CollabFileResponse(BaseModel):
    id: str
    room_id: str
    message_id: Optional[str] = None
    uploaded_by: str
    file_name: str
    file_path: str
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    created_at: datetime


class CollabFileListResponse(BaseModel):
    files: List[CollabFileResponse]


# ==================== WebSocket Messages ====================

class WSMessage(BaseModel):
    type: str  # auth, auth_guest, join, message, typing, ping
    token: Optional[str] = None
    room_id: Optional[str] = None
    content: Optional[str] = None
    metadata: Optional[dict] = None
