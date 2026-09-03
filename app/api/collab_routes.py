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
        origin_chat_room_id=req.origin_chat_room_id,
    )
    return CollabRoomResponse(**room, guest_count=0)


def _preview_text(msg: dict) -> str:
    files = (msg.get("metadata") or {}).get("files") or []
    single = (msg.get("metadata") or {}).get("file")
    if single and not files:
        files = [single]
    if files:
        kinds = [(f.get("type") or "") for f in files]
        if all(k.startswith("image/") for k in kinds):
            label = "📷 画像" if len(files) == 1 else f"📷 画像 {len(files)}枚"
        elif all(k.startswith("video/") for k in kinds):
            label = "🎬 動画" if len(files) == 1 else f"🎬 動画 {len(files)}本"
        else:
            label = f"📎 {files[0].get('name') or 'ファイル'}" + (f" 他{len(files)-1}件" if len(files) > 1 else "")
        return label
    return (msg.get("content") or "")[:100]


@router.get("/rooms", response_model=CollabRoomListResponse)
async def list_rooms(
    user: TokenData = Depends(get_current_user),
    service: CollabService = Depends(get_collab_service),
):
    import asyncio

    # Owner's rooms + rooms where user is a guest（同時に取る）
    rooms, guest_rooms = await asyncio.gather(
        service.list_rooms(user.user_id), service.list_guest_rooms(user.user_id)
    )

    unique: list[dict] = []
    seen_ids = set()
    for r in rooms + guest_rooms:
        if r["id"] in seen_ids:
            continue
        seen_ids.add(r["id"])
        unique.append(r)

    # 部屋ごとの付加情報（参加者数・最終メッセージ・未読）は互いに独立なので全部同時に取る。
    # 以前は部屋ごとに3本を直列に待っていて、5部屋で約17往復(=DBがシンガポールで1往復150ms)
    # → 2〜4秒かかっていた。これがコミュニケーション一覧が開かない主因。
    async def _enrich(r: dict) -> CollabRoomResponse:
        invites, messages, unread_count = await asyncio.gather(
            service.list_invites(r["id"]),
            service.get_messages(r["id"], limit=1),
            service.unread_count_for_owner(r),
        )
        guest_count = sum(1 for i in invites if i["status"] == "joined")
        last_msg = messages[-1] if messages else None
        return CollabRoomResponse(
            **r,
            guest_count=guest_count,
            last_message=_preview_text(last_msg) if last_msg else None,
            last_message_at=last_msg["created_at"] if last_msg else None,
            unread=unread_count > 0,
            unread_count=unread_count,
        )

    room_responses = list(await asyncio.gather(*[_enrich(r) for r in unique]))
    # 並びは「メッセージの動きがあった順」。updated_at は既読更新などでも動いてしまい、
    # 開いただけで一覧の順番が入れ替わる誤動作の原因になるため使わない。
    room_responses.sort(
        key=lambda x: x.last_message_at or x.created_at or "",
        reverse=True,
    )
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
    import asyncio
    guest_rooms, invites = await asyncio.gather(
        service.list_guest_rooms(user.user_id) if not is_owner else asyncio.sleep(0, result=[]),
        service.list_invites(room_id),
    )
    is_guest = any(gr["id"] == room_id for gr in guest_rooms)
    if not is_owner and not is_guest:
        raise HTTPException(status_code=404, detail="Room not found")
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
        # personal=True: 本人専用URL（開いた端末に関係なくこの身分で入れる）
        # personal=False: 入口URL（名前を入れて参加すると専用URLが発行される）
        "personal": bool(invite.get("guest_name")),
        "already_joined": bool(invite.get("guest_name")),
    }
    if invite.get("guest_name"):
        # 本人専用URLはそのまま入室させてよい（このURLを持っている＝本人）
        result["rejoin_token"] = _create_guest_token(
            invite_id=invite["id"],
            room_id=invite["room_id"],
            guest_name=invite["guest_name"],
            role=invite["role"],
        )
        result["room_id"] = invite["room_id"]
        result["guest_name"] = invite["guest_name"]
    return result


@router.post("/join/{token}", response_model=CollabJoinResponse)
async def join_room(
    token: str,
    req: CollabJoinRequest,
    service: CollabService = Depends(get_collab_service),
):
    """Guest joins a collab room via invite token. No auth required.

    1つの招待URL＝部屋の入口。最初の参加者は招待行そのものを身分証として使い、
    2人目以降は参加ごとに新しい身分（collab_invites 行）を発行する。
    """
    invite = await service.get_invite_by_token(token)
    if not invite:
        raise HTTPException(status_code=404, detail="Invalid invite link")
    room = invite.get("collab_rooms") or await service.get_room(invite["room_id"])

    # 身分モデル:
    #   - 入口URL（共有する招待リンク）= guest_name を持たない行。誰が何度開いても消費されない
    #   - 本人専用URL = 参加時に発行される身分行のトークン。開いた端末・ブラウザに
    #     関係なくその人を特定する（iOSのホーム画面アプリはSafariと保存領域が別なので、
    #     ブラウザ保存に頼ると同じ人が別人として二重参加する。URLに身分を持たせて根治）
    if invite.get("guest_name"):
        # 本人専用URL: その身分で入る（名前は変更可能なので入力値は無視して身分側を正とする）
        guest_jwt = _create_guest_token(
            invite_id=invite["id"],
            room_id=invite["room_id"],
            guest_name=invite["guest_name"],
            role=invite["role"],
        )
        await service.update_invite_guest_token(invite["id"], guest_jwt)
        return CollabJoinResponse(
            guest_token=guest_jwt,
            room_id=invite["room_id"],
            room_title=room["title"] if room else "",
            guest_name=invite["guest_name"],
            role=invite["role"],
            personal_token=invite["token"],
        )

    # 入口URL: この参加者専用の身分（＋専用URL）を新規発行。入口行自体は身分にしない
    identity = await service.create_joiner_identity(invite["room_id"], req.guest_name, invite["role"])
    guest_jwt = _create_guest_token(
        invite_id=identity["id"],
        room_id=invite["room_id"],
        guest_name=req.guest_name,
        role=invite["role"],
    )
    await service.update_invite_guest_token(identity["id"], guest_jwt)
    return CollabJoinResponse(
        guest_token=guest_jwt,
        room_id=invite["room_id"],
        room_title=room["title"] if room else "",
        guest_name=req.guest_name,
        role=invite["role"],
        personal_token=identity["token"],
    )


@router.get("/me")
async def guest_me(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    service: CollabService = Depends(get_collab_service),
):
    """ゲストの自分の身分情報（本人専用URL用トークン）。
    入口URLに古いセッションで来た人を、本人専用URLへ移行させるために使う。"""
    guest_token = _get_guest_token_from_request(request, credentials)
    if not guest_token:
        raise HTTPException(status_code=401, detail="Guest token required")
    gd = _decode_guest_token(guest_token)
    if not gd:
        raise HTTPException(status_code=403, detail="Invalid guest token")
    invites = await service.list_invites(gd["room_id"])
    mine = next((i for i in invites if i["id"] == gd.get("sub")), None)
    if not mine:
        raise HTTPException(status_code=404, detail="Identity not found")
    return {
        "personal_token": mine["token"],
        "guest_name": mine.get("guest_name"),
        "room_id": gd["room_id"],
    }


@router.post("/rename")
async def rename_guest(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    service: CollabService = Depends(get_collab_service),
):
    """ゲストの表示名変更。サーバー側の身分を更新し、新しい名前入りのトークンを返す。"""
    guest_token = _get_guest_token_from_request(request, credentials)
    if not guest_token:
        raise HTTPException(status_code=401, detail="Guest token required")
    guest_data = _decode_guest_token(guest_token)
    if not guest_data:
        raise HTTPException(status_code=403, detail="Invalid guest token")
    data = await request.json()
    new_name = (data.get("guest_name") or "").strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="guest_name required")

    updated = await service.update_invite_name(guest_data["sub"], new_name)
    if not updated:
        raise HTTPException(status_code=404, detail="Identity not found")
    new_jwt = _create_guest_token(
        invite_id=guest_data["sub"],
        room_id=guest_data["room_id"],
        guest_name=new_name,
        role=guest_data.get("role", "reviewer"),
    )
    await service.update_invite_guest_token(guest_data["sub"], new_jwt)
    return {"guest_token": new_jwt, "guest_name": new_name}


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

    has_files = bool((req.metadata or {}).get("files") or (req.metadata or {}).get("file"))
    if not (req.content or "").strip() and not has_files:
        raise HTTPException(status_code=422, detail="content or files required")
    # 通知・一覧・Push 用の短い本文（添付だけなら「📷 画像 3枚」等）
    preview = _preview_text({"content": req.content, "metadata": req.metadata})

    # ユーザー→ダンの私的メッセージ（相談への返答・指示）。相手には一切見せない
    is_owner_private = (
        sender_type == "owner"
        and ((req.metadata or {}).get("visibility") == "owner_only")
    )

    message = await service.send_message(
        room_id=room_id,
        sender_type=sender_type,
        sender_name=sender_name,
        content=req.content,
        metadata=req.metadata,
    )

    ws_payload = {
        "type": "new_message",
        "message": {
            "id": message["id"],
            "room_id": room_id,
            "sender_type": message["sender_type"],
            "sender_name": message["sender_name"],
            "content": message["content"],
            "metadata": message.get("metadata", {}),
            "created_at": message["created_at"],
        },
    }

    import asyncio
    if is_owner_private:
        # 自分側の画面にだけ配信し、ダンへ即時ディスパッチ。通知・Pushは出さない
        await collab_manager.send_to_type(room_id, "owner", ws_payload)
        asyncio.ensure_future(_dispatch_owner_private(service, room_id, message))
        return CollabMessageResponse(**message)

    # 部屋のWebSocketにも配信する（WS経由の送信と同じ見え方にする）。
    # これが無いと、REST経由の着信（スマホのフォールバック送信・外部ボット等）が
    # 開きっぱなしの画面にリアルタイム表示されない。
    await collab_manager.broadcast(room_id, ws_payload)

    # Real-time notification via WebSocket
    asyncio.ensure_future(notification_manager.notify_room_users(
        room_id,
        {"type": "new_message_notification", "room_id": room_id,
         "room_title": ((await service.get_room(room_id)) or {}).get("title", ""),
         "sender_name": sender_name, "content": preview[:100]},
        service
    ))

    # 相手側へのPush通知（WS経路と同じ扱い）
    asyncio.ensure_future(_send_push(room_id, sender_type, sender_name, preview))

    # Trigger DAN (REST API path)
    if sender_type == "guest":
        asyncio.ensure_future(
            _dispatch_guest_message(service, room_id, message)
        )
    elif sender_type == "owner":
        # ユーザーの公開発言もダンに届ける（ダン宛てかどうかはダンが判断し、
        # 宛てられていれば公開の場で直接返答する）
        asyncio.ensure_future(
            _dispatch_owner_public(service, room_id, message)
        )

    return CollabMessageResponse(**message)


# ==================== Participants / Read ====================

async def _room_access(request: Request, credentials, service: CollabService, room_id: str):
    """オーナー or ゲストのアクセス判定。(is_owner, guest_invite_id) を返す。どちらでもなければ None。"""
    owner_token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not owner_token and credentials:
        owner_token = credentials.credentials
    if owner_token:
        td = decode_access_token(owner_token)
        if td:
            room = await service.get_room(room_id)
            if room and room["owner_id"] == td.user_id:
                return True, None
    guest_token = request.headers.get("X-Guest-Token") or (
        credentials.credentials if credentials else None
    )
    if guest_token:
        gd = _decode_guest_token(guest_token)
        if gd and gd.get("room_id") == room_id:
            return False, gd.get("sub")
    return None


@router.get("/rooms/{room_id}/participants")
async def get_participants(
    room_id: str,
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    service: CollabService = Depends(get_collab_service),
):
    """参加者名簿（オーナー＋参加済みゲスト）と既読位置。双方から見える。"""
    access = await _room_access(request, credentials, service, room_id)
    if access is None:
        raise HTTPException(status_code=403, detail="Access denied")
    room = await service.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    owner_name = await _get_display_name(room["owner_id"], "オーナー")
    guests = await service.list_participants(room_id)
    return {
        "owner": {"name": owner_name, "last_read_at": room.get("owner_last_read_at")},
        "guests": guests,
    }


@router.post("/rooms/{room_id}/messages/{message_id}/react")
async def react_to_message(
    room_id: str,
    message_id: str,
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    service: CollabService = Depends(get_collab_service),
):
    """人間（オーナー/ゲスト）のリアクション。同じ絵文字をもう一度で外れる（トグル）。
    通知・Push・未読は発生しない。開いている画面にはWSで即反映。"""
    access = await _room_access(request, credentials, service, room_id)
    if access is None:
        raise HTTPException(status_code=403, detail="Access denied")
    is_owner, guest_invite_id = access
    data = await request.json()
    emoji = (data.get("emoji") or "").strip()
    if not emoji or len(emoji) > 8:
        raise HTTPException(status_code=422, detail="emoji required")
    if is_owner:
        room = await service.get_room(room_id)
        by = await _get_display_name(room["owner_id"], "オーナー") if room else "オーナー"
    else:
        gd = _decode_guest_token(_get_guest_token_from_request(request, credentials) or "") or {}
        by = gd.get("guest_name") or "ゲスト"
    msg = await service.add_reaction(room_id, message_id, emoji, by=by, toggle=True)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    reactions = (msg.get("metadata") or {}).get("reactions") or {}
    await collab_manager.broadcast(room_id, {
        "type": "reaction", "message_id": message_id, "reactions": reactions,
    })
    return {"reactions": reactions}


@router.post("/rooms/{room_id}/read")
async def mark_room_read(
    room_id: str,
    request: Request = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    service: CollabService = Depends(get_collab_service),
):
    """既読位置の更新（開いている間、フロントが定期的に叩く）。"""
    access = await _room_access(request, credentials, service, room_id)
    if access is None:
        raise HTTPException(status_code=403, detail="Access denied")
    is_owner, guest_invite_id = access
    await service.mark_read(room_id, guest_invite_id=guest_invite_id, as_owner=is_owner)
    return {"ok": True}


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
                        # Owner → ダンへの指示。origin 紐付きルームなら本体ダンへ
                        import asyncio
                        asyncio.ensure_future(
                            _dispatch_owner_private(service, room_id, {
                                **message,
                                "content": dan_content,
                                "sender_type": "owner",
                                "sender_name": sender_name,
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
                elif sender_type == "owner" and (metadata or {}).get("visibility") == "owner_only":
                    # ユーザー→ダンの私的メッセージ（相談への返信）。相手には見せず、
                    # 自分側にだけ表示して本体ダンへ即時ディスパッチ
                    message = await service.send_message(
                        room_id=room_id,
                        sender_type=sender_type,
                        sender_name=sender_name,
                        content=content,
                        metadata=metadata,
                    )
                    await collab_manager.send_to_type(room_id, "owner", {
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
                    import asyncio
                    asyncio.ensure_future(_dispatch_owner_private(service, room_id, message))
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

                    # DAN auto-assist
                    if sender_type == "guest":
                        import asyncio
                        asyncio.ensure_future(
                            _dispatch_guest_message(service, room_id, message)
                        )
                    elif sender_type == "owner":
                        import asyncio
                        asyncio.ensure_future(
                            _dispatch_owner_public(service, room_id, message)
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


async def _dispatch_guest_message(service: CollabService, room_id: str, message: dict):
    """ゲスト発言をダンに届ける振り分け。

    - origin 紐付きルーム（collab_thread ツールで作った外部窓口）: 本体チャットの部屋で
      ダンを自動起動する（core の /api/v1/chat/internal/collab-inbound 経由）。
      会話がダンの本体記憶に入り、改善提案・返信案が本体チャットに出る。
    - それ以外（手動作成の従来ルーム）: 従来どおり隔離 collab DAN でサポート。
    """
    try:
        room = await service.get_room(room_id)
        if room and room.get("origin_chat_room_id"):
            await _notify_origin_chat(service, room_id, message)
        else:
            await _trigger_dan_assist(service, room_id, message)
    except Exception:
        logger.exception("guest message dispatch failed room=%s", room_id)


async def _notify_origin_chat(service: CollabService, room_id: str, message: dict):
    """core にゲスト着信を中継して origin ルームで wake させる。core 不通なら通知タブへ。"""
    import httpx
    core_port = os.environ.get("DAN_CORE_PORT", "9000")
    payload = {
        "collab_room_id": room_id,
        "message": {k: message.get(k) for k in
                    ("id", "sender_type", "sender_name", "content", "created_at", "metadata")},
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"http://127.0.0.1:{core_port}/api/v1/chat/internal/collab-inbound",
                json=payload,
            )
            r.raise_for_status()
    except Exception:
        logger.warning("collab inbound relay to core failed room=%s; falling back to proposal",
                       room_id, exc_info=True)
        await service.notify_origin_chat_of_guest_message(room_id, message)


async def _dispatch_owner_public(service: CollabService, room_id: str, message: dict):
    """ユーザーの公開発言をダンへ。origin 紐付きルームのみ（ダン宛てかはダンが判断）。"""
    try:
        room = await service.get_room(room_id)
        if room and room.get("origin_chat_room_id"):
            await _notify_origin_chat(service, room_id, message)
    except Exception:
        logger.exception("owner public dispatch failed room=%s", room_id)


async def _dispatch_owner_private(service: CollabService, room_id: str, message: dict):
    """ユーザーの私的メッセージ（相談への返答・ダンへの指示）をダンへ届ける。

    origin 紐付きルームでは本体ダン（相談を出した頭）に即時で届ける。
    紐付き無しの従来ルームは旧来の隔離アシストにフォールバック。
    """
    try:
        room = await service.get_room(room_id)
        if room and room.get("origin_chat_room_id"):
            await _notify_origin_chat(service, room_id, message)
        else:
            await _trigger_dan_assist(service, room_id, {**message, "_owner_instruction": True})
    except Exception:
        logger.exception("owner private dispatch failed room=%s", room_id)


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
            url=f"/collab/{room_id}",
        )
        # オーナー宛（相手やダンからの新着）は、APKのネイティブ通知トークン
        # （room_id="user:{owner_id}" で登録される）にも届ける
        if sender_type != "owner":
            room = await CollabService().get_room(room_id)
            if room:
                await svc.notify_room(
                    room_id=f"user:{room['owner_id']}",
                    exclude_type=sender_type,
                    title=sender_name,
                    body=body,
                    url=f"/collab/{room_id}",
                )
    except Exception as e:
        logger.error("Push notification error: %s", e)


# ==================== Internal (localhost only) ====================

# 窓口ごとのダン稼働状態（考え中インジケーター用）。
# WS が張れない環境（Vercel 経由）はポーリングでこのキャッシュを読む。
# サンドボックス再起動で消える＝消灯側に倒れる（安全側）。
_dan_status: dict[str, float] = {}   # room_id -> thinking 開始時刻(epoch)
_DAN_STATUS_TTL = 30 * 60            # 万一 done が来なくても30分で自動消灯


@router.post("/internal/react")
async def internal_react(
    request: Request,
    service: CollabService = Depends(get_collab_service),
):
    """ダンのリアクション（既読サイン🙏など）。メッセージではないので通知・Push・未読なし。
    開いている画面には WS でリアルタイム反映される。"""
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Internal only")
    data = await request.json()
    room_id = (data.get("room_id") or "").strip()
    message_id = (data.get("message_id") or "").strip()
    emoji = (data.get("emoji") or "🙏").strip() or "🙏"
    if not room_id or not message_id:
        raise HTTPException(status_code=422, detail="room_id and message_id required")
    msg = await service.add_reaction(room_id, message_id, emoji, by=(data.get("by") or "ダン"))
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    await collab_manager.broadcast(room_id, {
        "type": "reaction",
        "message_id": message_id,
        "reactions": (msg.get("metadata") or {}).get("reactions") or {},
    })
    return {"ok": True}


@router.post("/internal/dan-status")
async def internal_dan_status(request: Request):
    """ダンの稼働状態をオーナー画面に流す（考え中インジケーター用）。core から呼ばれる。"""
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Internal only")
    data = await request.json()
    room_id = (data.get("room_id") or "").strip()
    status = (data.get("status") or "").strip()
    if not room_id or status not in ("thinking", "done"):
        raise HTTPException(status_code=422, detail="room_id and status(thinking|done) required")
    import time as _time
    if status == "thinking":
        _dan_status[room_id] = _time.time()
    else:
        _dan_status.pop(room_id, None)
    await collab_manager.send_to_type(room_id, "owner", {
        "type": "dan_thinking" if status == "thinking" else "dan_done",
        "room_id": room_id,
    })
    return {"ok": True}


@router.get("/rooms/{room_id}/dan-status")
async def get_dan_status(
    room_id: str,
    user: TokenData = Depends(get_current_user),
    service: CollabService = Depends(get_collab_service),
):
    """ダンが考え中かどうか（オーナー画面のポーリング用）。"""
    room = await service.get_room(room_id)
    if not room or room["owner_id"] != user.user_id:
        raise HTTPException(status_code=404, detail="Room not found")
    import time as _time
    since = _dan_status.get(room_id)
    thinking = bool(since and (_time.time() - since) < _DAN_STATUS_TTL)
    return {"thinking": thinking}



@router.post("/internal/send")
async def internal_send_message(
    request: Request,
    service: CollabService = Depends(get_collab_service),
):
    """ダン（compose_message channel="collab"）からの送信。保存＋WS配信＋Push まで行う。

    core / MCP サブプロセスから localhost 経由でのみ呼ばれる。ゲスト側には
    「DAN」の発言として表示される（visibility 指定なし＝双方に見える）。
    """
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Internal only")

    data = await request.json()
    room_id = (data.get("room_id") or "").strip()
    content = (data.get("content") or "").strip()
    if not room_id or not content:
        raise HTTPException(status_code=422, detail="room_id and content required")
    room = await service.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    sender_name = (data.get("sender_name") or "ダン").strip() or "ダン"
    # visibility="owner_only" はダンからユーザーへの「相談」: 相手には見せない
    owner_only = (data.get("visibility") or "").strip() == "owner_only"
    metadata = {"via": "consult" if owner_only else "outbound_card"}
    if owner_only:
        metadata["visibility"] = "owner_only"
        # 既存の相談スレッドの続きなら、そのスレッド（親メッセージ）にぶら下げる
        reply_to_id = (data.get("reply_to_message_id") or "").strip()
        if reply_to_id:
            metadata["reply_to"] = {"id": reply_to_id}

    message = await service.send_message(
        room_id=room_id,
        sender_type="dan_owner",
        sender_name=sender_name,
        content=content,
        metadata=metadata,
    )

    payload = {
        "type": "new_message",
        "message": {
            "id": message["id"],
            "room_id": room_id,
            "sender_type": message["sender_type"],
            "sender_name": message["sender_name"],
            "content": message["content"],
            "metadata": message.get("metadata", {}),
            "created_at": message["created_at"],
        },
    }
    if owner_only:
        await collab_manager.send_to_type(room_id, "owner", payload)
    else:
        await collab_manager.broadcast(room_id, payload)

    import asyncio
    asyncio.ensure_future(notification_manager.notify_room_users(
        room_id,
        {"type": "new_message_notification", "room_id": room_id,
         "room_title": room.get("title", ""),
         "sender_name": sender_name, "content": content[:100]},
        service,
    ))
    # 通常送信は相手（guest）側へ、相談はユーザー（owner）側へ Push
    asyncio.ensure_future(_send_push(room_id, "guest" if owner_only else "owner", sender_name, content))

    return {"message_id": message["id"], "delivery": "owner_only" if owner_only else "broadcast"}
