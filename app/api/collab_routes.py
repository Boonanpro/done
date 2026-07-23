"""
Collaboration Room API Routes
Supports owner auth (JWT) and guest auth (invite-based JWT)
"""
from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect, Request, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from datetime import datetime, timedelta, timezone
import json
import logging
import uuid
import os
from pathlib import Path

from app.config import settings
from app.services.auth_service import decode_access_token, TokenData
from app.services.collab_service import CollabService
from app.models.collab_schemas import (
    CollabRoomCreateRequest, CollabRoomUpdateRequest, CollabRoomResponse, CollabRoomListResponse,
    CollabInviteCreateRequest, CollabInviteResponse,
    CollabJoinRequest, CollabJoinResponse,
    CollabMessageSendRequest, CollabMessageResponse, CollabMessageListResponse,
    CollabFileResponse, CollabFileListResponse,
    GenerateReplyRequest,
)
from jose import jwt as jose_jwt

router = APIRouter(prefix="/collab", tags=["collab"])
security = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)

ACCESS_TOKEN_COOKIE = "done_access_token"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
from app.workspace import resolve_cli_workspace
CLI_WORKSPACE = resolve_cli_workspace()
UPLOAD_DIR = PROJECT_ROOT / "uploads" / "collab"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def get_collab_service() -> CollabService:
    return CollabService()


async def _get_display_name(user_id: str, fallback_email: str) -> str:
    """Get user's display_name from DB, fallback to email prefix."""
    try:
        from app.services.supabase_client import get_supabase_client
        client = get_supabase_client().client
        result = client.table("users").select("display_name").eq("id", user_id).limit(1).execute()
        if result.data and result.data[0].get("display_name"):
            return result.data[0]["display_name"]
    except Exception:
        pass
    return fallback_email.split("@")[0]


def _get_jwt_secret() -> str:
    return settings.JWT_SECRET_KEY or settings.APP_SECRET_KEY


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> TokenData:
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token and credentials:
        token = credentials.credentials
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token_data = decode_access_token(token)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return token_data


def _create_guest_token(invite_id: str, room_id: str, guest_name: str, role: str) -> str:
    """Create a lightweight JWT for guest access."""
    expire = datetime.now(timezone.utc) + timedelta(hours=72)
    payload = {
        "sub": invite_id,
        "room_id": room_id,
        "guest_name": guest_name,
        "role": role,
        "type": "guest",
        "exp": expire,
    }
    return jose_jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")


def _decode_guest_token(token: str) -> Optional[dict]:
    """Decode a guest JWT token."""
    try:
        payload = jose_jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])
        if payload.get("type") != "guest":
            return None
        return payload
    except Exception:
        return None


def _get_guest_token_from_request(request: Request, credentials=None) -> Optional[str]:
    """Extract guest token from header or cookie."""
    # Check X-Guest-Token header first
    guest_token = request.headers.get("X-Guest-Token")
    if guest_token:
        return guest_token
    # Fallback to Bearer
    if credentials and credentials.credentials:
        return credentials.credentials
    return None


# ==================== Room CRUD ====================

@router.post("/rooms", response_model=CollabRoomResponse)
async def create_room(
    req: CollabRoomCreateRequest,
    user: TokenData = Depends(get_current_user),
    service: CollabService = Depends(get_collab_service),
):
    room = await service.create_room(
        owner_id=user.user_id,
        title=req.title,
        description=req.description,
        project_ref=req.project_ref,
        ai_auto_assist=req.ai_auto_assist,
        ai_assist_config=req.ai_assist_config.model_dump() if req.ai_assist_config else None,
    )
    return CollabRoomResponse(**room, guest_count=0)


@router.get("/rooms", response_model=CollabRoomListResponse)
async def list_rooms(
    user: TokenData = Depends(get_current_user),
    service: CollabService = Depends(get_collab_service),
):
    # Owner's rooms
    rooms = await service.list_rooms(user.user_id)
    # Also include rooms where user is a guest
    guest_rooms = await service.list_guest_rooms(user.user_id)

    room_responses = []
    seen_ids = set()
    for r in rooms + guest_rooms:
        if r["id"] in seen_ids:
            continue
        seen_ids.add(r["id"])
        # Get guest count
        invites = await service.list_invites(r["id"])
        guest_count = sum(1 for i in invites if i["status"] == "joined")
        # Get last message
        messages = await service.get_messages(r["id"], limit=1)
        last_msg = messages[-1] if messages else None
        room_responses.append(CollabRoomResponse(
            **r,
            guest_count=guest_count,
            last_message=last_msg["content"][:100] if last_msg else None,
            last_message_at=last_msg["created_at"] if last_msg else None,
        ))
    return CollabRoomListResponse(rooms=room_responses)


@router.get("/rooms/{room_id}", response_model=CollabRoomResponse)
async def get_room(
    room_id: str,
    user: TokenData = Depends(get_current_user),
    service: CollabService = Depends(get_collab_service),
):
    room = await service.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    # Allow owner or linked guest user
    is_owner = room["owner_id"] == user.user_id
    guest_rooms = await service.list_guest_rooms(user.user_id) if not is_owner else []
    is_guest = any(gr["id"] == room_id for gr in guest_rooms)
    if not is_owner and not is_guest:
        raise HTTPException(status_code=404, detail="Room not found")
    invites = await service.list_invites(room_id)
    guest_count = sum(1 for i in invites if i["status"] == "joined")
    return CollabRoomResponse(**room, guest_count=guest_count)


@router.patch("/rooms/{room_id}", response_model=CollabRoomResponse)
async def update_room(
    room_id: str,
    req: CollabRoomUpdateRequest,
    user: TokenData = Depends(get_current_user),
    service: CollabService = Depends(get_collab_service),
):
    updates = req.model_dump(exclude_none=True)
    if "ai_assist_config" in updates and updates["ai_assist_config"]:
        updates["ai_assist_config"] = updates["ai_assist_config"]
    room = await service.update_room(room_id, user.user_id, updates)
    return CollabRoomResponse(**room, guest_count=0)


@router.delete("/rooms/{room_id}")
async def delete_room(
    room_id: str,
    user: TokenData = Depends(get_current_user),
    service: CollabService = Depends(get_collab_service),
):
    room = await service.get_room(room_id)
    if not room or room["owner_id"] != user.user_id:
        raise HTTPException(status_code=404, detail="Room not found")
    await service.delete_room(room_id)
    return {"success": True}


# ==================== Invites ====================

@router.post("/rooms/{room_id}/invites", response_model=CollabInviteResponse)
async def create_invite(
    room_id: str,
    req: CollabInviteCreateRequest,
    request: Request,
    user: TokenData = Depends(get_current_user),
    service: CollabService = Depends(get_collab_service),
):
    invite = await service.create_invite(
        room_id=room_id,
        user_id=user.user_id,
        role=req.role.value,
        expires_hours=req.expires_hours,
    )
    # Build invite URL
    from app.config import settings as app_settings
    frontend_url = (app_settings.FRONTEND_URL or "http://localhost:3000").rstrip("/")
    invite_url = f"{frontend_url}/collab/join/{invite['token']}"
    return CollabInviteResponse(**invite, invite_url=invite_url)


@router.get("/rooms/{room_id}/invites")
async def list_invites(
    room_id: str,
    user: TokenData = Depends(get_current_user),
    service: CollabService = Depends(get_collab_service),
):
    room = await service.get_room(room_id)
    if not room or room["owner_id"] != user.user_id:
        raise HTTPException(status_code=404, detail="Room not found")
    invites = await service.list_invites(room_id)
    return {"invites": invites}


# ==================== Guest Join (No auth required) ====================

@router.get("/join/{token}")
async def get_invite_info(
    token: str,
    service: CollabService = Depends(get_collab_service),
):
    """Get invite info for the join page (no auth required)."""
    invite = await service.get_invite_by_token(token)
    if not invite:
        raise HTTPException(status_code=404, detail="Invalid invite link")

    room = invite.get("collab_rooms")
    from app.services.chat_service import parse_datetime
    expires_at = parse_datetime(invite["expires_at"])
    is_expired = datetime.now(timezone.utc) > expires_at or invite["status"] == "expired"

    result = {
        "room_title": room["title"] if room else "Unknown",
        "room_description": room.get("description") if room else None,
        "role": invite["role"],
        "status": "expired" if is_expired else invite["status"],
        "already_joined": invite["status"] == "joined",
        "guest_name": invite.get("guest_name"),
    }

    # If already joined, include rejoin info so the guest can re-enter directly
    if invite["status"] == "joined" and invite.get("guest_name"):
        rejoin_jwt = _create_guest_token(
            invite_id=invite["id"],
            room_id=invite["room_id"],
            guest_name=invite["guest_name"],
            role=invite["role"],
        )
        result["rejoin_token"] = rejoin_jwt
        result["room_id"] = invite["room_id"]

    return result


@router.post("/join/{token}", response_model=CollabJoinResponse)
async def join_room(
    token: str,
    req: CollabJoinRequest,
    service: CollabService = Depends(get_collab_service),
):
    """Guest joins a collab room via invite token. No auth required."""
    invite = await service.get_invite_by_token(token)
    if not invite:
        raise HTTPException(status_code=404, detail="Invalid invite link")

    guest_jwt = _create_guest_token(
        invite_id=invite["id"],
        room_id=invite["room_id"],
        guest_name=req.guest_name,
        role=invite["role"],
    )

    result = await service.join_room(token, req.guest_name, guest_jwt)
    return CollabJoinResponse(guest_token=guest_jwt, **result)


# ==================== Messages ====================

@router.get("/rooms/{room_id}/messages", response_model=CollabMessageListResponse)
async def get_messages(
    room_id: str,
    limit: int = 50,
    before: Optional[str] = None,
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    service: CollabService = Depends(get_collab_service),
):
    # Verify access (owner or guest)
    owner_token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not owner_token and credentials:
        owner_token = credentials.credentials

    has_access = False
    if owner_token:
        # Try as owner
        token_data = decode_access_token(owner_token)
        if token_data:
            has_access = await service.verify_room_access(room_id, user_id=token_data.user_id)
        # Try as guest
        if not has_access:
            guest_data = _decode_guest_token(owner_token)
            if guest_data and guest_data.get("room_id") == room_id:
                has_access = True

    # Also check X-Guest-Token header
    if not has_access:
        guest_token = request.headers.get("X-Guest-Token")
        if guest_token:
            guest_data = _decode_guest_token(guest_token)
            if guest_data and guest_data.get("room_id") == room_id:
                has_access = True

    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied")

    # Determine if requester is owner or guest
    is_owner = False
    if owner_token:
        td = decode_access_token(owner_token)
        if td:
            room = await service.get_room(room_id)
            if room and room["owner_id"] == td.user_id:
                is_owner = True

    messages = await service.get_messages(room_id, limit=limit, before=before)

    # Filter visibility: each side only sees their own private messages
    if is_owner:
        messages = [m for m in messages
                    if m.get("metadata", {}).get("visibility") != "guest_only"]
    else:
        messages = [m for m in messages
                    if m.get("metadata", {}).get("visibility") != "owner_only"]

    return CollabMessageListResponse(
        messages=[CollabMessageResponse(**m) for m in messages]
    )


@router.post("/rooms/{room_id}/messages", response_model=CollabMessageResponse)
async def send_message(
    room_id: str,
    req: CollabMessageSendRequest,
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    service: CollabService = Depends(get_collab_service),
):
    # Determine sender
    sender_type = None
    sender_name = None

    # Try owner auth
    owner_token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not owner_token and credentials:
        owner_token = credentials.credentials

    if owner_token:
        token_data = decode_access_token(owner_token)
        if token_data:
            room = await service.get_room(room_id)
            if room and room["owner_id"] == token_data.user_id:
                sender_type = "owner"
                sender_name = await _get_display_name(token_data.user_id, token_data.email)

    # Try guest auth
    if not sender_type:
        guest_token = _get_guest_token_from_request(request, credentials)
        if guest_token:
            guest_data = _decode_guest_token(guest_token)
            if guest_data and guest_data.get("room_id") == room_id:
                sender_type = "guest"
                sender_name = guest_data.get("guest_name", "Guest")

    if not sender_type:
        raise HTTPException(status_code=403, detail="Access denied")

    message = await service.send_message(
        room_id=room_id,
        sender_type=sender_type,
        sender_name=sender_name,
        content=req.content,
        metadata=req.metadata,
    )

    # Real-time notification via WebSocket
    import asyncio
    asyncio.ensure_future(notification_manager.notify_room_users(
        room_id,
        {"type": "new_message_notification", "room_id": room_id,
         "room_title": ((await service.get_room(room_id)) or {}).get("title", ""),
         "sender_name": sender_name, "content": req.content[:100]},
        service
    ))

    # Trigger DAN assist for guest messages (REST API path)
    if sender_type == "guest":
        import asyncio
        asyncio.ensure_future(
            _trigger_dan_assist(service, room_id, message)
        )

    return CollabMessageResponse(**message)


# ==================== Generate Reply ====================

@router.post("/rooms/{room_id}/generate-reply")
async def generate_reply(
    room_id: str,
    req: GenerateReplyRequest,
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    service: CollabService = Depends(get_collab_service),
):
    """Generate a reply suggestion for a guest message on demand."""
    user = await get_current_user(request, credentials)

    room = await service.get_room(room_id)
    if not room or room["owner_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    target_message_id = req.message_id
    target_content = req.content

    # Get recent messages for context
    recent = await service.get_messages(room_id, limit=20)
    owner_name = await _get_display_name(room["owner_id"], "オーナー")

    history_lines = []
    for msg in recent:
        st = msg.get("sender_type", "?")
        sn = msg.get("sender_name", "?")
        c = msg.get("content", "")
        if st == "owner":
            history_lines.append(f"【オーナー({sn})】{c}")
        elif st == "guest":
            history_lines.append(f"【ゲスト({sn})】{c}")
        elif st.startswith("dan_"):
            history_lines.append(f"【DAN】{c}")
    history_text = "\n".join(history_lines)

    # Generate reply using CLI runner
    from app.agent.cli_runner import process_message_cli

    prompt = (
        f"あなたはコラボルーム内でオーナー（{owner_name}）の代わりに返信文を作成します。\n\n"
        f"## ルーム情報\n"
        f"- タイトル: {room['title']}\n"
        f"- 説明: {room.get('description') or '(なし)'}\n\n"
        f"## 会話履歴\n{history_text}\n\n"
        f"## 返信対象メッセージ\n{target_content}\n\n"
        f"## 指示\n"
        f"このメッセージに対する返信文を1つだけ生成してください。\n"
        f"- オーナーの口調で自然な返信を書く\n"
        f"- 返信文のみを出力（説明・前置き不要）\n"
        f"- 簡潔に（長くても3行以内）"
    )

    collab_dan_room_id = f"collab_reply_{room_id}"
    final_text = ""

    async for event in process_message_cli(
        room_id=collab_dan_room_id,
        user_id=room["owner_id"],
        content=prompt,
        system_prompt=(
            f"あなたはオーナー（{owner_name}）の代筆者です。"
            f"ゲストへの返信文を生成してください。返信文のみを出力し、それ以外は何も書かないでください。"
        ),
        skip_resume=True,
        cwd=str(CLI_WORKSPACE),
    ):
        if event["type"] == "text":
            final_text += event.get("text", "")
        elif event["type"] == "result":
            if event.get("text"):
                final_text = event["text"]
        elif event["type"] == "error":
            raise HTTPException(status_code=500, detail=event.get("message", "Generation failed"))

    final_text = final_text.strip()
    # Remove surrounding quotes if present
    if final_text.startswith("「") and final_text.endswith("」"):
        final_text = final_text[1:-1]

    return {"reply": final_text, "message_id": target_message_id}


@router.post("/rooms/{room_id}/generate-reply-guest")
async def generate_reply_guest(
    room_id: str,
    req: GenerateReplyRequest,
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    service: CollabService = Depends(get_collab_service),
):
    """Generate a reply suggestion for a guest (lightweight, no tools)."""
    guest_token = _get_guest_token_from_request(request, credentials)
    if not guest_token:
        raise HTTPException(status_code=401, detail="Guest token required")
    guest_data = _decode_guest_token(guest_token)
    if not guest_data or guest_data.get("room_id") != room_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    room = await service.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    guest_name = guest_data.get("guest_name", "ゲスト")
    target_content = req.content

    # Get recent messages for context
    recent = await service.get_messages(room_id, limit=20)

    history_lines = []
    for msg in recent:
        st = msg.get("sender_type", "?")
        sn = msg.get("sender_name", "?")
        c = msg.get("content", "")
        if st == "owner":
            history_lines.append(f"【オーナー({sn})】{c}")
        elif st == "guest":
            history_lines.append(f"【ゲスト({sn})】{c}")
    history_text = "\n".join(history_lines)

    # Use lightweight LLM (same as guest DAN assist)
    from app.services.collab_dan_service import _try_anthropic, _try_gemini

    system = (
        f"あなたはゲスト（{guest_name}）の代筆者です。"
        f"オーナーへの返信文を生成してください。返信文のみを出力し、それ以外は何も書かないでください。"
    )
    user_prompt = (
        f"## ルーム情報\n"
        f"- タイトル: {room['title']}\n"
        f"- 説明: {room.get('description') or '(なし)'}\n\n"
        f"## 会話履歴\n{history_text}\n\n"
        f"## 返信対象メッセージ\n{target_content}\n\n"
        f"## 指示\n"
        f"このメッセージに対する返信文を1つだけ生成してください。\n"
        f"- {guest_name}の口調で自然な返信を書く\n"
        f"- 返信文のみを出力（説明・前置き不要）\n"
        f"- 簡潔に（長くても3行以内）"
    )

    result = _try_anthropic(system, user_prompt) or _try_gemini(system, user_prompt)
    if not result:
        raise HTTPException(status_code=500, detail="Reply generation failed")

    result = result.strip()
    if result.startswith("「") and result.endswith("」"):
        result = result[1:-1]

    return {"reply": result, "message_id": req.message_id}


# ==================== Files ====================

@router.post("/rooms/{room_id}/files", response_model=CollabFileResponse)
async def upload_file(
    room_id: str,
    file: UploadFile = File(...),
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    service: CollabService = Depends(get_collab_service),
):
    # Determine uploader
    uploaded_by = None

    owner_token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not owner_token and credentials:
        owner_token = credentials.credentials

    if owner_token:
        token_data = decode_access_token(owner_token)
        if token_data:
            room = await service.get_room(room_id)
            if room and room["owner_id"] == token_data.user_id:
                uploaded_by = "owner"

    if not uploaded_by:
        guest_token = _get_guest_token_from_request(request, credentials)
        if guest_token:
            guest_data = _decode_guest_token(guest_token)
            if guest_data and guest_data.get("room_id") == room_id:
                uploaded_by = "guest"

    if not uploaded_by:
        raise HTTPException(status_code=403, detail="Access denied")

    # Save file
    room_dir = UPLOAD_DIR / room_id
    room_dir.mkdir(parents=True, exist_ok=True)

    ext = os.path.splitext(file.filename)[1] if file.filename else ""
    saved_name = f"{uuid.uuid4()}{ext}"
    file_path = room_dir / saved_name

    content = await file.read()
    if len(content) > 100 * 1024 * 1024:  # 100MB limit
        raise HTTPException(status_code=413, detail="File too large (max 100MB)")

    with open(file_path, "wb") as f:
        f.write(content)

    record = await service.save_file_record(
        room_id=room_id,
        uploaded_by=uploaded_by,
        file_name=file.filename or saved_name,
        file_path=f"/api/v1/collab/files/{room_id}/{saved_name}",
        file_type=file.content_type,
        file_size=len(content),
    )
    return CollabFileResponse(**record)


@router.get("/rooms/{room_id}/files", response_model=CollabFileListResponse)
async def list_files(
    room_id: str,
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    service: CollabService = Depends(get_collab_service),
):
    # Access check (simplified - similar to messages)
    has_access = False
    owner_token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not owner_token and credentials:
        owner_token = credentials.credentials
    if owner_token:
        token_data = decode_access_token(owner_token)
        if token_data:
            has_access = await service.verify_room_access(room_id, user_id=token_data.user_id)
    if not has_access:
        guest_token = request.headers.get("X-Guest-Token")
        if guest_token:
            guest_data = _decode_guest_token(guest_token)
            if guest_data and guest_data.get("room_id") == room_id:
                has_access = True
    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied")

    files = await service.get_files(room_id)
    return CollabFileListResponse(files=[CollabFileResponse(**f) for f in files])


from fastapi.responses import FileResponse

@router.get("/files/{room_id}/{filename}")
async def serve_file(room_id: str, filename: str):
    """Serve uploaded collab files."""
    file_path = UPLOAD_DIR / room_id / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    # Prevent path traversal
    if not file_path.resolve().is_relative_to(UPLOAD_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Invalid path")
    return FileResponse(file_path)


# ==================== WebSocket ====================

class CollabConnectionManager:
    """WebSocket connection manager for collab rooms."""

    def __init__(self):
        # room_id -> list of {ws, sender_type, sender_name}
        self.connections: dict[str, list[dict]] = {}

    def add(self, room_id: str, ws: WebSocket, sender_type: str, sender_name: str):
        if room_id not in self.connections:
            self.connections[room_id] = []
        # Remove stale connections from the same user (reconnect case)
        self.connections[room_id] = [
            c for c in self.connections[room_id]
            if not (c["sender_type"] == sender_type and c["sender_name"] == sender_name)
        ]
        self.connections[room_id].append({
            "ws": ws, "sender_type": sender_type, "sender_name": sender_name
        })

    def remove(self, room_id: str, ws: WebSocket):
        if room_id in self.connections:
            self.connections[room_id] = [c for c in self.connections[room_id] if c["ws"] != ws]
            if not self.connections[room_id]:
                del self.connections[room_id]

    async def broadcast(self, room_id: str, message: dict, exclude_ws: WebSocket = None):
        if room_id not in self.connections:
            return
        for conn in self.connections[room_id]:
            if conn["ws"] != exclude_ws:
                try:
                    await conn["ws"].send_json(message)
                except Exception:
                    pass

    async def send_to_type(self, room_id: str, sender_type: str, message: dict):
        """Send message only to connections of a specific sender_type (e.g. 'owner')."""
        if room_id not in self.connections:
            return
        for conn in self.connections[room_id]:
            if conn["sender_type"] == sender_type:
                try:
                    await conn["ws"].send_json(message)
                except Exception:
                    pass

    def get_online_users(self, room_id: str) -> list[dict]:
        if room_id not in self.connections:
            return []
        return [{"sender_type": c["sender_type"], "sender_name": c["sender_name"]}
                for c in self.connections[room_id]]


collab_manager = CollabConnectionManager()


class NotificationManager:
    """Manages per-user WebSocket connections for cross-room notifications."""

    def __init__(self):
        # user_id -> list of WebSocket
        self.connections: dict[str, list[WebSocket]] = {}

    def add(self, user_id: str, ws: WebSocket):
        if user_id not in self.connections:
            self.connections[user_id] = []
        self.connections[user_id].append(ws)

    def remove(self, user_id: str, ws: WebSocket):
        if user_id in self.connections:
            self.connections[user_id] = [c for c in self.connections[user_id] if c != ws]
            if not self.connections[user_id]:
                del self.connections[user_id]

    async def notify_room_users(self, room_id: str, message: dict, service: CollabService):
        """Notify all users who are part of a room (owner + linked guests)."""
        room = await service.get_room(room_id)
        if not room:
            return
        user_ids = set()
        # Owner
        user_ids.add(room["owner_id"])
        # Linked guest users
        invites = await service.list_invites(room_id)
        for inv in invites:
            if inv.get("user_id") and inv["status"] == "joined":
                user_ids.add(inv["user_id"])

        for uid in user_ids:
            if uid in self.connections:
                for ws in self.connections[uid]:
                    try:
                        await ws.send_json(message)
                    except Exception:
                        pass


notification_manager = NotificationManager()


@router.websocket("/ws/notifications")
async def notification_websocket(websocket: WebSocket):
    """Per-user WebSocket for real-time cross-room notifications."""
    await websocket.accept()
    user_id = None

    try:
        # Wait for auth
        auth_data = await websocket.receive_json()
        token = auth_data.get("token")
        if not token:
            await websocket.send_json({"type": "error", "message": "Token required"})
            await websocket.close()
            return

        token_data = decode_access_token(token)
        if not token_data:
            await websocket.send_json({"type": "error", "message": "Invalid token"})
            await websocket.close()
            return

        user_id = token_data.user_id
        notification_manager.add(user_id, websocket)
        await websocket.send_json({"type": "auth_success"})

        # Keep connection alive
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if user_id:
            notification_manager.remove(user_id, websocket)


@router.websocket("/ws/{room_id}")
async def collab_websocket(websocket: WebSocket, room_id: str):
    """
    WebSocket for real-time collab chat.

    Auth flow:
    1. Client sends: {"type": "auth", "token": "JWT"} (owner)
       OR: {"type": "auth_guest", "token": "GUEST_JWT"} (guest)
    2. Server validates and adds to room
    3. Messages: {"type": "message", "content": "..."}
    4. Typing: {"type": "typing"}
    """
    await websocket.accept()
    service = CollabService()
    sender_type = None
    sender_name = None

    try:
        # Wait for auth
        auth_data = await websocket.receive_json()
        auth_type = auth_data.get("type")
        token = auth_data.get("token")

        if auth_type == "auth" and token:
            # Authenticated user (owner or linked guest)
            token_data = decode_access_token(token)
            if not token_data:
                await websocket.send_json({"type": "error", "message": "Invalid token"})
                await websocket.close()
                return
            has_access = await service.verify_room_access(room_id, user_id=token_data.user_id)
            if not has_access:
                await websocket.send_json({"type": "error", "message": "Not authorized"})
                await websocket.close()
                return
            room = await service.get_room(room_id)
            if room and room["owner_id"] == token_data.user_id:
                sender_type = "owner"
            else:
                sender_type = "guest"
            sender_name = await _get_display_name(token_data.user_id, token_data.email)

        elif auth_type == "auth_guest" and token:
            # Guest auth
            guest_data = _decode_guest_token(token)
            if not guest_data or guest_data.get("room_id") != room_id:
                await websocket.send_json({"type": "error", "message": "Invalid guest token"})
                await websocket.close()
                return
            sender_type = "guest"
            sender_name = guest_data.get("guest_name", "Guest")

        else:
            await websocket.send_json({"type": "error", "message": "Auth required"})
            await websocket.close()
            return

        # Add to room
        collab_manager.add(room_id, websocket, sender_type, sender_name)
        online = collab_manager.get_online_users(room_id)
        await websocket.send_json({
            "type": "auth_success",
            "sender_type": sender_type,
            "sender_name": sender_name,
            "online_users": online,
        })

        # Notify others
        await collab_manager.broadcast(room_id, {
            "type": "user_joined",
            "sender_type": sender_type,
            "sender_name": sender_name,
            "online_users": online,
        }, exclude_ws=websocket)

        # Message loop
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "message":
                content = data.get("content", "").strip()
                if not content:
                    continue
                metadata = data.get("metadata") or {}

                # Check for @ダン mention (private message to DAN, both owner and guest)
                import re
                is_dan_mention = bool(re.match(r'^@[ダだ][ンん]\s*', content))

                if is_dan_mention:
                    dan_content = re.sub(r'^@[ダだ][ンん]\s*', '', content).strip()
                    if not dan_content:
                        continue

                    # Determine visibility: owner sees owner's DAN, guest sees guest's DAN
                    visibility = "owner_only" if sender_type == "owner" else "guest_only"
                    dan_type = "dan_owner" if sender_type == "owner" else "dan_guest"

                    # Save as private message
                    message = await service.send_message(
                        room_id=room_id,
                        sender_type=sender_type,
                        sender_name=sender_name,
                        content=content,
                        metadata={**metadata, "visibility": visibility},
                    )
                    # Send only to the sender's side
                    await collab_manager.send_to_type(room_id, sender_type, {
                        "type": "new_message",
                        "message": {
                            "id": message["id"],
                            "room_id": room_id,
                            "sender_type": message["sender_type"],
                            "sender_name": message["sender_name"],
                            "content": message["content"],
                            "metadata": message.get("metadata", {}),
                            "created_at": message["created_at"],
                        }
                    })

                    if sender_type == "owner":
                        # Owner: trigger full DAN agent
                        import asyncio
                        asyncio.ensure_future(
                            _trigger_dan_assist(service, room_id, {
                                **message,
                                "content": dan_content,
                                "sender_type": "owner",
                                "sender_name": sender_name,
                                "_owner_instruction": True,
                            })
                        )
                    else:
                        # Guest: trigger lightweight DAN
                        import asyncio
                        asyncio.ensure_future(
                            _trigger_guest_dan_assist(service, room_id, {
                                **message,
                                "content": dan_content,
                                "sender_type": "guest",
                                "sender_name": sender_name,
                            })
                        )
                else:
                    # Normal message - visible to all
                    message = await service.send_message(
                        room_id=room_id,
                        sender_type=sender_type,
                        sender_name=sender_name,
                        content=content,
                        metadata=metadata,
                    )
                    msg_payload = {
                        "type": "new_message",
                        "message": {
                            "id": message["id"],
                            "room_id": room_id,
                            "sender_type": message["sender_type"],
                            "sender_name": message["sender_name"],
                            "content": message["content"],
                            "metadata": message.get("metadata", {}),
                            "created_at": message["created_at"],
                        }
                    }
                    await collab_manager.broadcast(room_id, msg_payload)

                    # Real-time notification to all room users
                    import asyncio
                    asyncio.ensure_future(notification_manager.notify_room_users(
                        room_id,
                        {"type": "new_message_notification", "room_id": room_id,
                         "room_title": (await service.get_room(room_id) or {}).get("title", ""),
                         "sender_name": sender_name, "content": content[:100]},
                        service
                    ))

                    # Push notification to the other side
                    asyncio.ensure_future(_send_push(
                        room_id, sender_type, sender_name, content
                    ))

                    # DAN auto-assist: trigger when guest sends a message
                    if sender_type == "guest":
                        import asyncio
                        asyncio.ensure_future(
                            _trigger_dan_assist(service, room_id, message)
                        )

            elif msg_type == "typing":
                await collab_manager.broadcast(room_id, {
                    "type": "typing",
                    "sender_type": sender_type,
                    "sender_name": sender_name,
                }, exclude_ws=websocket)

            elif msg_type == "read":
                # Broadcast read receipt to others
                await collab_manager.broadcast(room_id, {
                    "type": "read",
                    "sender_type": sender_type,
                    "sender_name": sender_name,
                    "message_id": data.get("message_id"),
                }, exclude_ws=websocket)

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        collab_manager.remove(room_id, websocket)
        if sender_type:
            await collab_manager.broadcast(room_id, {
                "type": "user_left",
                "sender_type": sender_type,
                "sender_name": sender_name,
                "online_users": collab_manager.get_online_users(room_id),
            })


async def _trigger_dan_assist(service: CollabService, room_id: str, trigger_message: dict):
    """Run full DAN agent in background when auto-assist is enabled or owner mentions @ダン."""
    try:
        is_owner_instruction = trigger_message.get("_owner_instruction", False)
        room = await service.get_room(room_id)

        # For guest messages, check auto-assist setting + skip filter
        if not is_owner_instruction:
            if not room or not room.get("ai_auto_assist"):
                return
            from app.services.collab_dan_service import _should_skip
            content = trigger_message.get("content", "").strip()
            if _should_skip(content):
                return
        # Owner instructions always proceed (no skip filter, no auto-assist check)

        # Get context
        recent = await service.get_messages(room_id, limit=20)
        owner_name = await _get_display_name(room["owner_id"], "オーナー")

        # Build conversation history with role labels
        history_lines = []
        for msg in recent:
            st = msg.get("sender_type", "?")
            sn = msg.get("sender_name", "?")
            c = msg.get("content", "")
            if st == "owner":
                history_lines.append(f"【オーナー({sn})】{c}")
            elif st == "guest":
                history_lines.append(f"【ゲスト({sn})】{c}")
            elif st.startswith("dan_"):
                history_lines.append(f"【DAN】{c}")
        history_text = "\n".join(history_lines)

        # Build prompt for full DAN agent
        content = trigger_message.get("content", "").strip()
        if is_owner_instruction:
            collab_prompt = (
                f"あなたはコラボルーム内でオーナー（{owner_name}）をアシストしています。\n"
                f"あなたの応答はオーナーだけに見えます。ゲストには見えません。\n\n"
                f"## ルーム情報\n"
                f"- タイトル: {room['title']}\n"
                f"- 説明: {room.get('description') or '(なし)'}\n\n"
                f"## 会話履歴\n{history_text}\n\n"
                f"## オーナーからの指示\n"
                f"{content}\n\n"
                f"この指示を実行してください。ツールを積極的に使ってください。"
            )
        else:
            collab_prompt = (
                f"あなたはコラボルーム内でオーナー（{owner_name}）をアシストしています。\n"
                f"あなたの応答はオーナーだけに見えます。ゲストには見えません。\n\n"
                f"## ルーム情報\n"
                f"- タイトル: {room['title']}\n"
                f"- 説明: {room.get('description') or '(なし)'}\n\n"
                f"## 会話履歴\n{history_text}\n\n"
                f"## ゲストの新しいメッセージ\n"
                f"【ゲスト({trigger_message.get('sender_name', '?')})】{content}\n\n"
                f"## 指示\n"
                f"このメッセージに対してオーナーをサポートしてください。\n"
                f"- ツールが必要なら使ってください（カレンダー確認、ファイル操作、ブラウザ操作など）\n"
                f"- 返信案は生成しないでください（ユーザーが手動で生成します）\n"
                f"- カレンダー・資料管理・タスク管理など作業系の提案やアクション実行のみ行ってください\n"
                f"- 反応不要なメッセージなら何も返さないでください\n"
                f"- 簡潔に（長くても5行以内）"
            )

        # Use a unique room_id for collab DAN to avoid conflicting with main chat sessions
        collab_dan_room_id = f"collab_dan_{room_id}"

        # Notify owner that DAN is thinking
        await collab_manager.send_to_type(room_id, "owner", {
            "type": "dan_thinking",
            "room_id": room_id,
        })

        # Run full DAN agent via cli_runner
        from app.agent.cli_runner import process_message_cli
        final_text = ""

        async for event in process_message_cli(
            room_id=collab_dan_room_id,
            user_id=room["owner_id"],
            content=collab_prompt,
            system_prompt=(
                f"あなたはDANです。オーナー（{owner_name}）の秘書として、コラボルーム内のゲストとのやり取りをサポートします。\n"
                f"ツールを積極的に使ってください。応答は日本語で簡潔に。反応不要なら空文字を返してください。\n\n"
                f"## 使えるツール\n"
                f"- **Googleカレンダー**: オーナーのカレンダーに接続済み。Pythonで直接呼び出せます:\n"
                f"  - 予定一覧: python -c \"from app.services.calendar_service import CalendarService; svc=CalendarService(); print(svc.get_events('{room['owner_id']}'))\"\n"
                f"  - 空き時間: python -c \"from app.services.calendar_service import CalendarService; svc=CalendarService(); print(svc.find_free_slots('{room['owner_id']}'))\"\n"
                f"  - 予定作成: python -c \"from app.services.calendar_service import CalendarService; svc=CalendarService(); print(svc.create_event('{room['owner_id']}', 'タイトル', '2026-03-28T10:00:00+09:00', '2026-03-28T11:00:00+09:00'))\"\n"
                f"- **ファイル操作**: D:/dan-workspace/ でファイルの読み書きが可能\n"
                f"- **ブラウザ操作**: Webページのアクセス、操作が可能\n"
                f"- **検索**: Web検索が可能\n\n"
                f"## 重要ルール\n"
                f"- スケジュールに関する質問には、必ずカレンダーAPIを実行して実データを確認してから回答すること\n"
                f"- 「オーナーに聞いてください」ではなく、自分でツールを使って情報を取得すること\n"
                f"- 返信案は生成しないこと（ユーザーが手動で生成する機能があります）\n"
                f"- カレンダー・資料管理・タスク管理など作業系のサポートのみ行うこと"
            ),
            skip_resume=True,
            cwd=str(CLI_WORKSPACE),
        ):
            if event["type"] == "text":
                final_text += event.get("text", "")
            elif event["type"] == "result":
                if event.get("text"):
                    final_text = event["text"]
            elif event["type"] == "error":
                error_msg = event.get("message", "Unknown error")
                logger.error("DAN CLI error: %s", error_msg)
                final_text = f"（エラーが発生しました: {error_msg}）"
                break
            # keepalive events are ignored silently

        final_text = final_text.strip()
        if not final_text or final_text.upper() == "SKIP":
            # Notify owner that DAN finished without response
            await collab_manager.send_to_type(room_id, "owner", {
                "type": "dan_done", "room_id": room_id,
            })
            return

        # Save and send to owner only
        dan_message = await service.send_message(
            room_id=room_id,
            sender_type="dan_owner",
            sender_name="DAN",
            content=final_text,
            metadata={"visibility": "owner_only"},
        )

        await collab_manager.send_to_type(room_id, "owner", {
            "type": "new_message",
            "message": {
                "id": dan_message["id"],
                "room_id": room_id,
                "sender_type": dan_message["sender_type"],
                "sender_name": dan_message["sender_name"],
                "content": dan_message["content"],
                "metadata": dan_message.get("metadata", {}),
                "created_at": dan_message["created_at"],
            }
        })

    except Exception as e:
        logger.error("DAN assist error: %s", e, exc_info=True)
        # Notify owner about the error
        try:
            error_message = await service.send_message(
                room_id=room_id,
                sender_type="dan_owner",
                sender_name="DAN",
                content=f"（エラー: {str(e)[:200]}）",
                metadata={"visibility": "owner_only"},
            )
            await collab_manager.send_to_type(room_id, "owner", {
                "type": "new_message",
                "message": {
                    "id": error_message["id"],
                    "room_id": room_id,
                    "sender_type": error_message["sender_type"],
                    "sender_name": error_message["sender_name"],
                    "content": error_message["content"],
                    "metadata": error_message.get("metadata", {}),
                    "created_at": error_message["created_at"],
                }
            })
        except Exception:
            pass


async def _trigger_guest_dan_assist(service: CollabService, room_id: str, trigger_message: dict):
    """Lightweight DAN assist for guests using Gemini API (no tools)."""
    try:
        room = await service.get_room(room_id)
        if not room:
            return

        recent = await service.get_messages(room_id, limit=20)
        guest_name = trigger_message.get("sender_name", "ゲスト")
        content = trigger_message.get("content", "").strip()

        # Build conversation history
        history_lines = []
        for msg in recent:
            st = msg.get("sender_type", "?")
            sn = msg.get("sender_name", "?")
            c = msg.get("content", "")
            if st == "owner":
                history_lines.append(f"【オーナー({sn})】{c}")
            elif st == "guest":
                history_lines.append(f"【ゲスト({sn})】{c}")
            elif st == "dan_guest":
                history_lines.append(f"【DAN→ゲスト】{c}")
        history_text = "\n".join(history_lines)

        # Notify guest that DAN is thinking
        await collab_manager.send_to_type(room_id, "guest", {
            "type": "dan_thinking", "room_id": room_id,
        })

        # Call lightweight DAN (Gemini)
        import asyncio
        from app.services.collab_dan_service import get_dan_response
        loop = asyncio.get_event_loop()
        response_text = await loop.run_in_executor(
            None,
            lambda: get_dan_response(
                room["title"],
                room.get("description"),
                recent,
                trigger_message,
                owner_name=guest_name,
                system_override=(
                    f"あなたはDANというAIアシスタントです。コラボルーム内でゲスト（{guest_name}）をサポートします。\n"
                    f"あなたの応答はゲストだけに見えます。オーナーには見えません。\n\n"
                    f"## ルーム情報\n"
                    f"- タイトル: {room['title']}\n"
                    f"- 説明: {room.get('description') or '(なし)'}\n\n"
                    f"## 会話履歴\n{history_text}\n\n"
                    f"## ゲスト（{guest_name}）からの指示\n{content}\n\n"
                    f"## ルール\n"
                    f"- 日本語で簡潔に回答（5行以内）\n"
                    f"- 反応不要なら何も返さないでください"
                ),
            ),
        )

        if not response_text or response_text.strip().upper() == "SKIP":
            await collab_manager.send_to_type(room_id, "guest", {
                "type": "dan_done", "room_id": room_id,
            })
            return

        # Save and send to guest only
        dan_message = await service.send_message(
            room_id=room_id,
            sender_type="dan_guest",
            sender_name="DAN",
            content=response_text,
            metadata={"visibility": "guest_only"},
        )

        await collab_manager.send_to_type(room_id, "guest", {
            "type": "new_message",
            "message": {
                "id": dan_message["id"],
                "room_id": room_id,
                "sender_type": dan_message["sender_type"],
                "sender_name": dan_message["sender_name"],
                "content": dan_message["content"],
                "metadata": dan_message.get("metadata", {}),
                "created_at": dan_message["created_at"],
            }
        })

    except Exception as e:
        logger.error("Guest DAN assist error: %s", e, exc_info=True)
        try:
            error_msg = await service.send_message(
                room_id=room_id,
                sender_type="dan_guest",
                sender_name="DAN",
                content=f"（エラー: {str(e)[:200]}）",
                metadata={"visibility": "guest_only"},
            )
            await collab_manager.send_to_type(room_id, "guest", {
                "type": "new_message",
                "message": {
                    "id": error_msg["id"],
                    "room_id": room_id,
                    "sender_type": error_msg["sender_type"],
                    "sender_name": error_msg["sender_name"],
                    "content": error_msg["content"],
                    "metadata": error_msg.get("metadata", {}),
                    "created_at": error_msg["created_at"],
                }
            })
        except Exception:
            pass  # guest DAN error fallback


async def _send_push(room_id: str, sender_type: str, sender_name: str, content: str):
    """Send push notification to the other side."""
    try:
        from app.services.push_service import get_push_service
        svc = get_push_service()
        body = content[:100] + ("..." if len(content) > 100 else "")
        await svc.notify_room(
            room_id=room_id,
            exclude_type=sender_type,
            title=sender_name,
            body=body,
        )
    except Exception as e:
        logger.error("Push notification error: %s", e)
