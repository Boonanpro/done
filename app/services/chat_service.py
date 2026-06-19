"""
Chat Service - Business Logic for Done Chat
"""
from typing import Optional, Callable, Any
from datetime import datetime, timedelta, timezone
import secrets
import re
import asyncio
import random
import logging

from app.services.supabase_client import get_supabase_client
from app.services.auth_service import get_password_hash, verify_password


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


def generate_invite_code(length: int = 8) -> str:
    """Generate a random invite code"""
    return secrets.token_urlsafe(length)[:length]


def build_message_preview(content: Optional[str], limit: int = 80) -> str:
    """Turn raw message content into a short, single-line chat-list preview.

    Strips internal markup, collapses attachment tags into a short label,
    drops markdown emphasis markers, and truncates.
    """
    if not content:
        return ""
    text = re.sub(r"<dan-context>.*?</dan-context>", "", content, flags=re.DOTALL)
    text = re.sub(r"\[添付画像:[^\]]*\]", "📷 画像", text)
    text = re.sub(r"\[添付動画:[^\]]*\]", "🎬 動画", text)
    text = re.sub(r"\[添付ファイル:[^\]]*\]", "📎 ファイル", text)
    # Markdown link [label](url) -> label
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    # Emphasis / code markers
    text = re.sub(r"[*_`#>]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def record_message_delivery_sync(
    sb,
    room_id: str,
    message_id: Optional[str] = None,
    sender_id: Optional[str] = None,
    content: Optional[str] = None,
) -> None:
    """Sync analog of ``ChatService._record_message_delivery`` for callers that
    insert into ``chat_messages`` directly (cli_runner, live_runner) and so
    bypass the ChatService send paths.

    Bumps ``chat_rooms.last_message_at`` (and ``last_message_preview`` when
    ``content`` is given) and updates ``chat_room_members`` unread state. With
    ``sender_id=None`` (an AI reply) every member's ``unread_count`` is
    incremented. Best-effort; failures are logged but do not raise.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        room_update: dict = {"last_message_at": now}
        if content is not None:
            room_update["last_message_preview"] = build_message_preview(content)
        sb.table("chat_rooms").update(room_update).eq("id", room_id).execute()

        members = sb.table("chat_room_members").select(
            "id,user_id,unread_count"
        ).eq("room_id", room_id).execute()

        for member in members.data or []:
            if sender_id and member.get("user_id") == sender_id:
                update_data: dict = {
                    "last_read_at": now,
                    "unread_count": 0,
                }
                if message_id:
                    update_data["last_read_message_id"] = message_id
                sb.table("chat_room_members").update(update_data).eq("id", member["id"]).execute()
                continue

            current = member.get("unread_count") or 0
            sb.table("chat_room_members").update({
                "unread_count": current + 1,
            }).eq("id", member["id"]).execute()
    except Exception as exc:
        logging.getLogger(__name__).warning("record_message_delivery_sync failed: %s", exc)


class ChatService:
    """Done Chat business logic"""
    
    def __init__(self):
        self.supabase = get_supabase_client().client  # Use the underlying supabase client
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _is_transient_supabase_error(exc: Exception) -> bool:
        """Return True for transport errors that can succeed on retry."""
        text = str(exc).lower()
        markers = (
            "server disconnected",
            "remoteprotocolerror",
            "read timed out",
            "connection reset",
            "connection aborted",
            "temporarily unavailable",
        )
        return any(marker in text for marker in markers)

    async def _execute_with_retry(
        self,
        operation: str,
        fn: Callable[[], Any],
        retries: int = 2,
        base_delay: float = 0.2,
    ) -> Any:
        """Execute a sync Supabase request with short retries for transient failures."""
        attempt = 0
        while True:
            try:
                return fn()
            except Exception as exc:
                if attempt >= retries or not self._is_transient_supabase_error(exc):
                    raise
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.15)
                self.logger.warning(
                    "Transient Supabase error on %s (attempt %s/%s): %s",
                    operation,
                    attempt + 1,
                    retries + 1,
                    exc,
                )
                attempt += 1
                await asyncio.sleep(delay)
    
    # ==================== User Management ====================
    
    async def create_user(self, email: str, password: str, display_name: str) -> dict:
        """Create a new chat user"""
        password_hash = get_password_hash(password)
        
        result = self.supabase.table("users").insert({
            "email": email,
            "password_hash": password_hash,
            "display_name": display_name,
        }).execute()
        
        if result.data:
            user = result.data[0]
            # Don't return password_hash
            return {
                "id": user["id"],
                "email": user["email"],
                "display_name": user["display_name"],
                "avatar_url": user.get("avatar_url"),
                "created_at": user["created_at"],
            }
        raise ValueError("Failed to create user")
    
    async def get_user_by_email(self, email: str) -> Optional[dict]:
        """Get user by email (includes password_hash for authentication)"""
        result = self.supabase.table("users").select("*").eq("email", email).execute()
        return result.data[0] if result.data else None
    
    async def get_user_by_id(self, user_id: str) -> Optional[dict]:
        """Get user by ID (excludes password_hash)"""
        result = self.supabase.table("users").select(
            "id, email, display_name, avatar_url, created_at, updated_at"
        ).eq("id", user_id).execute()
        return result.data[0] if result.data else None
    
    async def update_user(self, user_id: str, display_name: Optional[str] = None, avatar_url: Optional[str] = None) -> Optional[dict]:
        """Update user profile"""
        update_data = {}
        if display_name is not None:
            update_data["display_name"] = display_name
        if avatar_url is not None:
            update_data["avatar_url"] = avatar_url
        
        if not update_data:
            return await self.get_user_by_id(user_id)
        
        result = self.supabase.table("users").update(update_data).eq("id", user_id).execute()
        if result.data:
            user = result.data[0]
            return {
                "id": user["id"],
                "email": user["email"],
                "display_name": user["display_name"],
                "avatar_url": user.get("avatar_url"),
                "created_at": user["created_at"],
                "updated_at": user["updated_at"],
            }
        return None
    
    async def authenticate_user(self, email: str, password: str) -> Optional[dict]:
        """Authenticate user with email and password"""
        user = await self.get_user_by_email(email)
        if not user:
            return None
        if not verify_password(password, user["password_hash"]):
            return None
        # Return user without password_hash
        return {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "avatar_url": user.get("avatar_url"),
            "created_at": user["created_at"],
        }
    
    # ==================== Invite Management ====================
    
    async def create_invite(self, creator_id: str, max_uses: int = 1, expires_in_hours: Optional[int] = 24) -> dict:
        """Create an invite link"""
        code = generate_invite_code()
        expires_at = None
        if expires_in_hours:
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)).isoformat()
        
        result = self.supabase.table("chat_invites").insert({
            "code": code,
            "creator_id": creator_id,
            "max_uses": max_uses,
            "expires_at": expires_at,
        }).execute()
        
        if result.data:
            return result.data[0]
        raise ValueError("Failed to create invite")
    
    async def get_invite_by_code(self, code: str) -> Optional[dict]:
        """Get invite by code"""
        result = self.supabase.table("chat_invites").select(
            "*, creator:users!creator_id(id, display_name, avatar_url)"
        ).eq("code", code).execute()
        return result.data[0] if result.data else None
    
    async def accept_invite(self, code: str, user_id: str) -> dict:
        """Accept an invite and create friendship"""
        invite = await self.get_invite_by_code(code)
        if not invite:
            raise ValueError("Invite not found")
        
        # Check if expired
        if invite.get("expires_at"):
            expires_at = parse_datetime(invite["expires_at"])
            if datetime.now(timezone.utc).replace(tzinfo=expires_at.tzinfo) > expires_at:
                raise ValueError("Invite has expired")
        
        # Check if max uses reached
        if invite["use_count"] >= invite["max_uses"]:
            raise ValueError("Invite has reached maximum uses")
        
        creator_id = invite["creator_id"]
        
        # Can't friend yourself
        if creator_id == user_id:
            raise ValueError("Cannot accept your own invite")
        
        # Create bidirectional friendship
        await self._create_friendship(user_id, creator_id)
        await self._create_friendship(creator_id, user_id)
        
        # Create direct chat room
        room = await self._create_direct_room(user_id, creator_id)
        
        # Increment use count
        self.supabase.table("chat_invites").update({
            "use_count": invite["use_count"] + 1
        }).eq("id", invite["id"]).execute()
        
        return {
            "friend_id": creator_id,
            "room_id": room["id"],
        }
    
    async def _create_friendship(self, user_id: str, friend_id: str) -> None:
        """Create a one-way friendship (internal)"""
        try:
            self.supabase.table("chat_friendships").insert({
                "user_id": user_id,
                "friend_id": friend_id,
            }).execute()
        except Exception:
            # Friendship might already exist
            pass
    
    async def _create_direct_room(self, user1_id: str, user2_id: str) -> dict:
        """Create a direct chat room between two users"""
        # Check if room already exists
        existing = self.supabase.table("chat_room_members").select(
            "room_id"
        ).eq("user_id", user1_id).execute()
        
        if existing.data:
            for member in existing.data:
                room_members = self.supabase.table("chat_room_members").select(
                    "user_id"
                ).eq("room_id", member["room_id"]).execute()
                
                if room_members.data and len(room_members.data) == 2:
                    member_ids = {m["user_id"] for m in room_members.data}
                    if member_ids == {user1_id, user2_id}:
                        # Room already exists
                        room = self.supabase.table("chat_rooms").select("*").eq("id", member["room_id"]).execute()
                        if room.data and room.data[0]["type"] == "direct":
                            return room.data[0]
        
        # Create new room
        room_result = self.supabase.table("chat_rooms").insert({
            "type": "direct",
        }).execute()
        
        if not room_result.data:
            raise ValueError("Failed to create room")
        
        room = room_result.data[0]
        
        # Add both users as members
        self.supabase.table("chat_room_members").insert([
            {"room_id": room["id"], "user_id": user1_id, "role": "member"},
            {"room_id": room["id"], "user_id": user2_id, "role": "member"},
        ]).execute()
        
        # Create default AI settings
        self.supabase.table("chat_ai_settings").insert({
            "room_id": room["id"],
            "enabled": False,
            "mode": "off",
        }).execute()
        
        return room
    
    # ==================== Friends Management ====================
    
    async def get_friends(self, user_id: str) -> list[dict]:
        """Get user's friends list"""
        result = self.supabase.table("chat_friendships").select(
            "*, friend:users!friend_id(id, display_name, avatar_url)"
        ).eq("user_id", user_id).eq("status", "active").execute()
        
        return [
            {
                "id": f["friend"]["id"],
                "display_name": f["friend"]["display_name"],
                "avatar_url": f["friend"].get("avatar_url"),
                "created_at": f["created_at"],
            }
            for f in result.data
        ] if result.data else []
    
    async def delete_friend(self, user_id: str, friend_id: str) -> bool:
        """Delete a friendship (bidirectional)"""
        # Delete both directions
        self.supabase.table("chat_friendships").delete().eq("user_id", user_id).eq("friend_id", friend_id).execute()
        self.supabase.table("chat_friendships").delete().eq("user_id", friend_id).eq("friend_id", user_id).execute()
        return True
    
    # ==================== Room Management ====================
    
    async def get_rooms(self, user_id: str) -> list[dict]:
        """Get user's chat rooms"""
        result = self.supabase.table("chat_room_members").select(
            "room_id, role, ai_mode, last_read_at, room:chat_rooms(*)"
        ).eq("user_id", user_id).execute()
        
        rooms = []
        for member in result.data or []:
            room = member["room"]
            room["my_role"] = member["role"]
            room["my_ai_mode"] = member["ai_mode"]
            room["last_read_at"] = member["last_read_at"]
            rooms.append(room)
        
        return rooms
    
    async def create_room(self, creator_id: str, name: str, member_ids: list[str]) -> dict:
        """Create a group chat room"""
        room_result = self.supabase.table("chat_rooms").insert({
            "name": name,
            "type": "group",
        }).execute()
        
        if not room_result.data:
            raise ValueError("Failed to create room")
        
        room = room_result.data[0]
        
        # Add creator as owner
        members = [{"room_id": room["id"], "user_id": creator_id, "role": "owner"}]
        
        # Add other members
        for member_id in member_ids:
            if member_id != creator_id:
                members.append({"room_id": room["id"], "user_id": member_id, "role": "member"})
        
        self.supabase.table("chat_room_members").insert(members).execute()
        
        # Create default AI settings
        self.supabase.table("chat_ai_settings").insert({
            "room_id": room["id"],
            "enabled": False,
            "mode": "off",
        }).execute()
        
        return room
    
    async def get_room(self, room_id: str, user_id: str) -> Optional[dict]:
        """Get room details (only if user is a member)"""
        # Verify membership
        member = await self._execute_with_retry(
            "get_room.membership_check",
            lambda: self.supabase.table("chat_room_members").select("*").eq("room_id", room_id).eq("user_id", user_id).execute(),
        )
        if not member.data:
            return None
        
        result = self.supabase.table("chat_rooms").select("*").eq("id", room_id).execute()
        if result.data:
            room = result.data[0]
            room["my_role"] = member.data[0]["role"]
            room["my_ai_mode"] = member.data[0]["ai_mode"]
            return room
        return None
    
    async def update_room(self, room_id: str, user_id: str, name: Optional[str] = None) -> Optional[dict]:
        """Update room settings"""
        # Verify membership and role
        member = await self._execute_with_retry(
            "get_messages.membership_check",
            lambda: self.supabase.table("chat_room_members").select("*").eq("room_id", room_id).eq("user_id", user_id).execute(),
        )
        if not member.data:
            return None
        
        if member.data[0]["role"] not in ["owner", "admin"]:
            raise ValueError("Permission denied")
        
        update_data = {}
        if name is not None:
            update_data["name"] = name
        
        if update_data:
            result = self.supabase.table("chat_rooms").update(update_data).eq("id", room_id).execute()
            return result.data[0] if result.data else None
        
        return await self.get_room(room_id, user_id)
    
    async def get_room_members(self, room_id: str, user_id: str) -> list[dict]:
        """Get room members"""
        # Verify membership
        member = self.supabase.table("chat_room_members").select("*").eq("room_id", room_id).eq("user_id", user_id).execute()
        if not member.data:
            raise ValueError("Not a member of this room")
        
        result = self.supabase.table("chat_room_members").select(
            "*, user:users!user_id(id, display_name, avatar_url)"
        ).eq("room_id", room_id).execute()
        
        return [
            {
                "user_id": m["user"]["id"],
                "display_name": m["user"]["display_name"],
                "avatar_url": m["user"].get("avatar_url"),
                "role": m["role"],
                "ai_mode": m["ai_mode"],
                "joined_at": m["joined_at"],
            }
            for m in result.data
        ] if result.data else []
    
    async def add_room_member(self, room_id: str, user_id: str, new_member_id: str) -> dict:
        """Add a member to a room"""
        # Verify membership and role
        member = self.supabase.table("chat_room_members").select("*").eq("room_id", room_id).eq("user_id", user_id).execute()
        if not member.data:
            raise ValueError("Not a member of this room")
        
        if member.data[0]["role"] not in ["owner", "admin"]:
            raise ValueError("Permission denied")
        
        # Add new member
        result = self.supabase.table("chat_room_members").insert({
            "room_id": room_id,
            "user_id": new_member_id,
            "role": "member",
        }).execute()
        
        if result.data:
            return result.data[0]
        raise ValueError("Failed to add member")
    
    # ==================== Message Management ====================

    async def _record_message_delivery(self, room_id: str, message_id: str, sender_id: Optional[str] = None, content: Optional[str] = None) -> None:
        """Update room/member read state after a message is inserted."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            room_update: dict = {"last_message_at": now}
            if content is not None:
                room_update["last_message_preview"] = build_message_preview(content)
            self.supabase.table("chat_rooms").update(room_update).eq("id", room_id).execute()

            members = self.supabase.table("chat_room_members").select(
                "id,user_id,unread_count"
            ).eq("room_id", room_id).execute()

            for member in members.data or []:
                if sender_id and member.get("user_id") == sender_id:
                    self.supabase.table("chat_room_members").update({
                        "last_read_at": now,
                        "last_read_message_id": message_id,
                        "unread_count": 0,
                    }).eq("id", member["id"]).execute()
                    continue

                current = member.get("unread_count") or 0
                self.supabase.table("chat_room_members").update({
                    "unread_count": current + 1,
                }).eq("id", member["id"]).execute()
        except Exception as exc:
            self.logger.warning("Unread counter update failed: %s", exc)
    
    async def send_message(self, room_id: str, sender_id: str, content: str, sender_type: str = "human", reply_to_id: str = None, created_at: str = None) -> dict:
        """Send a message to a room

        created_at: 明示指定時はその時刻で保存（既定はDBの now()）。並列保存パス
        （DAN_PARALLEL_SEND）は run 作成や CLI 起動の後に insert するため、DB任せだと
        メッセージの時刻が run より後に逆転し、フロントの時系列表示が崩れる。
        リクエスト到着時刻を渡して実際の送信時刻を保つ。
        """
        # Verify membership
        member = await self._execute_with_retry(
            "send_message.membership_check",
            lambda: self.supabase.table("chat_room_members").select("*").eq("room_id", room_id).eq("user_id", sender_id).execute(),
        )
        if not member.data:
            raise ValueError("Not a member of this room")

        # Get sender info
        sender = await self._execute_with_retry(
            "send_message.get_sender",
            lambda: self.supabase.table("users").select("display_name").eq("id", sender_id).execute(),
        )
        sender_name = sender.data[0]["display_name"] if sender.data else "Unknown"
        # 統合後: sender_id = users.id（done_user_idは不要）

        insert_data = {
            "room_id": room_id,
            "sender_id": sender_id,
            "sender_type": sender_type,
            "content": content,
        }
        if reply_to_id:
            insert_data["reply_to"] = reply_to_id
        if created_at:
            insert_data["created_at"] = created_at

        result = await self._execute_with_retry(
            "send_message.insert_message",
            lambda: self.supabase.table("chat_messages").insert(insert_data).execute(),
        )

        if result.data:
            msg = result.data[0]
            msg["sender_name"] = sender_name
            await self._record_message_delivery(room_id, msg["id"], sender_id=sender_id, content=content)
            
            # Phase 5A: メッセージ検知フック（AI有効ルームのみ）
            if sender_type == "human":
                await self._trigger_message_detection(
                    room_id=room_id,
                    message_id=msg["id"],
                    sender_id=sender_id,
                    user_id=sender_id,  # 統合後: sender_id = users.id
                    content=content,
                    sender_name=sender_name,
                )
                # チャットで送られたファイル(画像/動画/PDF等)を dan-notion の案件フォルダへ保存
                try:
                    await self._archive_chat_attachments(room_id, sender_id, msg["id"], content)
                except Exception:
                    import logging
                    logging.getLogger(__name__).warning("archive chat attachments failed", exc_info=True)

            return msg
        raise ValueError("Failed to send message")
    
    async def _archive_chat_attachments(self, room_id: str, user_id: str, message_id: str, content: str) -> None:
        """チャットで送られたファイル(/api/v1/files/<name>)を dan-notion の案件フォルダへ保存。

        部屋に紐づく project が分かれば その案件の種類別フォルダ(画像素材/動画素材/資料)へ、
        不明なら inbox へ。拡張子で種類判定。ベストエフォート。
        """
        import asyncio as _asyncio
        import re as _re

        files = _re.findall(r"/api/v1/files/([A-Za-z0-9._%\-]+)", content or "")
        if not files:
            return
        seen = set()
        files = [f for f in files if not (f in seen or seen.add(f))]

        # 部屋→project 解決
        def _project():
            r = self.supabase.table("projects").select("id,title").eq("room_id", room_id).limit(1).execute()
            return (r.data[0] if r.data else None)
        proj = await _asyncio.to_thread(_project)
        project_id = proj["id"] if proj else None
        project_title = proj.get("title") if proj else None

        def _ext_type(name: str) -> str:
            n = name.lower()
            if n.rsplit(".", 1)[-1] in ("png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "heic"):
                return "image"
            if n.rsplit(".", 1)[-1] in ("mp4", "mov", "webm", "avi", "mkv", "m4v"):
                return "video"
            if n.endswith(".pdf"):
                return "pdf"
            return "file"

        from app.services.dan_notion_service import get_dan_notion_service
        svc = get_dan_notion_service()

        def _file_one(fname: str):
            asset = {"url": f"/api/v1/files/{fname}", "prompt": "", "original_name": fname}
            svc.add_asset_block_to_project(
                user_id=user_id, project_id=str(project_id) if project_id else None,
                project_title=project_title, asset=asset,
                asset_type=_ext_type(fname), source_id=f"{message_id}:{fname}",
            )

        for fname in files:
            try:
                await _asyncio.to_thread(_file_one, fname)
            except Exception:
                pass

    async def _trigger_message_detection(
        self,
        room_id: str,
        message_id: str,
        sender_id: str,
        user_id: str,  # 統合後: sender_id = users.id
        content: str,
        sender_name: str,
    ) -> None:
        """
        メッセージ検知をトリガー（Phase 5A）
        AI設定が有効なルームのみ検知
        """
        try:
            # AI設定を確認
            ai_settings = self.supabase.table("chat_ai_settings").select("*").eq("room_id", room_id).execute()
            
            if not ai_settings.data:
                return
            
            settings = ai_settings.data[0]
            if not settings.get("enabled", False):
                return
            
            # 統合後: 全チャットユーザーはDoneユーザーなのでチェック不要
            
            # メッセージ検知サービスを呼び出し
            from app.services.message_detection import get_detection_service
            from app.models.detection_schemas import MessageSource
            
            detection_service = get_detection_service()
            await detection_service.detect_message(
                user_id=user_id,
                source=MessageSource.DONE_CHAT,
                content=content,
                source_id=message_id,
                sender_info={
                    "sender_id": sender_id,
                    "sender_name": sender_name,
                    "room_id": room_id,
                },
                metadata={
                    "room_id": room_id,
                    "ai_mode": settings.get("mode", "assist"),
                },
            )
        except Exception as e:
            # 検知失敗してもメッセージ送信は成功させる
            import logging
            logging.getLogger(__name__).warning(f"Message detection failed: {e}")
    
    async def get_messages(self, room_id: str, user_id: str, limit: int = 50, before: Optional[str] = None) -> list[dict]:
        """Get messages from a room"""
        # Verify membership
        member = self.supabase.table("chat_room_members").select("*").eq("room_id", room_id).eq("user_id", user_id).execute()
        if not member.data:
            raise ValueError("Not a member of this room")
        
        query = self.supabase.table("chat_messages").select(
            "*, sender:users!sender_id(id, display_name, avatar_url)"
        ).eq("room_id", room_id).order("created_at", desc=True).limit(limit)

        if before:
            query = query.lt("created_at", before)

        result = await self._execute_with_retry(
            "get_messages.fetch_messages",
            lambda: query.execute(),
        )

        # 返信先メッセージを一括取得
        reply_to_ids = [msg["reply_to"] for msg in (result.data or []) if msg.get("reply_to")]
        reply_map = {}
        if reply_to_ids:
            try:
                unique_ids = list(set(reply_to_ids))
                replied_result = self.supabase.table("chat_messages").select(
                    "id, sender_type, content, created_at, sender:users!sender_id(display_name)"
                ).in_("id", unique_ids).execute()
                for rm in (replied_result.data or []):
                    reply_map[rm["id"]] = {
                        "id": rm["id"],
                        "sender_name": rm["sender"]["display_name"] if rm.get("sender") else "Unknown",
                        "sender_type": rm["sender_type"],
                        "content": rm["content"][:200],
                        "created_at": rm["created_at"],
                    }
            except Exception:
                pass

        messages = []
        for msg in result.data or []:
            message_dict = {
                "id": msg["id"],
                "room_id": msg["room_id"],
                "sender_id": msg["sender_id"],
                "sender_name": msg["sender"]["display_name"] if msg.get("sender") else "Unknown",
                "sender_type": msg["sender_type"],
                "content": msg["content"],
                "created_at": msg["created_at"],
            }
            # ai_contextがあれば追加（reasoning_steps等）
            if msg.get("ai_context"):
                message_dict["ai_context"] = msg["ai_context"]
            # reply_to情報
            if msg.get("reply_to"):
                message_dict["reply_to_id"] = msg["reply_to"]
                if msg["reply_to"] in reply_map:
                    message_dict["reply_to_message"] = reply_map[msg["reply_to"]]
            messages.append(message_dict)

        return messages

    async def search_messages(self, room_id: str, user_id: str, query: str, limit: int = 50) -> list[dict]:
        """Full-history keyword search within a room's messages (content ILIKE).

        Unlike get_messages (which only returns the newest N), this scans the
        entire history so the user can find something said long ago. Newest hits
        first. Returns the same message shape so the UI can render + jump to them.
        """
        # Verify membership
        member = self.supabase.table("chat_room_members").select("*").eq("room_id", room_id).eq("user_id", user_id).execute()
        if not member.data:
            raise ValueError("Not a member of this room")

        q = (query or "").strip()
        if not q:
            return []
        # Escape ILIKE wildcards so the user's literal text is matched verbatim.
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

        search_q = self.supabase.table("chat_messages").select(
            "*, sender:users!sender_id(id, display_name, avatar_url)"
        ).eq("room_id", room_id).ilike("content", f"%{escaped}%").order("created_at", desc=True).limit(limit)

        result = await self._execute_with_retry(
            "search_messages.fetch_messages",
            lambda: search_q.execute(),
        )

        messages = []
        for msg in result.data or []:
            message_dict = {
                "id": msg["id"],
                "room_id": msg["room_id"],
                "sender_id": msg["sender_id"],
                "sender_name": msg["sender"]["display_name"] if msg.get("sender") else "Unknown",
                "sender_type": msg["sender_type"],
                "content": msg["content"],
                "created_at": msg["created_at"],
            }
            if msg.get("ai_context"):
                message_dict["ai_context"] = msg["ai_context"]
            messages.append(message_dict)

        return messages

    async def mark_as_read(self, room_id: str, user_id: str) -> bool:
        """Mark messages as read"""
        latest = self.supabase.table("chat_messages").select("id").eq(
            "room_id", room_id
        ).order("created_at", desc=True).limit(1).execute()
        update_data = {
            "last_read_at": datetime.now(timezone.utc).isoformat(),
            "unread_count": 0,
        }
        if latest.data:
            update_data["last_read_message_id"] = latest.data[0]["id"]

        result = self.supabase.table("chat_room_members").update(update_data).eq("room_id", room_id).eq("user_id", user_id).execute()
        
        return bool(result.data)
    
    # ==================== AI Settings ====================
    
    async def get_ai_settings(self, room_id: str, user_id: str) -> Optional[dict]:
        """Get AI settings for a room"""
        # Verify membership
        member = self.supabase.table("chat_room_members").select("*").eq("room_id", room_id).eq("user_id", user_id).execute()
        if not member.data:
            raise ValueError("Not a member of this room")
        
        result = self.supabase.table("chat_ai_settings").select("*").eq("room_id", room_id).execute()
        return result.data[0] if result.data else None
    
    async def update_ai_settings(
        self, 
        room_id: str, 
        user_id: str, 
        enabled: Optional[bool] = None,
        mode: Optional[str] = None,
        personality: Optional[str] = None,
        auto_reply_delay_ms: Optional[int] = None,
    ) -> Optional[dict]:
        """Update AI settings for a room"""
        # Verify membership
        member = self.supabase.table("chat_room_members").select("*").eq("room_id", room_id).eq("user_id", user_id).execute()
        if not member.data:
            raise ValueError("Not a member of this room")
        
        update_data = {}
        if enabled is not None:
            update_data["enabled"] = enabled
        if mode is not None:
            update_data["mode"] = mode
        if personality is not None:
            update_data["personality"] = personality
        if auto_reply_delay_ms is not None:
            update_data["auto_reply_delay_ms"] = auto_reply_delay_ms
        
        if update_data:
            result = self.supabase.table("chat_ai_settings").update(update_data).eq("room_id", room_id).execute()
            return result.data[0] if result.data else None
        
        return await self.get_ai_settings(room_id, user_id)
    
    async def get_ai_summary(self, room_id: str, user_id: str) -> dict:
        """Get AI summary of recent conversation"""
        # Verify membership
        member = self.supabase.table("chat_room_members").select("*").eq("room_id", room_id).eq("user_id", user_id).execute()
        if not member.data:
            raise ValueError("Not a member of this room")
        
        # Get recent messages
        messages = await self.get_messages(room_id, user_id, limit=50)
        
        if not messages:
            return {"summary": "No messages yet.", "message_count": 0}
        
        # TODO: Use Claude to generate summary
        # For now, return a simple summary
        return {
            "summary": f"Recent conversation with {len(messages)} messages.",
            "message_count": len(messages),
            "last_message_at": messages[0]["created_at"] if messages else None,
        }

    async def is_room_member(self, room_id: str, user_id: str) -> bool:
        """Check if user is a member of the room"""
        member = self.supabase.table("chat_room_members").select("id").eq("room_id", room_id).eq("user_id", user_id).execute()
        return bool(member.data)
    
    # ==================== System Messages (Phase 10) ====================
    
    async def send_system_message(
        self,
        user_id: str,
        message: str,
        room_type: str = "ai",
    ) -> Optional[dict]:
        """
        システム/AIからユーザーにメッセージを送信
        
        Args:
            user_id: 対象ユーザーID
            message: メッセージ内容
            room_type: ルームタイプ（ai=AIアシスタントルーム）
            
        Returns:
            送信されたメッセージ
        """
        try:
            # 1. ユーザーのAIルームを取得または作成
            rooms = self.supabase.table("chat_rooms").select("*").eq(
                "room_type", room_type
            ).execute()
            
            ai_room = None
            for room in rooms.data or []:
                # このルームのメンバーを確認
                members = self.supabase.table("chat_room_members").select("user_id").eq(
                    "room_id", room["id"]
                ).execute()
                
                member_ids = [m["user_id"] for m in members.data or []]
                if user_id in member_ids:
                    ai_room = room
                    break
            
            if not ai_room:
                # AIルームがない場合は作成
                room_result = self.supabase.table("chat_rooms").insert({
                    "name": "AI Assistant",
                    "room_type": room_type,
                }).execute()
                
                if room_result.data:
                    ai_room = room_result.data[0]
                    # ユーザーをメンバーに追加
                    self.supabase.table("chat_room_members").insert({
                        "room_id": ai_room["id"],
                        "user_id": user_id,
                    }).execute()
                else:
                    return None
            
            # 2. AIとしてメッセージを送信
            # AI送信者はシステム用の固定ID（または最初のメンバー）
            message_result = self.supabase.table("chat_messages").insert({
                "room_id": ai_room["id"],
                "sender_id": user_id,  # ユーザー自身のルームに送信
                "content": message,
                "message_type": "system",  # システムメッセージとして区別
            }).execute()
            
            if message_result.data:
                return message_result.data[0]
            
            return None
            
        except Exception as e:
            import logging
            logging.error(f"Failed to send system message: {e}")
            return None


    # ==================== Dan Page (Phase 2E) ====================
    
    async def get_or_create_dan_room(self, user_id: str) -> dict:
        """
        ユーザーのダンルームを取得または作成
        
        Args:
            user_id: ユーザーID
            
        Returns:
            ダンルーム情報
        """
        # 1. まずユーザーのdan_room_idを確認
        user = self.supabase.table("users").select("dan_room_id").eq("id", user_id).execute()
        
        if user.data and user.data[0].get("dan_room_id"):
            room_id = user.data[0]["dan_room_id"]
            room = self.supabase.table("chat_rooms").select("*").eq("id", room_id).execute()
            if room.data:
                return await self._enrich_dan_room(room.data[0], user_id)
        
        # 2. dan_room_idがない場合、danタイプのルームを検索
        rooms = await self.get_rooms(user_id)
        for room in rooms:
            if room.get("type") == "dan":
                # 見つかった場合、dan_room_idを更新
                self.supabase.table("users").update({"dan_room_id": room["id"]}).eq("id", user_id).execute()
                return await self._enrich_dan_room(room, user_id)
        
        # 3. ダンルームがない場合、作成
        room = await self._create_dan_room(user_id)
        return await self._enrich_dan_room(room, user_id)
    
    async def _create_dan_room(self, user_id: str) -> dict:
        """ダンルームを作成（内部用）"""
        # ルーム作成
        room_result = self.supabase.table("chat_rooms").insert({
            "name": "ダン",
            "type": "dan",
        }).execute()
        
        if not room_result.data:
            raise ValueError("Failed to create Dan room")
        
        room = room_result.data[0]
        
        # メンバー追加
        self.supabase.table("chat_room_members").insert({
            "room_id": room["id"],
            "user_id": user_id,
            "role": "owner",
            "ai_mode": "auto",
        }).execute()
        
        # AI設定（ダンルームはデフォルトで有効）
        self.supabase.table("chat_ai_settings").insert({
            "room_id": room["id"],
            "enabled": True,
            "mode": "auto",
            "personality": "あなたはダン（Dan）、ユーザーの専属AIアシスタントです。丁寧で親しみやすい口調で話します。",
        }).execute()
        
        # ユーザーのdan_room_id更新
        self.supabase.table("users").update({"dan_room_id": room["id"]}).eq("id", user_id).execute()
        
        return room
    
    async def _enrich_dan_room(self, room: dict, user_id: str) -> dict:
        """ダンルーム情報を拡充"""
        room_id = room["id"]
        
        # 未読メッセージ数を取得
        member = self.supabase.table("chat_room_members").select("unread_count").eq("room_id", room_id).eq("user_id", user_id).execute()
        unread_count = member.data[0].get("unread_count", 0) if member.data else 0
        
        # 保留中の提案数を取得
        pending = self.supabase.table("dan_proposals").select("id", count="exact").eq("user_id", user_id).eq("status", "pending").execute()
        pending_count = pending.count or 0
        
        # 最後のメッセージ日時
        room_state = self.supabase.table("chat_rooms").select("last_message_at,updated_at").eq("id", room_id).limit(1).execute()
        last_message_at = None
        if room_state.data:
            last_message_at = room_state.data[0].get("last_message_at") or room_state.data[0].get("updated_at")
        
        return {
            "id": room_id,
            "name": room.get("name", "ダン"),
            "type": "dan",
            "unread_count": unread_count,
            "pending_proposals_count": pending_count,
            "last_message_at": last_message_at,
            "created_at": room["created_at"],
        }
    
    async def send_dan_message(self, user_id: str, content: str) -> dict:
        """
        ダンルームにメッセージを送信
        
        Args:
            user_id: ユーザーID
            content: メッセージ内容
            
        Returns:
            送信されたメッセージ
        """
        dan_room = await self.get_or_create_dan_room(user_id)
        return await self.send_message(dan_room["id"], user_id, content, sender_type="human")
    
    async def send_dan_ai_message(
        self,
        user_id: str,
        content: str,
        reasoning_steps: list[str] = None,
        room_id: str = None,
        reasoning_full: list[str] = None,
    ) -> dict:
        """
        ダンからユーザーにメッセージを送信（AI側）

        Args:
            user_id: 対象ユーザーID
            content: メッセージ内容
            reasoning_steps: 推論過程の短いラベル（プロセスモニター表示用）
            room_id: 送信先ルームID（指定しない場合は現在のDanルーム）
            reasoning_full: 推論過程の全文（展開表示用）

        Returns:
            送信されたメッセージ
        """
        if room_id:
            target_room_id = room_id
        else:
            dan_room = await self.get_or_create_dan_room(user_id)
            target_room_id = dan_room["id"]

        # ai_contextを構築
        ai_context = None
        if reasoning_steps:
            ai_context = {"reasoning_steps": reasoning_steps}
            if reasoning_full:
                ai_context["reasoning_full"] = reasoning_full
        
        # AIからのメッセージとして送信
        insert_data = {
            "room_id": target_room_id,
            "sender_id": None,  # AIなのでsender_idはnull
            "sender_type": "ai",
            "content": content,
        }
        if ai_context:
            insert_data["ai_context"] = ai_context
        
        result = await self._execute_with_retry(
            "send_dan_ai_message.insert_message",
            lambda: self.supabase.table("chat_messages").insert(insert_data).execute(),
        )
        
        if result.data:
            msg = result.data[0]
            msg["sender_name"] = "ダン"
            await self._record_message_delivery(target_room_id, msg["id"], content=content)
            return msg
        raise ValueError("Failed to send AI message")
    
    # ==================== Chat Sessions ====================
    
    async def get_dan_sessions(self, user_id: str) -> dict:
        """
        ユーザーのダンセッション一覧を取得（最適化版）
        
        Args:
            user_id: ユーザーID
            
        Returns:
            セッション一覧と現在のセッションID
        """
        # ユーザーの現在のセッションIDを取得
        user = self.supabase.table("users").select("dan_room_id").eq("id", user_id).execute()
        current_session_id = user.data[0].get("dan_room_id") if user.data else None
        
        # ユーザーのダンセッション一覧を取得（JOINで一括取得）
        members = self.supabase.table("chat_room_members").select(
            "room_id, chat_rooms!inner(id, name, type, created_at)"
        ).eq("user_id", user_id).execute()
        
        # danタイプのルームIDを収集
        dan_room_ids = []
        room_info_map = {}
        for member in members.data or []:
            room = member.get("chat_rooms", {})
            if room.get("type") == "dan":
                room_id = room["id"]
                dan_room_ids.append(room_id)
                room_info_map[room_id] = {
                    "id": room_id,
                    "title": room.get("name", "新しい会話"),
                    "created_at": room["created_at"],
                }
        
        if not dan_room_ids:
            return {
                "sessions": [],
                "current_session_id": current_session_id,
            }
        
        # 全ルームのメッセージ件数を一括取得（RPCまたはグループ化クエリ）
        # Supabaseでは直接GROUP BYができないため、個別に取得するがキャッシュを活用
        # ここでは最適化として、最新のメッセージのみを取得し件数は概算
        
        # 全ルームの最新メッセージを一括取得
        all_messages = self.supabase.table("chat_messages").select(
            "room_id, content, created_at"
        ).in_("room_id", dan_room_ids).order(
            "created_at", desc=True
        ).execute()
        
        # ルームごとに整理
        room_messages = {}
        room_msg_counts = {}
        for msg in all_messages.data or []:
            room_id = msg["room_id"]
            if room_id not in room_messages:
                room_messages[room_id] = msg
            room_msg_counts[room_id] = room_msg_counts.get(room_id, 0) + 1
        
        sessions = []
        for room_id in dan_room_ids:
            room = room_info_map[room_id]
            msg = room_messages.get(room_id)
            
            last_message = None
            last_message_at = None
            if msg:
                last_message = msg["content"][:50]
                if len(msg["content"]) > 50:
                    last_message += "..."
                last_message_at = msg["created_at"]
            
            sessions.append({
                "id": room_id,
                "title": room["title"],
                "last_message": last_message,
                "last_message_at": last_message_at,
                "message_count": room_msg_counts.get(room_id, 0),
                "created_at": room["created_at"],
            })
        
        # 最終メッセージ日時で降順ソート（メッセージがない場合は作成日時）
        sessions.sort(
            key=lambda x: x["last_message_at"] or x["created_at"], 
            reverse=True
        )
        
        return {
            "sessions": sessions,
            "current_session_id": current_session_id,
        }
    
    async def create_dan_session(self, user_id: str, title: str = "新しい会話") -> dict:
        """
        ダンセッションを取得（単一セッションモード）

        注意: 単一セッションモードでは新規作成せず、既存のメインセッションを返す。
        将来マルチセッションに戻す場合は、この制限を解除する。

        Args:
            user_id: ユーザーID
            title: セッションタイトル（現在は無視）

        Returns:
            既存のメインセッション情報
        """
        # 単一セッションモード: 既存のメインセッションを返す
        main_room = await self.get_or_create_dan_room(user_id)

        return {
            "id": main_room["id"],
            "title": main_room.get("name", "ダンとの会話"),
            "created_at": main_room.get("created_at"),
        }

        # === 以下は将来マルチセッションに戻す場合のコード ===
        # # 新しいダンルームを作成
        # room_result = self.supabase.table("chat_rooms").insert({
        #     "name": title,
        #     "type": "dan",
        # }).execute()
        #
        # if not room_result.data:
        #     raise ValueError("Failed to create session")
        #
        # room = room_result.data[0]
        #
        # # メンバー追加
        # self.supabase.table("chat_room_members").insert({
        #     "room_id": room["id"],
        #     "user_id": user_id,
        #     "role": "owner",
        #     "ai_mode": "auto",
        # }).execute()
        #
        # # AI設定
        # self.supabase.table("chat_ai_settings").insert({
        #     "room_id": room["id"],
        #     "enabled": True,
        #     "mode": "auto",
        #     "personality": "あなたはダン（Dan）、ユーザーの専属AIアシスタントです。丁寧で親しみやすい口調で話します。",
        # }).execute()
        #
        # # ユーザーのdan_room_idを更新（新しいセッションをアクティブに）
        # self.supabase.table("users").update({"dan_room_id": room["id"]}).eq("id", user_id).execute()

    async def activate_dan_session(self, user_id: str, session_id: str) -> dict:
        """
        ダンセッションをアクティブにする
        
        Args:
            user_id: ユーザーID
            session_id: セッションID
            
        Returns:
            成功フラグとセッションID
        """
        # セッションの存在とユーザーの所有を確認
        member = self.supabase.table("chat_room_members").select(
            "room_id"
        ).eq("room_id", session_id).eq("user_id", user_id).execute()
        
        if not member.data:
            raise ValueError("Session not found or access denied")
        
        # ルームタイプがdanであることを確認
        room = self.supabase.table("chat_rooms").select("type").eq("id", session_id).execute()
        if not room.data or room.data[0].get("type") != "dan":
            raise ValueError("Invalid session type")
        
        # ユーザーのdan_room_idを更新
        self.supabase.table("users").update({"dan_room_id": session_id}).eq("id", user_id).execute()
        
        return {
            "success": True,
            "session_id": session_id,
        }
    
    async def update_dan_session_title(self, user_id: str, session_id: str, title: str) -> dict:
        """
        セッションタイトルを更新
        
        Args:
            user_id: ユーザーID
            session_id: セッションID
            title: 新しいタイトル
            
        Returns:
            更新されたセッション情報
        """
        # セッションの所有を確認
        member = self.supabase.table("chat_room_members").select(
            "room_id"
        ).eq("room_id", session_id).eq("user_id", user_id).execute()
        
        if not member.data:
            raise ValueError("Session not found or access denied")
        
        # タイトル更新
        result = self.supabase.table("chat_rooms").update({
            "name": title
        }).eq("id", session_id).execute()
        
        if not result.data:
            raise ValueError("Failed to update session title")
        
        return {
            "id": session_id,
            "title": title,
        }
    
    async def delete_dan_session(self, user_id: str, session_id: str) -> dict:
        """
        ダンセッションを削除
        
        Args:
            user_id: ユーザーID
            session_id: セッションID
            
        Returns:
            成功フラグと新しいアクティブセッションID（あれば）
        """
        # セッションの所有を確認
        member = self.supabase.table("chat_room_members").select(
            "room_id"
        ).eq("room_id", session_id).eq("user_id", user_id).execute()
        
        if not member.data:
            raise ValueError("Session not found or access denied")
        
        # 現在アクティブなセッションかチェック
        user = self.supabase.table("users").select("dan_room_id").eq("id", user_id).execute()
        is_active_session = user.data and user.data[0].get("dan_room_id") == session_id
        
        new_active_session_id = None
        
        # アクティブなセッションを削除する場合、別のセッションに切り替える
        if is_active_session:
            # 全セッションを取得（最終メッセージ日時順）
            sessions_data = await self.get_dan_sessions(user_id)
            sessions = sessions_data["sessions"]
            
            # 削除対象のセッションのインデックスを見つける
            current_index = -1
            for i, s in enumerate(sessions):
                if s["id"] == session_id:
                    current_index = i
                    break
            
            if current_index != -1 and len(sessions) > 1:
                # 1つ上のセッション（インデックスが小さい方）を優先、なければ1つ下
                if current_index > 0:
                    new_active_session_id = sessions[current_index - 1]["id"]
                else:
                    new_active_session_id = sessions[current_index + 1]["id"]
                
                # 新しいセッションをアクティブに設定
                self.supabase.table("users").update(
                    {"dan_room_id": new_active_session_id}
                ).eq("id", user_id).execute()
            elif len(sessions) <= 1:
                # 最後のセッションを削除する場合、新しいセッションを作成
                new_session = await self.create_dan_session(user_id, "新しい会話")
                new_active_session_id = new_session["id"]
        
        # メッセージを削除
        self.supabase.table("chat_messages").delete().eq("room_id", session_id).execute()
        
        # AI設定を削除
        self.supabase.table("chat_ai_settings").delete().eq("room_id", session_id).execute()
        
        # メンバーを削除
        self.supabase.table("chat_room_members").delete().eq("room_id", session_id).execute()
        
        # ルームを削除
        self.supabase.table("chat_rooms").delete().eq("id", session_id).execute()
        
        return {
            "success": True,
            "new_active_session_id": new_active_session_id,
        }
    
    # ==================== Observer Notifications ====================

    async def get_proposals(
        self,
        user_id: str,
        status: Optional[str] = None,
        limit: int = 50,
        types: Optional[list[str]] = None,
        exclude_types: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        ユーザーの提案一覧を取得

        Args:
            user_id: ユーザーID
            status: フィルターするステータス（None=全て）
            limit: 取得件数
            types: この type のみに絞る（None=全て）
            exclude_types: この type を除外する（例: ["observation"] で情報通知を除く）

        Returns:
            提案リスト
        """
        query = self.supabase.table("dan_proposals").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(limit)

        if status:
            query = query.eq("status", status)
        if types:
            query = query.in_("type", types)
        if exclude_types:
            # PostgREST: not.in.(a,b) 形式
            query = query.not_.in_("type", exclude_types)

        result = query.execute()
        
        proposals = []
        for p in result.data or []:
            proposals.append(await self._enrich_proposal(p))
        
        return proposals
    
    async def get_proposal(self, proposal_id: str, user_id: str) -> Optional[dict]:
        """提案を取得"""
        result = self.supabase.table("dan_proposals").select("*").eq("id", proposal_id).eq("user_id", user_id).execute()
        
        if result.data:
            return await self._enrich_proposal(result.data[0])
        return None
    
    async def _enrich_proposal(self, proposal: dict) -> dict:
        """提案情報を拡充"""
        # 元のルーム名を取得
        source_room_name = None
        if proposal.get("source_room_id"):
            room = self.supabase.table("chat_rooms").select("name").eq("id", proposal["source_room_id"]).execute()
            if room.data:
                source_room_name = room.data[0].get("name")
        
        return {
            "id": proposal["id"],
            "user_id": proposal["user_id"],
            "type": proposal["type"],
            "status": proposal["status"],
            "title": proposal["title"],
            "content": proposal["content"],
            "source_room_id": proposal.get("source_room_id"),
            "source_room_name": source_room_name,
            "source_message_id": proposal.get("source_message_id"),
            "action_data": proposal.get("action_data"),
            "expires_at": proposal.get("expires_at"),
            "created_at": proposal["created_at"],
            "responded_at": proposal.get("responded_at"),
        }
    
    async def respond_to_proposal(
        self,
        proposal_id: str,
        user_id: str,
        action: str,
        edited_content: Optional[str] = None,
    ) -> dict:
        """
        提案に対応（承認/却下/編集）
        
        Args:
            proposal_id: 提案ID
            user_id: ユーザーID
            action: アクション（approve, reject, edit）
            edited_content: 編集後の内容（action=editの場合）
            
        Returns:
            更新された提案
        """
        # 提案を取得
        proposal = await self.get_proposal(proposal_id, user_id)
        if not proposal:
            raise ValueError("Proposal not found")
        
        if proposal["status"] != "pending":
            raise ValueError("Proposal is not pending")
        
        # ステータス更新
        new_status = "approved" if action in ["approve", "edit"] else "rejected"
        update_data = {
            "status": new_status,
            "responded_at": datetime.now(timezone.utc).isoformat(),
        }
        
        if action == "edit" and edited_content:
            update_data["content"] = edited_content
        
        result = self.supabase.table("dan_proposals").update(update_data).eq("id", proposal_id).execute()
        
        if not result.data:
            raise ValueError("Failed to update proposal")
        
        updated_proposal = await self.get_proposal(proposal_id, user_id)
        
        # 承認された場合、アクションを実行
        if new_status == "approved" and proposal.get("type") == "reply":
            await self._execute_reply_proposal(proposal, edited_content or proposal["content"])
        
        return updated_proposal
    
    async def _execute_reply_proposal(self, proposal: dict, content: str) -> None:
        """返信提案を実行。

        - 外部チャネル（フォーム/メール返信）の場合は実際に外部送信する。
        - それ以外は従来通り、元チャットルームにメッセージを投稿する。
        """
        import logging

        action_data = proposal.get("action_data") or {}
        action = action_data.get("action")
        channel = action_data.get("channel")
        user_id = proposal["user_id"]

        # 外部メール返信（フォーム問い合わせへの返信など）
        if action == "send_inquiry_reply" or channel == "email":
            try:
                await self._send_external_email_reply(proposal, content, action_data)
            except Exception as e:
                logging.error(f"Failed to send external email reply: {e}")
            return

        # 従来: 元チャットルームへ投稿
        source_room_id = proposal.get("source_room_id")
        if source_room_id:
            try:
                await self.send_message(source_room_id, user_id, content, sender_type="human")
            except Exception as e:
                logging.error(f"Failed to execute reply proposal: {e}")

    async def _send_external_email_reply(self, proposal: dict, content: str, action_data: dict) -> None:
        """承認された返信案を SMTP で外部送信し、必要なら inquiry のステータスを更新する。"""
        import asyncio as _asyncio
        import logging

        from app.config import settings

        to_addr = action_data.get("to")
        subject = action_data.get("subject") or "Re: お問い合わせ"
        from_name = action_data.get("reply_from_name") or settings.DAN_DEFAULT_FROM_NAME
        if not to_addr:
            logging.warning("external email reply: 宛先メール無し proposal=%s", proposal.get("id"))
            return

        from app.services.inquiry_notify import _send_smtp, OWNER_REPLY_TO

        await _asyncio.to_thread(
            _send_smtp, to_addr, subject, content,
            from_name=from_name, reply_to=OWNER_REPLY_TO,
        )
        logging.info("external email reply sent to=%s subject=%s", to_addr, subject)

        # inquiry を replied に
        inquiry_id = action_data.get("inquiry_id")
        if inquiry_id:
            try:
                await _asyncio.to_thread(
                    lambda: self.supabase.table("inquiries").update({"status": "replied"}).eq("id", inquiry_id).execute()
                )
            except Exception as e:
                logging.warning("inquiry status update failed: %s", e)
    
    async def instruct_proposal(self, proposal_id: str, user_id: str, instruction: str) -> dict:
        """通知タブの提案に対するユーザーの自由指示を処理する。

        - revise: 返信案の修正依頼 → 草案を書き換えて提案を更新
        - delegate: 別作業の依頼(他者へメール/調査等) → ダンのメインチャットに文脈付きで投げて実行
        - answer: 質問 → その場で回答

        Returns: {"mode", "message", "proposal"(reviseのみ)}
        """
        import asyncio as _asyncio
        import json
        import logging

        proposal = await self.get_proposal(proposal_id, user_id)
        if not proposal:
            raise ValueError("Proposal not found")

        ad = proposal.get("action_data") or {}
        summary = ad.get("summary") or ""
        from_sender = ad.get("from_sender") or ""
        current = proposal.get("content") or ""

        try:
            from app.agent.cli_runner import run_oneshot_cli
        except Exception:
            return {"mode": "answer", "message": "今は指示を処理できません（CLI未利用）。"}

        prompt = (
            "あなたは運用担当者のアシスタントです。ユーザーが『返信案の提案』に対して指示を出しました。\n"
            "指示を分類し、次のJSONだけを出力してください（前後に文章を付けない）:\n"
            '{"mode":"revise|delegate|answer","reply":"<modeがreviseの時のみ:指示を反映した新しい返信本文の全文>","message":"<ユーザーへの短い一言(日本語)>"}\n'
            "- revise: 返信案そのものの修正（言い回し変更/追記/トーン/短縮など）。replyに修正後の本文全体、messageは「〜に書き換えました」。\n"
            "- delegate: 返信案の修正ではない別の作業依頼（他の人にメール/調査/電話など）。messageは何をするかの確認。\n"
            "- answer: 質問への回答。messageに回答。\n\n"
            f"--- 提案情報 ---\n元メール概要: {summary}\n差出人: {from_sender}\n"
            f"現在の返信案:\n{current}\n\n--- ユーザーの指示 ---\n{instruction}\n"
        )
        raw = await _asyncio.to_thread(run_oneshot_cli, prompt, "sonnet", 90)

        data = None
        if raw:
            try:
                data = json.loads(raw)
            except Exception:
                import re as _re
                m = _re.search(r"\{.*\}", raw, _re.DOTALL)
                if m:
                    try:
                        data = json.loads(m.group(0))
                    except Exception:
                        data = None
        if not data or data.get("mode") not in ("revise", "delegate", "answer"):
            return {"mode": "answer", "message": (raw or "うまく解釈できませんでした。もう一度お願いします。")[:600]}

        mode = data["mode"]
        if mode == "revise" and data.get("reply"):
            self.supabase.table("dan_proposals").update({"content": data["reply"]}).eq("id", proposal_id).execute()
            updated = await self.get_proposal(proposal_id, user_id)
            return {"mode": "revise", "message": data.get("message") or "返信案を書き換えました。", "proposal": updated}

        if mode == "delegate":
            try:
                await self._delegate_to_dan(user_id, proposal, instruction)
            except Exception:
                logging.exception("delegate to dan failed")
                return {"mode": "answer", "message": "依頼の起動に失敗しました。メインチャットで直接お願いします。"}
            return {"mode": "delegate", "message": data.get("message") or "ダンに依頼しました。メインチャットで対応します。"}

        return {"mode": "answer", "message": data.get("message") or "（回答が空でした）"}

    async def _delegate_to_dan(self, user_id: str, proposal: dict, instruction: str) -> None:
        """提案の文脈＋指示をダンのメインチャットに投げ、エージェントを背景起動する。"""
        import asyncio as _asyncio
        import logging

        dan_room = await self.get_or_create_dan_room(user_id)
        room_id = dan_room["id"]
        ad = proposal.get("action_data") or {}
        content = (
            f"[通知タブの提案「{proposal.get('title')}」についての指示]\n"
            f"元メール概要: {ad.get('summary') or '-'}\n"
            f"差出人: {ad.get('from_sender') or '-'}\n"
            f"現在の返信案:\n{proposal.get('content') or '-'}\n\n"
            f"ユーザーの指示: {instruction}\n\n"
            f"この指示に従って対応し、結果を日本語で報告してください。"
            f"メール送信が必要なら email-send スキルを使ってください。"
        )

        async def _run():
            try:
                from app.agent.cli_runner import process_message_cli
                async for _ev in process_message_cli(
                    room_id=room_id, user_id=user_id, content=content,
                    project_id=None, run_id=None,
                ):
                    pass
            except Exception:
                logging.exception("delegate agent run failed")

        _asyncio.create_task(_run())

    async def get_pending_proposals_count(
        self, user_id: str, exclude_types: Optional[list[str]] = None
    ) -> int:
        """保留中の提案数を取得（exclude_types で情報通知などを除外可能）"""
        query = self.supabase.table("dan_proposals").select("id", count="exact").eq("user_id", user_id).eq("status", "pending")
        if exclude_types:
            query = query.not_.in_("type", exclude_types)
        result = query.execute()
        return result.count or 0


def get_chat_service() -> ChatService:
    """ChatServiceのシングルトンインスタンスを取得"""
    return ChatService()

