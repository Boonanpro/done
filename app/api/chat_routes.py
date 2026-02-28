"""
Chat API Routes for Done Chat
Supports both Bearer token and HttpOnly Cookie authentication
"""
from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect, Response, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from datetime import datetime, timezone
import json
import logging
from pathlib import Path

from app.config import settings

from app.services.auth_service import (
    decode_access_token, create_token_pair, refresh_tokens,
    TokenData
)
from app.services.chat_service import ChatService, parse_datetime
from app.models.chat_schemas import (
    # Auth
    RegisterRequest, LoginRequest, TokenResponse,
    UserResponse, UserUpdateRequest,
    # Invite
    InviteCreateRequest, InviteResponse, InviteInfoResponse, InviteAcceptResponse,
    # Friends
    FriendResponse, FriendsListResponse,
    # Rooms
    RoomCreateRequest, RoomUpdateRequest, RoomResponse, RoomsListResponse,
    RoomMemberResponse, RoomMembersListResponse, AddMemberRequest,
    # Messages
    MessageSendRequest, MessageResponse, MessagesListResponse, ReadMarkResponse,
    # AI
    AISettingsResponse, AISettingsUpdateRequest, AISummaryResponse,
    # Dan Page & Proposals (2E & 2G)
    DanRoomResponse, ProposalResponse, ProposalsListResponse, ProposalActionRequest,
    # Sessions
    SessionResponse, SessionsListResponse, SessionCreateResponse,
    SessionActivateResponse, SessionUpdateRequest,
)

from pydantic import BaseModel


class CancelRequest(BaseModel):
    """キャンセルリクエスト"""
    session_id: str

router = APIRouter(prefix="/chat", tags=["chat"])
security = HTTPBearer(auto_error=False)

# Cookie names
ACCESS_TOKEN_COOKIE = "done_access_token"
REFRESH_TOKEN_COOKIE = "done_refresh_token"
WORKSPACE_DIR = Path.home() / ".dan" / "workspace"
WORKSPACE_MEMORY_DIR = WORKSPACE_DIR / "memory"
COMPACTION_SNAPSHOT_INTERVAL_MESSAGES = 40
logger = logging.getLogger(__name__)
REPLAN_KEYWORDS = (
    "やっぱり",
    "方針変更",
    "方向転換",
    "仕様変更",
    "変更したい",
    "見直し",
    "再計画",
    "再提案",
    "再調査",
    "別案",
    "ピボット",
    "change direction",
    "replan",
    "pivot",
    "revise plan",
)


def _is_replan_request(text: str) -> bool:
    """ユーザー入力が再計画リクエストかを緩く判定する。"""
    if not text:
        return False
    lowered = text.lower()
    return any(keyword in text or keyword in lowered for keyword in REPLAN_KEYWORDS)


def _compact_text(text: str, limit: int = 220) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = " ".join(line.strip() for line in text.split("\n") if line.strip())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def _build_content_with_images(content: str, image_urls: list) -> str:
    """画像URLをローカルパスに変換してcontentの先頭に付加する"""
    if not image_urls:
        return content
    import os
    upload_dir = os.path.join(os.path.dirname(__file__), "..", "..", "uploads")
    upload_dir = os.path.normpath(upload_dir)
    lines = []
    for url in image_urls:
        filename = url.split("/")[-1]
        local_path = os.path.join(upload_dir, filename).replace("\\", "/")
        lines.append(f"[添付画像: {local_path}]")
    image_prefix = "\n".join(lines)
    return f"{image_prefix}\n\n{content}" if content.strip() else image_prefix


def _fetch_latest_user_message_from_room(service: ChatService, room_id: str) -> str:
    """指定ルームの最新ユーザーメッセージを取得する（旧データ互換を含む）。"""
    if not room_id:
        return ""
    try:
        result = (
            service.supabase.table("chat_messages")
            .select("content, sender_type")
            .eq("room_id", room_id)
            .in_("sender_type", ["human", "user"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return ""
        return result.data[0].get("content", "") or ""
    except Exception as e:
        logger.warning("Failed to fetch latest user message (room=%s): %s", room_id, e)
        return ""


def _build_session_memory_summary_entry(
    *,
    archive_type: str,
    room_id: str,
    messages: list[dict],
    is_project: bool,
    project_title: str = "",
    project_status: str = "",
    message_count: Optional[int] = None,
) -> Optional[str]:
    if not messages:
        return None

    chronological = list(reversed(messages))
    created_values = []
    for msg in chronological:
        dt = parse_datetime(msg.get("created_at"))
        if dt:
            created_values.append(dt)

    period_label = "-"
    if created_values:
        period_label = (
            f"{created_values[0].strftime('%Y-%m-%d %H:%M:%S')} -> "
            f"{created_values[-1].strftime('%Y-%m-%d %H:%M:%S')}"
        )

    user_msgs = [m for m in chronological if m.get("sender_type") == "human"]
    ai_msgs = [m for m in chronological if m.get("sender_type") == "ai"]
    last_user = _compact_text(user_msgs[-1]["content"]) if user_msgs else "-"
    last_ai = _compact_text(ai_msgs[-1]["content"]) if ai_msgs else "-"

    recent = chronological[-8:]
    excerpt_lines = []
    for m in recent:
        role = "User" if m.get("sender_type") == "human" else "Assistant"
        excerpt_lines.append(f"- {role}: {_compact_text(m.get('content', ''), limit=160)}")

    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    project_label = project_title.strip() if project_title else "-"
    status_label = project_status.strip() if project_status else "-"
    total_count = message_count if message_count is not None else len(messages)

    return (
        f"### {ts} [{archive_type}] room={room_id}\n"
        f"- mode: {'project' if is_project else 'chat'}\n"
        f"- project_title: {project_label}\n"
        f"- project_status: {status_label}\n"
        f"- total_messages: {total_count}\n"
        f"- sampled_messages: {len(messages)}\n"
        f"- period: {period_label}\n\n"
        f"#### Last User Intent\n{last_user}\n\n"
        f"#### Last Assistant Response\n{last_ai}\n\n"
        f"#### Recent Excerpts\n" + ("\n".join(excerpt_lines) if excerpt_lines else "- (none)") + "\n\n"
    )


def _append_memory_entry(entry: str) -> None:
    if not entry:
        return

    try:
        WORKSPACE_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        log_path = WORKSPACE_MEMORY_DIR / f"{date_str}.md"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        logger.warning("Failed to append memory entry: %s", e)


async def _archive_session_summary(
    *,
    service: ChatService,
    user_id: str,
    room_id: str,
    archive_type: str,
    is_project: bool,
    project_title: str = "",
    project_status: str = "",
    force: bool = False,
) -> None:
    try:
        count_result = (
            service.supabase.table("chat_messages")
            .select("id", count="exact")
            .eq("room_id", room_id)
            .execute()
        )
        total_messages = count_result.count or 0
        if total_messages == 0:
            return

        if not force:
            if total_messages < COMPACTION_SNAPSHOT_INTERVAL_MESSAGES:
                return
            if total_messages % COMPACTION_SNAPSHOT_INTERVAL_MESSAGES != 0:
                return

        sample_limit = min(120, total_messages)
        messages = await service.get_messages(room_id, user_id, limit=sample_limit)
        entry = _build_session_memory_summary_entry(
            archive_type=archive_type,
            room_id=room_id,
            messages=messages,
            is_project=is_project,
            project_title=project_title,
            project_status=project_status,
            message_count=total_messages,
        )
        _append_memory_entry(entry or "")
    except Exception as e:
        logger.warning("Failed to archive session summary (%s): %s", archive_type, e)


def set_auth_cookies(response: Response, access_token: str, refresh_token: str, remember_me: bool = False):
    """Set HttpOnly cookies for authentication"""
    # Access token cookie (shorter lived)
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=access_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN or None,
        max_age=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    
    # Refresh token cookie (longer lived)
    refresh_max_age = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60 if remember_me else 24 * 60 * 60
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN or None,
        max_age=refresh_max_age,
        path="/api/v1/chat/refresh",  # Only sent to refresh endpoint
    )


def clear_auth_cookies(response: Response):
    """Clear authentication cookies"""
    response.delete_cookie(
        key=ACCESS_TOKEN_COOKIE,
        domain=settings.COOKIE_DOMAIN or None,
    )
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE,
        domain=settings.COOKIE_DOMAIN or None,
        path="/api/v1/chat/refresh",
    )

# Base URL for invite links (should be configured in settings)
INVITE_BASE_URL = "https://done.app/i/"


def get_chat_service() -> ChatService:
    """Get ChatService instance"""
    return ChatService()


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> TokenData:
    """Get current authenticated user from JWT token (Cookie or Bearer header)"""
    token = None
    
    # First, try to get token from cookie
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    
    # If no cookie, try Bearer header
    if not token and credentials:
        token = credentials.credentials
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    token_data = decode_access_token(token)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    return token_data


async def get_optional_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[TokenData]:
    """Get current user if authenticated, None otherwise"""
    token = None
    
    # First, try to get token from cookie
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    
    # If no cookie, try Bearer header
    if not token and credentials:
        token = credentials.credentials
    
    if not token:
        return None
    return decode_access_token(token)


# ==================== Auth Routes ====================

@router.post("/register", response_model=UserResponse)
async def register(
    request: RegisterRequest,
    service: ChatService = Depends(get_chat_service),
):
    """Register a new user"""
    try:
        user = await service.create_user(
            email=request.email,
            password=request.password,
            display_name=request.display_name,
        )
        return UserResponse(**user)
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(status_code=400, detail="Email already registered")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    response: Response,
    service: ChatService = Depends(get_chat_service),
):
    """Login and get JWT token"""
    user = await service.authenticate_user(request.email, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    token_pair = create_token_pair(user_id=user["id"], email=user["email"])
    set_auth_cookies(response, token_pair.access_token, token_pair.refresh_token)
    return TokenResponse(access_token=token_pair.access_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token_endpoint(
    request: Request,
    response: Response,
):
    """Refresh access token using refresh token from cookie"""
    refresh_token_value = request.cookies.get(REFRESH_TOKEN_COOKIE)
    if not refresh_token_value:
        raise HTTPException(status_code=401, detail="Refresh token not found")
    
    token_pair = refresh_tokens(refresh_token_value)
    if not token_pair:
        clear_auth_cookies(response)
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    
    set_auth_cookies(response, token_pair.access_token, token_pair.refresh_token)
    return TokenResponse(access_token=token_pair.access_token)


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Get current user profile"""
    user = await service.get_user_by_id(current_user.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**user)


@router.patch("/me", response_model=UserResponse)
async def update_me(
    request: UserUpdateRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Update current user profile"""
    user = await service.update_user(
        user_id=current_user.user_id,
        display_name=request.display_name,
        avatar_url=request.avatar_url,
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**user)


# ==================== Invite Routes ====================

@router.post("/invite", response_model=InviteResponse)
async def create_invite(
    request: InviteCreateRequest = InviteCreateRequest(),
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Create an invite link"""
    invite = await service.create_invite(
        creator_id=current_user.user_id,
        max_uses=request.max_uses,
        expires_in_hours=request.expires_in_hours,
    )
    return InviteResponse(
        id=invite["id"],
        code=invite["code"],
        invite_url=f"{INVITE_BASE_URL}{invite['code']}",
        max_uses=invite["max_uses"],
        use_count=invite["use_count"],
        expires_at=invite.get("expires_at"),
        created_at=invite["created_at"],
    )


@router.get("/invite/{code}", response_model=InviteInfoResponse)
async def get_invite(
    code: str,
    service: ChatService = Depends(get_chat_service),
):
    """Get invite information"""
    invite = await service.get_invite_by_code(code)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    
    # Check if valid
    is_valid = True
    if invite.get("expires_at"):
        expires_at = parse_datetime(invite["expires_at"])
        if datetime.now(timezone.utc).replace(tzinfo=expires_at.tzinfo) > expires_at:
            is_valid = False
    if invite["use_count"] >= invite["max_uses"]:
        is_valid = False
    
    creator = invite.get("creator", {})
    return InviteInfoResponse(
        code=invite["code"],
        creator_name=creator.get("display_name", "Unknown"),
        creator_avatar_url=creator.get("avatar_url"),
        expires_at=invite.get("expires_at"),
        is_valid=is_valid,
    )


@router.post("/invite/{code}/accept", response_model=InviteAcceptResponse)
async def accept_invite(
    code: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Accept an invite and become friends"""
    try:
        result = await service.accept_invite(code, current_user.user_id)
        return InviteAcceptResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== Friends Routes ====================

@router.get("/friends", response_model=FriendsListResponse)
async def get_friends(
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Get friends list"""
    friends = await service.get_friends(current_user.user_id)
    return FriendsListResponse(friends=[FriendResponse(**f) for f in friends])


@router.delete("/friends/{friend_id}")
async def delete_friend(
    friend_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Delete a friend"""
    await service.delete_friend(current_user.user_id, friend_id)
    return {"message": "Friend deleted successfully"}


# ==================== Room Routes ====================

@router.get("/rooms", response_model=RoomsListResponse)
async def get_rooms(
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Get chat rooms"""
    rooms = await service.get_rooms(current_user.user_id)
    return RoomsListResponse(rooms=[RoomResponse(**r) for r in rooms])


@router.post("/rooms", response_model=RoomResponse)
async def create_room(
    request: RoomCreateRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Create a group chat room"""
    room = await service.create_room(
        creator_id=current_user.user_id,
        name=request.name,
        member_ids=request.member_ids,
    )
    return RoomResponse(**room)


@router.get("/rooms/{room_id}", response_model=RoomResponse)
async def get_room(
    room_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Get room details"""
    room = await service.get_room(room_id, current_user.user_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return RoomResponse(**room)


@router.patch("/rooms/{room_id}", response_model=RoomResponse)
async def update_room(
    room_id: str,
    request: RoomUpdateRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Update room settings"""
    try:
        room = await service.update_room(room_id, current_user.user_id, name=request.name)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        return RoomResponse(**room)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/rooms/{room_id}/members", response_model=RoomMembersListResponse)
async def get_room_members(
    room_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Get room members"""
    try:
        members = await service.get_room_members(room_id, current_user.user_id)
        return RoomMembersListResponse(members=[RoomMemberResponse(**m) for m in members])
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/rooms/{room_id}/members", response_model=RoomMemberResponse)
async def add_room_member(
    room_id: str,
    request: AddMemberRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Add a member to the room"""
    try:
        member = await service.add_room_member(room_id, current_user.user_id, request.user_id)
        # Get full member info
        members = await service.get_room_members(room_id, current_user.user_id)
        for m in members:
            if m["user_id"] == request.user_id:
                return RoomMemberResponse(**m)
        return member
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ==================== Message Routes ====================

@router.get("/rooms/{room_id}/messages", response_model=MessagesListResponse)
async def get_messages(
    room_id: str,
    limit: int = 50,
    before: Optional[str] = None,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Get messages from a room"""
    try:
        messages = await service.get_messages(room_id, current_user.user_id, limit=limit, before=before)
        return MessagesListResponse(messages=[MessageResponse(**m) for m in messages])
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.warning("Temporary failure in get_messages (room=%s): %s", room_id, e)
        raise HTTPException(status_code=503, detail="Temporary backend error. Please retry.")


@router.post("/rooms/{room_id}/messages", response_model=MessageResponse)
async def send_message(
    room_id: str,
    request: MessageSendRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Send a message to a room"""
    try:
        message = await service.send_message(room_id, current_user.user_id, request.content)
        # Get sender info
        user = await service.get_user_by_id(current_user.user_id)
        return MessageResponse(
            id=message["id"],
            room_id=message["room_id"],
            sender_id=message["sender_id"],
            sender_name=user["display_name"] if user else "Unknown",
            sender_type=message["sender_type"],
            content=message["content"],
            created_at=message["created_at"],
        )
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/rooms/{room_id}/dry-run")
async def dry_run_message(
    room_id: str,
    request: MessageSendRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    Dry-run: 認証・ルーム存在・メンバーシップを検証するが、DBには何も書き込まない。
    事業部CLIのデバッグ用。履歴を汚さずに接続テストができる。
    """
    # ルーム存在 & メンバーシップ確認
    room = await service.get_room(room_id, current_user.user_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found or not a member")

    # プロジェクトルームかどうか判定
    is_project = False
    try:
        from app.services.project_service import ProjectService
        ps = ProjectService()
        proj_result = (
            ps.supabase.table("projects")
            .select("id")
            .eq("room_id", room_id)
            .execute()
        )
        if proj_result.data:
            is_project = True
    except Exception:
        pass

    return {
        "status": "ok",
        "room_id": room_id,
        "content_received": request.content,
        "is_project": is_project,
    }


@router.post("/rooms/{room_id}/read", response_model=ReadMarkResponse)
async def mark_as_read(
    room_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Mark messages as read"""
    success = await service.mark_as_read(room_id, current_user.user_id)
    return ReadMarkResponse(success=success, read_at=datetime.now(timezone.utc))


# ==================== AI Settings Routes ====================

@router.get("/rooms/{room_id}/ai", response_model=AISettingsResponse)
async def get_ai_settings(
    room_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Get AI settings for a room"""
    try:
        settings = await service.get_ai_settings(room_id, current_user.user_id)
        if not settings:
            raise HTTPException(status_code=404, detail="AI settings not found")
        return AISettingsResponse(**settings)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.patch("/rooms/{room_id}/ai", response_model=AISettingsResponse)
async def update_ai_settings(
    room_id: str,
    request: AISettingsUpdateRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Update AI settings for a room"""
    try:
        settings = await service.update_ai_settings(
            room_id,
            current_user.user_id,
            enabled=request.enabled,
            mode=request.mode,
            personality=request.personality,
            auto_reply_delay_ms=request.auto_reply_delay_ms,
        )
        if not settings:
            raise HTTPException(status_code=404, detail="AI settings not found")
        return AISettingsResponse(**settings)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/rooms/{room_id}/ai/summary", response_model=AISummaryResponse)
async def get_ai_summary(
    room_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Get AI summary of recent conversation"""
    try:
        summary = await service.get_ai_summary(room_id, current_user.user_id)
        return AISummaryResponse(**summary)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ==================== Dan Page Routes (2E) ====================

@router.get("/dan", response_model=DanRoomResponse)
async def get_dan_room(
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    ダンページ（ユーザーとダンの1対1ルーム）を取得
    
    - ルームが存在しない場合は自動作成
    - 未読メッセージ数と保留中の提案数も返す
    """
    try:
        dan_room = await service.get_or_create_dan_room(current_user.user_id)
        return DanRoomResponse(**dan_room)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dan/messages", response_model=MessagesListResponse)
async def get_dan_messages(
    limit: int = 50,
    before: Optional[str] = None,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """ダンページのメッセージを取得"""
    try:
        dan_room = await service.get_or_create_dan_room(current_user.user_id)
        messages = await service.get_messages(dan_room["id"], current_user.user_id, limit=limit, before=before)
        return MessagesListResponse(messages=[MessageResponse(**m) for m in messages])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dan/messages/stream")
async def send_dan_message_stream(
    request: MessageSendRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """ダンにメッセージを送信（SSEストリーミング版）- Agent v2を使用"""
    from starlette.responses import StreamingResponse
    from app.services.progress_callback import (
        ProgressCallbackRegistry,
        set_current_request_id,
    )
    import uuid
    import asyncio
    
    # 挨拶のハードコード返答は廃止。必ずAgent v2に渡す。
    
    async def generate_stream():
        # リクエストIDを生成（プログレスコールバック用）
        request_id = str(uuid.uuid4())
        progress_queue = ProgressCallbackRegistry.create_queue(request_id)
        set_current_request_id(request_id)

        # キャンセルフラグを登録
        from app.services.cancellation import CancellationRegistry
        room_id_for_cancel = None  # 後で設定
        done_sent = False  # done イベント送信済みフラグ
        result_saved = False  # AI回答DB保存済みフラグ
        cli_saved_ai_message = False  # CLIスレッドがAI応答をDB保存済みか
        replan_requested = _is_replan_request(request.content)
        run_id = None

        async def _save_project_event_safe(project_service, **kwargs):
            """Best-effort event write; avoid blocking chat execution on log writes."""
            try:
                await asyncio.wait_for(
                    project_service.save_execution_event(**kwargs),
                    timeout=5,
                )
            except Exception as event_err:
                logger.debug(
                    "Skipped execution_event write (room=%s, type=%s): %s",
                    kwargs.get("room_id"),
                    kwargs.get("event_type"),
                    event_err,
                )

        try:
            preloaded_project_info = {}
            preloaded_is_project = False
            current_project_run = None
            should_supersede_existing_run = False
            if request.session_id:
                try:
                    from app.services.project_service import ProjectService
                    from app.services.run_service import RunService

                    preload_project_service = ProjectService()
                    proj_result = (
                        preload_project_service.supabase.table("projects")
                        .select("id, title, description, status, room_id")
                        .eq("room_id", request.session_id)
                        .execute()
                    )
                    if proj_result.data:
                        preloaded_is_project = True
                        preloaded_project_info = proj_result.data[0]
                        current_project_run = await RunService().get_current_run(
                            preloaded_project_info["id"]
                        )
                        should_supersede_existing_run = bool(
                            current_project_run
                            and current_project_run.get("state")
                            not in {"completed", "failed", "superseded"}
                        )
                        if CancellationRegistry.is_active(request.session_id):
                            should_supersede_existing_run = True
                except Exception:
                    pass
            if (
                request.session_id
                and not replan_requested
                and not preloaded_is_project
                and CancellationRegistry.is_active(request.session_id)
            ):
                busy_message = "前の実行がまだ進行中です。停止してから再送してください。"
                yield f"data: {json.dumps({'type': 'error', 'session_id': request.session_id, 'message': busy_message})}\n\n"
                done_sent = True
                yield f"data: {json.dumps({'type': 'done', 'session_id': request.session_id})}\n\n"
                return

            # Step 1: ユーザーメッセージを保存
            # session_idが指定されていればそのルームに、なければ現在のDanルームに送信
            if request.session_id:
                room_id = request.session_id
                message = await service.send_message(room_id, current_user.user_id, _build_content_with_images(request.content, request.image_urls or []), sender_type="human")
            else:
                message = await service.send_dan_message(current_user.user_id, _build_content_with_images(request.content, request.image_urls or []))
                room_id = message["room_id"]
            user = await service.get_user_by_id(current_user.user_id)

            # 方針変更要求時は、既存の同一ルーム実行を先に止める
            if replan_requested or should_supersede_existing_run:
                try:
                    CancellationRegistry.cancel(room_id)
                except Exception:
                    pass

            # キャンセルフラグを登録（room_idが確定してから）
            room_id_for_cancel = room_id
            CancellationRegistry.register(room_id)

            user_message = {
                "id": message["id"],
                "room_id": room_id,
                "sender_id": message["sender_id"],
                "sender_name": user["display_name"] if user else "You",
                "sender_type": message["sender_type"],
                "content": message["content"],
                "created_at": message["created_at"].isoformat() if hasattr(message["created_at"], 'isoformat') else str(message["created_at"]),
            }

            # ユーザーメッセージを送信（session_id付き）
            yield f"data: {json.dumps({'type': 'user_message', 'session_id': room_id, 'message': user_message})}\n\n"
            
            # Step 1.5: 同一セッション（ルーム）の会話履歴を取得
            # 現在のメッセージより前のメッセージを取得（直近10件）
            conversation_history = []
            try:
                # 現在のメッセージを除く直近のメッセージを取得
                recent_messages = await service.get_messages(room_id, current_user.user_id, limit=11)
                # 最新のメッセージ（今送ったもの）を除外
                conversation_history = [
                    {
                        "sender_type": msg.get("sender_type", "unknown"),
                        "sender_name": msg.get("sender_name", ""),
                        "content": msg.get("content", ""),
                    }
                    for msg in recent_messages[1:]  # 最新を除く
                ]
                # 時系列順に並べ替え（古い順）
                conversation_history = list(reversed(conversation_history))
            except Exception as e:
                import logging
                logging.warning(f"Failed to get conversation history: {e}")
            
            # ========================================
            # プロジェクトルーム判定 → SDK Runner / 通常 Runner の分岐
            # ========================================
            is_project = preloaded_is_project
            project_info = preloaded_project_info
            try:
                if not is_project:
                    from app.services.project_service import ProjectService
                    ps = ProjectService()
                    proj_result = (
                        ps.supabase.table("projects")
                        .select("id, title, description, status")
                        .eq("room_id", room_id)
                        .execute()
                    )
                    if proj_result.data:
                        is_project = True
                        project_info = proj_result.data[0]
            except Exception:
                pass

            if is_project:
                # ========================================
                # CLI Runner でプロジェクト実行（SDK は親子タスクでフリーズするため）
                # ========================================
                from app.agent.cli_runner import process_message_cli
                from app.api.project_routes import _format_tool_label
                from app.services.run_service import RunService

                project_service = ProjectService()
                run_service = RunService()
                final_text = ""
                reasoning_steps = []   # 短いラベル（プロセスモニター表示用）
                reasoning_full = []    # 全文（DB保存用、フロントで展開表示）
                step_counter = 0
                run_state = None
                if current_project_run is None and should_supersede_existing_run:
                    try:
                        current_project_run = await run_service.get_current_run(project_info["id"])
                    except Exception:
                        current_project_run = None
                try:
                    run_metadata = {}
                    if should_supersede_existing_run and current_project_run:
                        run_metadata["started_by"] = "follow_up"
                        run_metadata["superseded_run_id"] = current_project_run["id"]
                        if current_project_run.get("active_proposal_id"):
                            run_metadata["superseded_proposal_id"] = current_project_run["active_proposal_id"]
                    if replan_requested:
                        run_metadata["direction_changed"] = True
                    run = await run_service.create_run(
                        project_id=project_info["id"],
                        room_id=room_id,
                        parent_run_id=current_project_run["id"] if current_project_run else None,
                        metadata=run_metadata or None,
                    )
                    run_id = run["id"]
                    if should_supersede_existing_run and current_project_run:
                        await run_service.supersede_run(current_project_run["id"], run_id)
                        active_proposal_id = current_project_run.get("active_proposal_id")
                        if active_proposal_id:
                            await project_service.supersede_proposal(
                                active_proposal_id,
                                project_info["id"],
                            )
                            await project_service.update_project(
                                project_info["id"],
                                current_user.user_id,
                                status="planning",
                            )
                        await _save_project_event_safe(
                            project_service,
                            project_id=project_info["id"],
                            room_id=room_id,
                            run_id=run_id,
                            event_type="phase",
                            content="previous run superseded by user follow-up",
                        )
                except Exception as run_error:
                    logger.warning(
                        "Failed to create agent run (project=%s, room=%s): %s",
                        project_info.get("id"),
                        room_id,
                        run_error,
                    )

                # 方針変更要求が来たら、現在ステータスに関係なく planning へ戻して再計画
                if replan_requested and project_info.get("status") != "planning":
                    try:
                        updated = await project_service.update_project(
                            project_info["id"],
                            current_user.user_id,
                            status="planning",
                        )
                        if updated:
                            project_info["status"] = updated.get("status", "planning")
                        else:
                            project_info["status"] = "planning"
                        await _save_project_event_safe(project_service,
                            project_id=project_info["id"],
                            room_id=room_id,
                            run_id=run_id,
                            event_type="phase",
                            content="user requested direction change; switched to planning",
                        )
                        yield f"data: {json.dumps({'type': 'process', 'session_id': room_id, 'step': {'id': 'replan-switch', 'label': '方針変更を受け、再計画モードに切り替えました', 'status': 'running'}})}\n\n"
                    except Exception as e:
                        logger.warning(
                            "Failed to switch project to planning for replan "
                            "(project=%s, room=%s): %s",
                            project_info.get("id"),
                            room_id,
                            e,
                        )

                # planning ステータスの場合、origin_room_id から依頼文を取得
                user_messages_for_cli = ""
                if project_info.get("status") == "planning":
                    # 方針変更時は、直近のユーザー依頼を優先して計画に使う
                    if replan_requested and request.content.strip():
                        user_messages_for_cli = request.content
                    try:
                        if not user_messages_for_cli:
                            origin_room_id = project_info.get("origin_room_id", "")
                            if not origin_room_id:
                                # プロジェクトテーブルから origin_room_id を取得
                                proj_full = (
                                    project_service.supabase.table("projects")
                                    .select("origin_room_id")
                                    .eq("id", project_info["id"])
                                    .execute()
                                )
                                if proj_full.data:
                                    origin_room_id = proj_full.data[0].get("origin_room_id", "")
                            if origin_room_id:
                                user_messages_for_cli = _fetch_latest_user_message_from_room(
                                    service, origin_room_id
                                )
                    except Exception:
                        pass

                async for event in process_message_cli(
                    room_id=room_id,
                    user_id=current_user.user_id,
                    content=_build_content_with_images(request.content, request.image_urls or []),
                    project_title=project_info.get("title", ""),
                    project_description=project_info.get("description", ""),
                    project_status=project_info.get("status", "in_progress"),
                    user_messages=user_messages_for_cli,
                    project_id=project_info.get("id"),
                    run_id=run_id,
                ):
                    if event["type"] == "keepalive":
                        # SSEコメント: クライアントのEventSourceパーサーは無視するが接続は維持される
                        yield ": keepalive\n\n"
                        continue

                    if event["type"] == "cancelled":
                        await service.send_dan_ai_message(current_user.user_id, "（中断されました）", [], room_id=room_id)
                        await _save_project_event_safe(project_service,
                            project_id=project_info["id"], room_id=room_id,
                            run_id=run_id,
                            event_type="done", content="cancelled",
                        )
                        if run_id:
                            await run_service.update_run(run_id, state="paused")
                        yield f"data: {json.dumps({'type': 'cancelled', 'session_id': room_id})}\n\n"
                        done_sent = True
                        result_saved = True
                        break

                    elif event["type"] == "reasoning":
                        text = event.get("text", "")
                        label = text
                        reasoning_steps.append(label)
                        if text.strip():
                            reasoning_full.append(text)
                        yield f"data: {json.dumps({'type': 'process', 'session_id': room_id, 'step': {'id': f'cli-{step_counter}', 'label': label, 'status': 'running'}})}\n\n"
                        step_counter += 1
                        # DB保存はCLIスレッドが実行済み（DB-first）

                    elif event["type"] == "tool_use":
                        tool_label = _format_tool_label(event.get("name", ""), event.get("input", {}))
                        reasoning_steps.append(f"🔧 {tool_label}")
                        yield f"data: {json.dumps({'type': 'process', 'session_id': room_id, 'step': {'id': f'cli-{step_counter}', 'label': f'🔧 {tool_label}', 'status': 'running'}})}\n\n"
                        step_counter += 1
                        # DB保存はCLIスレッドが実行済み（DB-first）

                    elif event["type"] == "text":
                        # textイベントは暫定的に記録（最終回答はresultイベントで確定する）
                        final_text = event["text"]
                        text_preview = event["text"].strip()
                        if text_preview and len(text_preview) > 10:
                            # Use full text preview without truncation.
                            label = text_preview
                            reasoning_steps.append(label)
                            reasoning_full.append(text_preview)
                            yield f"data: {json.dumps({'type': 'process', 'session_id': room_id, 'step': {'id': f'cli-{step_counter}', 'label': label, 'status': 'running'}})}\n\n"
                            step_counter += 1

                    elif event["type"] == "result":
                        result_text = event.get("text", "")
                        cli_saved_ai_message = event.get("cli_saved", False)
                        if run_id and event.get("session_id"):
                            await run_service.attach_claude_session(run_id, event["session_id"])
                        run_state = "failed" if event.get("is_error") else "completed"
                        if result_text:
                            final_text = result_text
                        elif event.get("is_error"):
                            # CLIがエラーで終了し応答テキストがない場合、エラー内容を表示
                            final_text = result_text  # エラー内容（cli_runnerが組み立て済み）

                    elif event["type"] == "error":
                        if run_id:
                            await run_service.update_run(run_id, state="failed")
                        run_state = "failed"
                        yield f"data: {json.dumps({'type': 'error', 'session_id': room_id, 'message': event['message']})}\n\n"
                        # DB保存はCLIスレッドが実行済み（DB-first）

                # キャンセル時はスキップ（cancelled ハンドラで保存済み）
                if not result_saved:
                    ai_response_content = final_text or "応答を生成できませんでした。もう一度お試しください。"

                    if cli_saved_ai_message:
                        # DB-first: CLIスレッドが既にAI応答を保存済み → クライアント送信のみ
                        ai_message = {
                            "id": "cli-saved",
                            "room_id": room_id,
                            "sender_id": None,
                            "sender_name": "ダン",
                            "sender_type": "ai",
                            "content": ai_response_content,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        }
                        yield f"data: {json.dumps({'type': 'ai_message', 'session_id': room_id, 'message': ai_message})}\n\n"
                    else:
                        # フォールバック: CLIの保存が失敗した場合は従来通りSSEからDB保存
                        ai_message_data = await service.send_dan_ai_message(
                            current_user.user_id, ai_response_content, reasoning_steps,
                            room_id=room_id, reasoning_full=reasoning_full,
                        )
                        if not ai_message_data:
                            import logging
                            logging.error(f"send_dan_ai_message returned None for user {current_user.user_id}")
                            raise ValueError("Failed to save AI message: returned None")

                        ai_message = {
                            "id": ai_message_data["id"],
                            "room_id": ai_message_data["room_id"],
                            "sender_id": ai_message_data.get("sender_id"),
                            "sender_name": "ダン",
                            "sender_type": "ai",
                            "content": ai_message_data["content"],
                            "created_at": ai_message_data["created_at"].isoformat() if hasattr(ai_message_data["created_at"], 'isoformat') else str(ai_message_data["created_at"]),
                        }
                        if ai_message_data.get("ai_context"):
                            ai_message["ai_context"] = ai_message_data["ai_context"]

                        yield f"data: {json.dumps({'type': 'ai_message', 'session_id': room_id, 'message': ai_message})}\n\n"

                    # 提案保存はSSEジェネレーターに残す（SSE断線時は提案は作成されないが、
                    # AI応答テキスト自体はCLIスレッドが保存しているのでユーザーは回答を見られる）
                    proposal_created = False
                    if project_info.get("status") == "planning" and "## 実行計画" in ai_response_content:
                        try:
                            from app.services.proposal_steps import extract_steps

                            proposal_steps = extract_steps(ai_response_content)
                            proposal = await asyncio.wait_for(
                                project_service.create_proposal(
                                    project_id=project_info["id"],
                                    run_id=run_id,
                                    content=ai_response_content,
                                    proposal_type="plan",
                                    steps=proposal_steps,
                                    metadata={
                                        "source": "project_chat_planning",
                                        "generated_by": "cli_runner",
                                    },
                                ),
                                timeout=10,
                            )
                            proposal_created = True
                            if run_id and proposal:
                                await run_service.update_run(
                                    run_id,
                                    state="awaiting_approval",
                                    active_proposal_id=proposal["id"],
                                )
                            await _save_project_event_safe(project_service,
                                project_id=project_info["id"],
                                room_id=room_id,
                                run_id=run_id,
                                event_type="phase",
                                content="planning output saved as proposal",
                            )
                        except Exception as proposal_error:
                            logger.warning(
                                "Failed to save planning output as proposal "
                                "(project=%s, room=%s): %s",
                                project_info.get("id"),
                                room_id,
                                proposal_error,
                            )
                            try:
                                await _save_project_event_safe(project_service,
                                    project_id=project_info["id"],
                                    room_id=room_id,
                                    run_id=run_id,
                                    event_type="error",
                                    content=f"proposal save failed: {proposal_error}",
                                )
                            except Exception:
                                pass

                    # doneイベントはCLIスレッドが既にDB保存済み（DB-first）
                    # 提案が作成された場合のみSSEからphaseイベントを追加保存
                    if run_id and run_state and not proposal_created:
                        await run_service.update_run(run_id, state=run_state)
                    result_saved = True
                    yield f"data: {json.dumps({'type': 'done', 'session_id': room_id})}\n\n"
                    done_sent = True

            else:
                # ========================================
                # 非プロジェクトチャットも CLI Runner に統一
                # ========================================
                from app.agent.cli_runner import process_message_cli
                from app.api.project_routes import _format_tool_label

                final_text = ""
                reasoning_steps = []
                reasoning_full = []
                step_counter = 0

                async for event in process_message_cli(
                    room_id=room_id,
                    user_id=current_user.user_id,
                    content=_build_content_with_images(request.content, request.image_urls or []),
                    project_title="",
                    project_description="",
                    project_status="in_progress",
                ):
                    if event["type"] == "keepalive":
                        yield ": keepalive\n\n"
                        continue


                    if event["type"] == "cancelled":
                        await service.send_dan_ai_message(
                            current_user.user_id, "処理を中止しました。", [], room_id=room_id
                        )
                        yield f"data: {json.dumps({'type': 'cancelled', 'session_id': room_id})}\n\n"
                        done_sent = True
                        result_saved = True
                        break

                    elif event["type"] == "reasoning":
                        text = event.get("text", "")
                        label = text
                        reasoning_steps.append(label)
                        if text.strip():
                            reasoning_full.append(text)
                        yield f"data: {json.dumps({'type': 'process', 'session_id': room_id, 'step': {'id': f'cli-{step_counter}', 'label': label, 'status': 'running'}})}\n\n"
                        step_counter += 1

                    elif event["type"] == "tool_use":
                        tool_label = _format_tool_label(event.get("name", ""), event.get("input", {}))
                        reasoning_steps.append(f"🛠 {tool_label}")
                        yield f"data: {json.dumps({'type': 'process', 'session_id': room_id, 'step': {'id': f'cli-{step_counter}', 'label': f'🛠 {tool_label}', 'status': 'running'}})}\n\n"
                        step_counter += 1

                    elif event["type"] == "text":
                        final_text = event["text"]
                        text_preview = event["text"].strip()
                        if text_preview and len(text_preview) > 10:
                            reasoning_steps.append(text_preview)
                            reasoning_full.append(text_preview)
                            yield f"data: {json.dumps({'type': 'process', 'session_id': room_id, 'step': {'id': f'cli-{step_counter}', 'label': text_preview, 'status': 'running'}})}\n\n"
                            step_counter += 1

                    elif event["type"] == "result":
                        result_text = event.get("text", "")
                        if result_text:
                            final_text = result_text
                        elif event.get("is_error"):
                            final_text = result_text

                    elif event["type"] == "error":
                        yield f"data: {json.dumps({'type': 'error', 'session_id': room_id, 'message': event['message']})}\n\n"

                if not result_saved:
                    ai_response_content = final_text or "応答の生成に失敗しました。"
                    ai_message_data = await service.send_dan_ai_message(
                        current_user.user_id,
                        ai_response_content,
                        reasoning_steps,
                        room_id=room_id,
                        reasoning_full=reasoning_full,
                    )
                    result_saved = True

                    if not ai_message_data:
                        raise ValueError("Failed to save AI message: returned None")

                    ai_message = {
                        "id": ai_message_data["id"],
                        "room_id": ai_message_data["room_id"],
                        "sender_id": ai_message_data.get("sender_id"),
                        "sender_name": "ダン",
                        "sender_type": "ai",
                        "content": ai_message_data["content"],
                        "created_at": ai_message_data["created_at"].isoformat() if hasattr(ai_message_data["created_at"], 'isoformat') else str(ai_message_data["created_at"]),
                    }
                    if ai_message_data.get("ai_context"):
                        ai_message["ai_context"] = ai_message_data["ai_context"]

                    yield f"data: {json.dumps({'type': 'ai_message', 'session_id': room_id, 'message': ai_message})}\n\n"
                    yield f"data: {json.dumps({'type': 'done', 'session_id': room_id})}\n\n"
                    done_sent = True
        except Exception as e:
            import logging
            import traceback
            logging.error(f"Failed to stream dan message: {e}\n{traceback.format_exc()}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            # CLI Runner 方式ではプロセスは別スレッドで完結しており、
            # SSE切断時には async for ループが自然に終了して result_saved が
            # 正常パスで設定される。ここでは UI の確実な停止だけ保証する。
            if not result_saved and room_id_for_cancel:
                # SSE切断等で正常パスを通れなかった場合のログ
                logger.info(
                    "[SSE-DISCONNECT] Stream ended without saving result (room=%s)",
                    room_id_for_cancel,
                )

            # done 未送信の場合のみ送信（フロントエンドのスピナー停止保証）
            if not done_sent:
                try:
                    yield f"data: {json.dumps({'type': 'done', 'session_id': room_id_for_cancel or ''})}\n\n"
                except Exception:
                    pass
            # クリーンアップ: リクエストIDとコールバックを解除
            ProgressCallbackRegistry.unregister(request_id)
            set_current_request_id(None)
            # キャンセルフラグを解除（CLIがまだ動いていたらスキップ → cli_runner.pyのfinally任せ）
            if room_id_for_cancel:
                from app.agent.cli_runner import is_cli_active
                if not is_cli_active(room_id_for_cancel):
                    CancellationRegistry.unregister(room_id_for_cancel)
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.post("/dan/read", response_model=ReadMarkResponse)
async def mark_dan_as_read(
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """ダンページを既読にする"""
    try:
        dan_room = await service.get_or_create_dan_room(current_user.user_id)
        success = await service.mark_as_read(dan_room["id"], current_user.user_id)
        return ReadMarkResponse(success=success, read_at=datetime.now(timezone.utc))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Session Routes ====================

@router.get("/dan/sessions", response_model=SessionsListResponse)
async def get_dan_sessions(
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    ダンのセッション一覧を取得
    
    - 全てのセッション（チャット履歴）を返す
    - 現在アクティブなセッションIDも含む
    """
    try:
        result = await service.get_dan_sessions(current_user.user_id)
        # heartbeatセッションを除外
        sessions = [
            s for s in result["sessions"]
            if not s["id"].startswith("heartbeat-")
        ]
        return SessionsListResponse(
            sessions=[SessionResponse(**s) for s in sessions],
            current_session_id=result["current_session_id"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dan/sessions", response_model=SessionCreateResponse)
async def create_dan_session(
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    新しいダンセッションを作成
    
    - 新規セッションを作成し、アクティブに設定
    - 既存のセッションは保持される
    """
    try:
        session = await service.create_dan_session(current_user.user_id)
        return SessionCreateResponse(**session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dan/sessions/{session_id}/activate", response_model=SessionActivateResponse)
async def activate_dan_session(
    session_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    セッションをアクティブにする（切り替え）
    
    - 指定したセッションをアクティブに設定
    - 次回の /dan/messages はこのセッションのメッセージを返す
    """
    try:
        result = await service.activate_dan_session(current_user.user_id, session_id)
        return SessionActivateResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Optimized Session Switch Route ====================

class SessionSwitchResponse(SessionActivateResponse):
    """セッション切り替えレスポンス（メッセージ含む）"""
    room: Optional[DanRoomResponse] = None
    messages: Optional[MessagesListResponse] = None


@router.post("/dan/sessions/{session_id}/switch")
async def switch_dan_session(
    session_id: str,
    limit: int = 50,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    セッションを切り替え、ルーム情報とメッセージを一度に取得（最適化版）
    
    - セッションをアクティブに設定
    - ルーム情報を取得
    - メッセージを取得
    - 1回のAPIコールで全データを返す
    """
    try:
        # セッションをアクティブ化
        result = await service.activate_dan_session(current_user.user_id, session_id)
        
        # ルーム情報を取得
        dan_room = await service.get_or_create_dan_room(current_user.user_id)
        
        # メッセージを取得
        messages = await service.get_messages(dan_room["id"], current_user.user_id, limit=limit)
        
        return {
            "success": result["success"],
            "session_id": result["session_id"],
            "room": dan_room,
            "messages": {"messages": [MessageResponse(**m) for m in messages]},
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/dan/sessions/{session_id}", response_model=SessionResponse)
async def update_dan_session(
    session_id: str,
    request: SessionUpdateRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """セッションのタイトルを更新"""
    try:
        result = await service.update_dan_session_title(
            current_user.user_id, 
            session_id, 
            request.title
        )
        # 完全なセッション情報を返すために再取得
        sessions = await service.get_dan_sessions(current_user.user_id)
        for s in sessions["sessions"]:
            if s["id"] == session_id:
                return SessionResponse(**s)
        return SessionResponse(
            id=result["id"],
            title=result["title"],
            message_count=0,
            created_at=datetime.now(timezone.utc),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/dan/sessions/{session_id}")
async def delete_dan_session(
    session_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    セッションを削除

    - アクティブなセッションを削除した場合、別のセッションに自動切り替え
    - 関連するメッセージも全て削除される
    - 実行中の処理とブラウザ操作もキャンセルされる
    """
    try:
        # キャンセル処理: 実行中のタスクとブラウザ操作を停止
        from app.services.cancellation import CancellationRegistry
        from app.tools.browser import abort_executor_session

        await _archive_session_summary(
            service=service,
            user_id=current_user.user_id,
            room_id=session_id,
            archive_type="delete",
            is_project=False,
            force=True,
        )

        CancellationRegistry.cancel(session_id)
        abort_executor_session()

        result = await service.delete_dan_session(current_user.user_id, session_id)
        return {
            "message": "Session deleted successfully",
            "new_active_session_id": result.get("new_active_session_id"),
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Cancel Route ====================

@router.get("/dan/sessions/{session_id}/execution-events")
async def get_session_execution_events(
    session_id: str,
    limit: int = 100,
    since_seq: Optional[int] = None,
    current_only: bool = False,
    current_user: TokenData = Depends(get_current_user),
):
    """
    セッション（room_id）の実行イベントを取得。

    since_seq を指定すると、そのseq番号より後のイベントのみ返す。
    current_only=True で最後のdoneイベント以降のみ返す（現在の実行分のみ）。
    フロントエンドのポーリング復帰時に差分取得に使う。
    """
    from app.services.project_service import ProjectService
    service = ProjectService()
    events = await service.get_execution_events_by_room(
        room_id=session_id,
        limit=limit,
        since_seq=since_seq,
        current_only=current_only,
    )
    return events


@router.get("/dan/sessions/{session_id}/active")
async def get_active_session_status(
    session_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    """
    セッションがバックエンドで実行中かどうかを返す。

    フロントエンドがページ読み込み時やタブ復帰時に呼び出し、
    実行中ならポーリングモードに切り替える。
    """
    from app.services.cancellation import CancellationRegistry
    from app.agent.cli_runner import is_cli_active

    info = CancellationRegistry.get_active_info(session_id)
    if info:
        return {
            "active": True,
            "session_id": session_id,
            "started_at": info["started_at"],
        }

    # Registry にないが CLI プロセスがまだ動いている場合
    if is_cli_active(session_id):
        return {
            "active": True,
            "session_id": session_id,
            "started_at": None,
        }

    return {
        "active": False,
        "session_id": session_id,
        "started_at": None,
    }


@router.post("/dan/cancel")
async def cancel_dan_session(
    request: CancelRequest,
    current_user: TokenData = Depends(get_current_user),
):
    """
    実行中のセッションをキャンセル

    - CancellationRegistryにキャンセルフラグをセット
    - ブラウザのコマンドキューをクリア
    - 実行中のツールは次のチェックポイントで停止
    """
    from app.services.cancellation import CancellationRegistry
    from app.tools.browser import abort_executor_session
    from app.agent.cli_runner import kill_cli_process

    success = CancellationRegistry.cancel(request.session_id)
    cli_killed = kill_cli_process(request.session_id)

    # ブラウザセッションも停止
    abort_executor_session()

    return {"success": success or cli_killed, "session_id": request.session_id}


# ==================== Proposal Routes (2G) ====================

@router.get("/proposals", response_model=ProposalsListResponse)
async def get_proposals(
    status: Optional[str] = None,
    limit: int = 50,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    ダンからの提案一覧を取得
    
    - status: フィルター（pending, approved, rejected, expired）
    - limit: 取得件数（デフォルト50）
    """
    try:
        proposals = await service.get_proposals(current_user.user_id, status=status, limit=limit)
        pending_count = await service.get_pending_proposals_count(current_user.user_id)
        return ProposalsListResponse(
            proposals=[ProposalResponse(**p) for p in proposals],
            total_count=len(proposals),
            pending_count=pending_count,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """提案の詳細を取得。.htmlファイルはHTMLとして直接サーブ"""
    if proposal_id.endswith(".html"):
        proposals_dir = Path("D:/dan-workspace/proposals")
        html_path = proposals_dir / proposal_id
        if html_path.exists() and html_path.is_file():
            return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
        raise HTTPException(status_code=404, detail="HTML file not found")
    proposal = await service.get_proposal(proposal_id, current_user.user_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return ProposalResponse(**proposal)


@router.post("/proposals/{proposal_id}/respond", response_model=ProposalResponse)
async def respond_to_proposal(
    proposal_id: str,
    request: ProposalActionRequest,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """
    提案に対応する
    
    - action: approve（承認）, reject（却下）, edit（編集して承認）
    - edited_content: action=editの場合、編集後の内容
    """
    try:
        proposal = await service.respond_to_proposal(
            proposal_id,
            current_user.user_id,
            request.action,
            request.edited_content,
        )
        return ProposalResponse(**proposal)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== WebSocket ====================

class ConnectionManager:
    """WebSocket接続マネージャー"""
    
    def __init__(self):
        # room_id -> {user_id -> WebSocket}
        self.active_connections: dict[str, dict[str, WebSocket]] = {}
    
    def add_connection(self, room_id: str, user_id: str, websocket: WebSocket):
        """WebSocket接続を追加する"""
        if room_id not in self.active_connections:
            self.active_connections[room_id] = {}
        self.active_connections[room_id][user_id] = websocket
    
    def disconnect(self, room_id: str, user_id: str):
        """WebSocket接続を解除する"""
        if room_id in self.active_connections:
            self.active_connections[room_id].pop(user_id, None)
            if not self.active_connections[room_id]:
                del self.active_connections[room_id]
    
    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """特定のWebSocketにメッセージを送信"""
        await websocket.send_json(message)

    def get_connection(self, room_id: str, user_id: str) -> Optional[WebSocket]:
        """指定ユーザーの接続を取得"""
        return self.active_connections.get(room_id, {}).get(user_id)

    def is_connected(self, room_id: str, user_id: str) -> bool:
        """ユーザーが接続中か確認"""
        return self.get_connection(room_id, user_id) is not None
    
    async def broadcast_to_room(self, room_id: str, message: dict, exclude_user_id: str = None):
        """ルーム内の全員にメッセージをブロードキャスト"""
        if room_id in self.active_connections:
            for user_id, connection in self.active_connections[room_id].items():
                if exclude_user_id and user_id == exclude_user_id:
                    continue
                try:
                    await connection.send_json(message)
                except Exception:
                    pass  # 接続が切れている場合は無視


# グローバルな接続マネージャー
manager = ConnectionManager()


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocketチャットエンドポイント
    
    接続時: { "type": "auth", "token": "JWT_TOKEN" }
    ルーム参加: { "type": "join", "room_id": "..." }
    メッセージ送信: { "type": "message", "room_id": "...", "content": "..." }
    退出: { "type": "leave", "room_id": "..." }
    """
    user_id = None
    current_room_id = None
    service = None
    
    try:
        # まず接続を受け入れる
        await websocket.accept()
        
        # サービスを初期化
        service = ChatService()
        
        # 認証を待つ
        auth_data = await websocket.receive_json()
        if auth_data.get("type") != "auth" or "token" not in auth_data:
            await websocket.send_json({"type": "error", "message": "Authentication required"})
            await websocket.close()
            return
        
        # トークン検証
        token_data = decode_access_token(auth_data["token"])
        if not token_data:
            await websocket.send_json({"type": "error", "message": "Invalid or expired token"})
            await websocket.close()
            return
        
        user_id = token_data.user_id
        await websocket.send_json({"type": "auth_success", "user_id": user_id})
        
        # メッセージループ
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            
            if msg_type == "join":
                # ルームに参加
                room_id = data.get("room_id")
                if not room_id:
                    await websocket.send_json({"type": "error", "message": "room_id required"})
                    continue
                
                # ルームメンバーか確認
                is_member = await service.is_room_member(room_id, user_id)
                if not is_member:
                    await websocket.send_json({"type": "error", "message": "Not a member of this room"})
                    continue
                
                # 以前のルームから退出
                if current_room_id:
                    manager.disconnect(current_room_id, user_id)
                
                # 新しいルームに参加
                current_room_id = room_id
                manager.add_connection(room_id, user_id, websocket)
                
                await websocket.send_json({"type": "joined", "room_id": room_id})
                
                # 他のメンバーに通知
                await manager.broadcast_to_room(
                    room_id,
                    {"type": "user_joined", "user_id": user_id, "room_id": room_id},
                    exclude_user_id=user_id
                )
            
            elif msg_type == "message":
                # メッセージ送信
                room_id = data.get("room_id") or current_room_id
                content = data.get("content")

                if not room_id or not content:
                    await websocket.send_json({"type": "error", "message": "room_id and content required"})
                    continue

                # メッセージをDBに保存
                try:
                    message = await service.send_message(room_id, user_id, content)

                    # ルーム内の全員にブロードキャスト
                    await manager.broadcast_to_room(
                        room_id,
                        {
                            "type": "new_message",
                            "message": {
                                "id": message["id"],
                                "room_id": message["room_id"],
                                "sender_id": message["sender_id"],
                                "sender_name": message["sender_name"],
                                "sender_type": message["sender_type"],
                                "content": message["content"],
                                "created_at": message["created_at"],
                            }
                        }
                    )
                except ValueError as e:
                    await websocket.send_json({"type": "error", "message": str(e)})
                except Exception as e:
                    await websocket.send_json({"type": "error", "message": f"Server error: {str(e)}"})
            
            elif msg_type == "leave":
                # ルームから退出
                room_id = data.get("room_id") or current_room_id
                if room_id:
                    manager.disconnect(room_id, user_id)
                    await manager.broadcast_to_room(
                        room_id,
                        {"type": "user_left", "user_id": user_id, "room_id": room_id}
                    )
                    if current_room_id == room_id:
                        current_room_id = None
                    await websocket.send_json({"type": "left", "room_id": room_id})
            
            elif msg_type == "ping":
                # キープアライブ
                await websocket.send_json({"type": "pong"})
    
    except WebSocketDisconnect:
        # 接続切断時の処理
        if current_room_id and user_id:
            manager.disconnect(current_room_id, user_id)
            await manager.broadcast_to_room(
                current_room_id,
                {"type": "user_left", "user_id": user_id, "room_id": current_room_id}
            )
    except Exception as e:
        # エラー時の処理
        if current_room_id and user_id:
            manager.disconnect(current_room_id, user_id)
