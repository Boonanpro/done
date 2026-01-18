"""
Chat API Routes for Done Chat
Supports both Bearer token and HttpOnly Cookie authentication
"""
from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect, Response, Request, Cookie, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from datetime import datetime
import re
import json

from app.config import settings


def parse_datetime(dt_str: str) -> datetime:
    """Parse ISO format datetime string with variable microsecond precision"""
    if not dt_str:
        return None
    # Replace Z with +00:00 for timezone
    dt_str = dt_str.replace("Z", "+00:00")
    # Normalize microseconds to 6 digits (Python requires exactly 6)
    match = re.match(r"(.+\.\d{1,6})(\d*)(\+.*)?$", dt_str)
    if match:
        base, extra, tz = match.groups()
        # Pad to 6 digits if needed
        base_parts = base.rsplit(".", 1)
        if len(base_parts) == 2:
            microsec = base_parts[1].ljust(6, "0")[:6]
            dt_str = f"{base_parts[0]}.{microsec}{tz or ''}"
    return datetime.fromisoformat(dt_str)

from app.services.auth_service import (
    decode_access_token, decode_refresh_token, 
    create_access_token, create_token_pair, refresh_tokens,
    TokenData
)
from app.services.chat_service import ChatService
from app.models.chat_schemas import (
    # Auth
    RegisterRequest, LoginRequest, TokenResponse, TokenPairResponse, RefreshTokenRequest,
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
    ProcessStep, DanMessageResponse, SenderType,
    # AI
    AISettingsResponse, AISettingsUpdateRequest, AISummaryResponse,
    # Dan Page & Proposals (2E & 2G)
    DanRoomResponse, ProposalResponse, ProposalsListResponse, ProposalActionRequest,
    # Sessions
    SessionResponse, SessionsListResponse, SessionCreateResponse, 
    SessionActivateResponse, SessionUpdateRequest,
)

router = APIRouter(prefix="/chat", tags=["chat"])
security = HTTPBearer(auto_error=False)

# Cookie names
ACCESS_TOKEN_COOKIE = "done_access_token"
REFRESH_TOKEN_COOKIE = "done_refresh_token"


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
        if datetime.utcnow().replace(tzinfo=expires_at.tzinfo) > expires_at:
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


@router.post("/rooms/{room_id}/read", response_model=ReadMarkResponse)
async def mark_as_read(
    room_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """Mark messages as read"""
    from datetime import datetime
    success = await service.mark_as_read(room_id, current_user.user_id)
    return ReadMarkResponse(success=success, read_at=datetime.utcnow())


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
        ProgressUpdate
    )
    import uuid
    import asyncio
    
    # 挨拶キーワード
    GREETING_KEYWORDS = ["おはよう", "こんにちは", "こんばんは", "ありがとう", "おやすみ",
                         "hello", "hi", "thanks", "thank you", "good morning", "good night"]
    
    async def generate_stream():
        # リクエストIDを生成（プログレスコールバック用）
        request_id = str(uuid.uuid4())
        progress_queue = ProgressCallbackRegistry.create_queue(request_id)
        set_current_request_id(request_id)
        
        try:
            # Step 1: ユーザーメッセージを保存
            # session_idが指定されていればそのルームに、なければ現在のDanルームに送信
            if request.session_id:
                room_id = request.session_id
                message = await service.send_message(room_id, current_user.user_id, request.content, sender_type="human")
            else:
                message = await service.send_dan_message(current_user.user_id, request.content)
                room_id = message["room_id"]
            user = await service.get_user_by_id(current_user.user_id)

            # 最初のプロセスステップ（session_id付き）
            yield f"data: {json.dumps({'type': 'process', 'session_id': room_id, 'step': {'id': 'receive', 'label': '考え中...', 'status': 'running'}})}\n\n"

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
            
            # 挨拶かどうかをチェック
            content_lower = request.content.lower()
            is_greeting = any(kw in content_lower for kw in GREETING_KEYWORDS)

            # ========================================
            # Agent v2で処理
            # ========================================

            # 推論ステップを収集するためのリストとキュー
            reasoning_steps = []
            reasoning_queue = asyncio.Queue()

            # 推論ステップをキューに追加するコールバック
            async def on_reasoning_step(step: str):
                reasoning_steps.append(step)
                await reasoning_queue.put(step)

            # 挨拶の場合はシンプルに応答
            if is_greeting:
                yield f"data: {json.dumps({'type': 'process', 'session_id': room_id, 'step': {'id': 'greeting', 'label': '挨拶に応答します', 'status': 'completed'}})}\n\n"
                ai_response_content = "こんにちは！何かお手伝いできることはありますか？"
            else:
                # ========================================
                # Agent v2: Messages配列ベースのrunner
                # ========================================
                from app.agent.v2.runner import create_runner
                from app.executors.registry import register_all_executors

                # Executor登録
                register_all_executors()

                # Agent v2 Runner作成
                runner = await create_runner(
                    session_id=room_id,
                    user_id=current_user.user_id,
                    on_reasoning_step=on_reasoning_step,
                )

                # メッセージ処理をバックグラウンドで実行
                process_task = asyncio.create_task(runner.process_message(request.content))

                # キューを監視してSSEで送信
                step_counter = 0
                while not process_task.done():
                    try:
                        step = await asyncio.wait_for(reasoning_queue.get(), timeout=0.1)
                        yield f"data: {json.dumps({'type': 'process', 'session_id': room_id, 'step': {'id': f'reasoning-{step_counter}', 'label': step, 'status': 'running'}})}\n\n"
                        step_counter += 1
                    except asyncio.TimeoutError:
                        continue

                # 残りのステップを送信
                while not reasoning_queue.empty():
                    try:
                        step = reasoning_queue.get_nowait()
                        yield f"data: {json.dumps({'type': 'process', 'session_id': room_id, 'step': {'id': f'reasoning-{step_counter}', 'label': step, 'status': 'completed'}})}\n\n"
                        step_counter += 1
                    except asyncio.QueueEmpty:
                        break

                # 結果を取得
                result = await process_task

                # 応答を取得
                ai_response_content = result.get("response", "申し訳ありません。処理中にエラーが発生しました。")

                # ツール実行結果があれば通知
                if result.get("tool_results"):
                    for tr in result["tool_results"]:
                        tool_info = f"{tr['tool']['skill']} {tr['tool']['action']}"
                        success = tr['result'].get('success', False)
                        yield f"data: {json.dumps({'type': 'process', 'session_id': room_id, 'step': {'id': f'tool-{tool_info}', 'label': f'ツール実行: {tool_info}', 'status': 'completed' if success else 'error'}})}\n\n"

                # エラーがあれば通知
                if result.get("error"):
                    yield f"data: {json.dumps({'type': 'error', 'session_id': room_id, 'message': result['error']})}\n\n"
            
            # DBに保存（指定されたroom_idを使用）
            ai_message_data = await service.send_dan_ai_message(current_user.user_id, ai_response_content, reasoning_steps, room_id=room_id)

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
            
            # 完了（session_id付き）
            yield f"data: {json.dumps({'type': 'process', 'session_id': room_id, 'step': {'id': 'propose', 'label': '回答を作成しました', 'status': 'completed'}})}\n\n"
            yield f"data: {json.dumps({'type': 'ai_message', 'session_id': room_id, 'message': ai_message})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'session_id': room_id})}\n\n"
            
        except Exception as e:
            import logging
            import traceback
            logging.error(f"Failed to stream dan message: {e}\n{traceback.format_exc()}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            # クリーンアップ: リクエストIDとコールバックを解除
            ProgressCallbackRegistry.unregister(request_id)
            set_current_request_id(None)
    
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
        return ReadMarkResponse(success=success, read_at=datetime.utcnow())
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
        return SessionsListResponse(
            sessions=[SessionResponse(**s) for s in result["sessions"]],
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
            created_at=datetime.utcnow(),
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
    """
    try:
        result = await service.delete_dan_session(current_user.user_id, session_id)
        return {
            "message": "Session deleted successfully",
            "new_active_session_id": result.get("new_active_session_id"),
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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


@router.get("/proposals/{proposal_id}", response_model=ProposalResponse)
async def get_proposal(
    proposal_id: str,
    current_user: TokenData = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
):
    """提案の詳細を取得"""
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
