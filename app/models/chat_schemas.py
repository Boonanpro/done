"""
Pydantic Schemas for Done Chat
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
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
    PROJECT = "project"  # プロジェクト専用ルーム


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
    guest_tokens: Optional[list[str]] = None


class LoginRequest(BaseModel):
    """User login request"""
    email: EmailStr
    password: str
    remember_me: bool = False  # ログイン状態を保持するか
    guest_tokens: Optional[list[str]] = None


class TokenResponse(BaseModel):
    """JWT token response (Bearer token - for backwards compatibility)"""
    access_token: str
    token_type: str = "bearer"
    # Cookieを使えないクライアント（APK）が長期セッションを維持するための
    # リフレッシュトークン。Webはこのフィールドを無視してCookieの方を使う。
    refresh_token: Optional[str] = None


class TokenPairResponse(BaseModel):
    """JWT token pair response (for cookie-based auth)"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expires


class RefreshTokenRequest(BaseModel):
    """Refresh token request (when not using cookies)"""
    # 省略時はCookieのリフレッシュトークンにフォールバックする（422にしない）
    refresh_token: Optional[str] = None


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
    content: str = Field(..., min_length=0, max_length=10000)
    session_id: Optional[str] = Field(None, description="Target session/room ID")
    image_urls: Optional[List[str]] = Field(default=[], description="Uploaded image URLs for vision")
    file_urls: Optional[List[dict]] = Field(default=[], description="Uploaded file URLs [{name, url}]")
    reply_to_id: Optional[str] = Field(None, description="ID of the message being replied to")
    replace_message_id: Optional[str] = Field(None, description="ID of existing user message to update instead of creating new")
    client_message_id: Optional[str] = Field(None, description="Client-side optimistic message id — lets an early cancel delete the row before the client learns the real id")
    timeline_refs: Optional[List[dict]] = Field(default=[], description="Explicit production timeline references [{content_id, title}]")


class ReplyToMessage(BaseModel):
    """Embedded reply-to message summary"""
    id: str
    sender_name: str
    sender_type: SenderType
    content: str
    created_at: datetime


class MessageResponse(BaseModel):
    """Message response"""
    id: str
    room_id: str
    sender_id: Optional[str] = None
    sender_name: str
    sender_type: SenderType
    content: str
    created_at: datetime
    ai_context: Optional[dict] = None  # reasoning_steps等を含む
    reply_to_id: Optional[str] = None
    reply_to_message: Optional[ReplyToMessage] = None


class MessagesListResponse(BaseModel):
    """Messages list response"""
    messages: list[MessageResponse]


class ProcessStep(BaseModel):
    """プロセスステップ"""
    id: str
    label: str
    status: str  # "pending" | "running" | "completed" | "error"


class DanMessageResponse(BaseModel):
    """ダンへのメッセージ送信レスポンス（ユーザーメッセージ + AI返信）"""
    user_message: MessageResponse
    ai_message: MessageResponse
    process_steps: list[ProcessStep] = []


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


# ==================== Chat Session Schemas ====================

class SessionResponse(BaseModel):
    """チャットセッション情報"""
    id: str
    title: str
    last_message: Optional[str] = None
    last_message_at: Optional[datetime] = None
    message_count: int = 0
    created_at: datetime


class SessionsListResponse(BaseModel):
    """セッション一覧レスポンス"""
    sessions: list[SessionResponse]
    current_session_id: Optional[str] = None


class SessionCreateResponse(BaseModel):
    """新規セッション作成レスポンス"""
    id: str
    title: str
    created_at: datetime


class SessionActivateResponse(BaseModel):
    """セッション切り替えレスポンス"""
    success: bool
    session_id: str


class SessionUpdateRequest(BaseModel):
    """セッションタイトル更新リクエスト"""
    title: str = Field(..., min_length=1, max_length=100)


# ==================== Proposal Schemas (2G) ====================

class ProposalStatus(str, Enum):
    """提案ステータス"""
    PENDING = "pending"      # 保留中
    APPROVED = "approved"    # 承認済み
    REJECTED = "rejected"    # 却下済み
    EXPIRED = "expired"      # 期限切れ
    SENT = "sent"            # 送信済み（outbound）
    SENDING = "sending"      # 送信中ロック（outbound: ダンが手動送信作業中・操作不可）


class ProposalType(str, Enum):
    """提案タイプ"""
    REPLY = "reply"              # 返信案
    ACTION = "action"            # アクション提案
    SCHEDULE = "schedule"        # スケジュール登録
    REMINDER = "reminder"        # リマインダー
    OBSERVATION = "observation"  # 観察者の事後報告
    NOTIFY = "notify"            # 返信不要だが知らせるべき重要情報(FYI通知)
    OUTBOUND = "outbound"        # 外部宛メッセージの文面カード（compose_message）


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
