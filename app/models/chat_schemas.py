"""
Pydantic Schemas for Done Chat
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from datetime import datetime
from enum import Enum


# ==================== Enums ====================

class AIMode(str, Enum):
    """AI Mode options"""
    OFF = "off"
    ASSIST = "assist"
    AUTO = "auto"


class RoomType(str, Enum):
    """Room type"""
    DIRECT = "direct"
    GROUP = "group"
    DAN = "dan"  # ダンページ（ユーザーとダンの1対1会話）


class MemberRole(str, Enum):
    """Member role in a room"""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class SenderType(str, Enum):
    """Message sender type"""
    HUMAN = "human"
    AI = "ai"


# ==================== Auth Schemas ====================

class RegisterRequest(BaseModel):
    """User registration request"""
    email: EmailStr
    password: str = Field(..., min_length=8)
    display_name: str = Field(..., min_length=1, max_length=100)


class LoginRequest(BaseModel):
    """User login request"""
    email: EmailStr
    password: str
    remember_me: bool = False  # ログイン状態を保持するか


class TokenResponse(BaseModel):
    """JWT token response (Bearer token - for backwards compatibility)"""
    access_token: str
    token_type: str = "bearer"


class TokenPairResponse(BaseModel):
    """JWT token pair response (for cookie-based auth)"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expires


class RefreshTokenRequest(BaseModel):
    """Refresh token request (when not using cookies)"""
    refresh_token: str


class UserResponse(BaseModel):
    """User profile response"""
    id: str
    email: str
    display_name: str
    avatar_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class UserUpdateRequest(BaseModel):
    """User profile update request"""
    display_name: Optional[str] = Field(None, min_length=1, max_length=100)
    avatar_url: Optional[str] = None


# ==================== Invite Schemas ====================

class InviteCreateRequest(BaseModel):
    """Create invite request"""
    max_uses: int = Field(default=1, ge=1, le=100)
    expires_in_hours: Optional[int] = Field(default=24, ge=1, le=720)  # Max 30 days


class InviteResponse(BaseModel):
    """Invite response"""
    id: str
    code: str
    invite_url: str
    max_uses: int
    use_count: int
    expires_at: Optional[datetime] = None
    created_at: datetime


class InviteInfoResponse(BaseModel):
    """Invite info response (for accept page)"""
    code: str
    creator_name: str
    creator_avatar_url: Optional[str] = None
    expires_at: Optional[datetime] = None
    is_valid: bool


class InviteAcceptResponse(BaseModel):
    """Invite accept response"""
    friend_id: str
    room_id: str
    message: str = "Friend added successfully"


# ==================== Friend Schemas ====================

class FriendResponse(BaseModel):
    """Friend response"""
    id: str
    display_name: str
    avatar_url: Optional[str] = None
    created_at: datetime


class FriendsListResponse(BaseModel):
    """Friends list response"""
    friends: list[FriendResponse]


# ==================== Room Schemas ====================

class RoomCreateRequest(BaseModel):
    """Create room request"""
    name: str = Field(..., min_length=1, max_length=100)
    member_ids: list[str] = Field(..., min_length=1)


class RoomUpdateRequest(BaseModel):
    """Update room request"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)


class RoomResponse(BaseModel):
    """Room response"""
    id: str
    name: Optional[str] = None
    type: RoomType
    my_role: Optional[MemberRole] = None
    my_ai_mode: Optional[AIMode] = None
    last_read_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class RoomsListResponse(BaseModel):
    """Rooms list response"""
    rooms: list[RoomResponse]


class RoomMemberResponse(BaseModel):
    """Room member response"""
    user_id: str
    display_name: str
    avatar_url: Optional[str] = None
    role: MemberRole
    ai_mode: AIMode
    joined_at: datetime


class RoomMembersListResponse(BaseModel):
    """Room members list response"""
    members: list[RoomMemberResponse]


class AddMemberRequest(BaseModel):
    """Add member request"""
    user_id: str


# ==================== Message Schemas ====================

class MessageSendRequest(BaseModel):
    """Send message request"""
    content: str = Field(..., min_length=1, max_length=10000)


class MessageResponse(BaseModel):
    """Message response"""
    id: str
    room_id: str
    sender_id: Optional[str] = None
    sender_name: str
    sender_type: SenderType
    content: str
    created_at: datetime


class MessagesListResponse(BaseModel):
    """Messages list response"""
    messages: list[MessageResponse]


class ReadMarkResponse(BaseModel):
    """Read mark response"""
    success: bool
    read_at: datetime


# ==================== AI Settings Schemas ====================

class AISettingsResponse(BaseModel):
    """AI settings response"""
    room_id: str
    enabled: bool
    mode: AIMode
    personality: Optional[str] = None
    auto_reply_delay_ms: int


class AISettingsUpdateRequest(BaseModel):
    """Update AI settings request"""
    enabled: Optional[bool] = None
    mode: Optional[AIMode] = None
    personality: Optional[str] = None
    auto_reply_delay_ms: Optional[int] = Field(None, ge=0, le=30000)


class AISummaryResponse(BaseModel):
    """AI summary response"""
    summary: str
    message_count: int
    last_message_at: Optional[datetime] = None


# ==================== Dan Page Schemas (2E) ====================

class DanRoomResponse(BaseModel):
    """ダンページルーム情報"""
    id: str
    name: str = "ダン"
    type: RoomType = RoomType.DAN
    unread_count: int = 0
    pending_proposals_count: int = 0
    last_message_at: Optional[datetime] = None
    created_at: datetime


# ==================== Proposal Schemas (2G) ====================

class ProposalStatus(str, Enum):
    """提案ステータス"""
    PENDING = "pending"      # 保留中
    APPROVED = "approved"    # 承認済み
    REJECTED = "rejected"    # 却下済み
    EXPIRED = "expired"      # 期限切れ


class ProposalType(str, Enum):
    """提案タイプ"""
    REPLY = "reply"          # 返信案
    ACTION = "action"        # アクション提案
    SCHEDULE = "schedule"    # スケジュール登録
    REMINDER = "reminder"    # リマインダー


class ProposalCreateRequest(BaseModel):
    """提案作成リクエスト（内部用）"""
    type: ProposalType
    title: str = Field(..., max_length=200)
    content: str = Field(..., max_length=5000)
    source_room_id: Optional[str] = None  # 元のチャットルームID
    source_message_id: Optional[str] = None  # 元のメッセージID
    action_data: Optional[dict] = None  # アクション実行に必要なデータ
    expires_at: Optional[datetime] = None


class ProposalResponse(BaseModel):
    """提案レスポンス"""
    id: str
    user_id: str
    type: ProposalType
    status: ProposalStatus
    title: str
    content: str
    source_room_id: Optional[str] = None
    source_room_name: Optional[str] = None
    source_message_id: Optional[str] = None
    action_data: Optional[dict] = None
    expires_at: Optional[datetime] = None
    created_at: datetime
    responded_at: Optional[datetime] = None


class ProposalsListResponse(BaseModel):
    """提案一覧レスポンス"""
    proposals: list[ProposalResponse]
    total_count: int
    pending_count: int


class ProposalActionRequest(BaseModel):
    """提案アクションリクエスト"""
    action: str = Field(..., pattern="^(approve|reject|edit)$")
    edited_content: Optional[str] = None  # action="edit"の場合に使用
