"""
Chat API Routes for Done Chat
"""
from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from datetime import datetime
import re
import json


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

from app.services.auth_service import decode_access_token, create_access_token, TokenData
from app.services.chat_service import ChatService
from app.models.chat_schemas import (
    # Auth
    RegisterRequest, LoginRequest, TokenResponse, UserResponse, UserUpdateRequest,
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
)

router = APIRouter(prefix="/chat", tags=["chat"])
security = HTTPBearer(auto_error=False)

# Base URL for invite links (should be configured in settings)
INVITE_BASE_URL = "https://done.app/i/"


def get_chat_service() -> ChatService:
    """Get ChatService instance"""
    return ChatService()


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> TokenData:
    """Get current authenticated user from JWT token"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    token_data = decode_access_token(credentials.credentials)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    return token_data


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[TokenData]:
    """Get current user if authenticated, None otherwise"""
    if not credentials:
        return None
    return decode_access_token(credentials.credentials)


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
    service: ChatService = Depends(get_chat_service),
):
    """Login and get JWT token"""
    user = await service.authenticate_user(request.email, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    access_token = create_access_token(user_id=user["id"], email=user["email"])
    return TokenResponse(access_token=access_token)


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
