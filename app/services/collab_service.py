"""
Collaboration Service - Business Logic for Collab Rooms
"""
from typing import Optional, List
from datetime import datetime, timedelta, timezone
import secrets
import logging
import random

from app.services.supabase_client import get_supabase_client


def generate_invite_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


class CollabService:
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _is_transient_error(exc: Exception) -> bool:
        text = str(exc).lower()
        markers = ("server disconnected", "remoteprotocolerror", "read timed out",
                   "connection reset", "connection aborted", "temporarily unavailable")
        return any(m in text for m in markers)

    async def _retry(self, operation: str, fn, retries: int = 2, base_delay: float = 0.2):
        import asyncio
        attempt = 0
        while True:
            try:
                return fn()
            except Exception as exc:
                if attempt >= retries or not self._is_transient_error(exc):
                    raise
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.15)
                self.logger.warning("Transient error on %s (attempt %s): %s", operation, attempt + 1, exc)
                await asyncio.sleep(delay)
                attempt += 1

    # ==================== Rooms ====================

    async def create_room(self, owner_id: str, title: str, description: str = None,
                          project_ref: str = None, ai_auto_assist: bool = True,
                          ai_assist_config: dict = None,
                          origin_chat_room_id: str = None) -> dict:
        data = {
            "owner_id": owner_id,
            "title": title,
            "description": description,
            "project_ref": project_ref,
            "ai_auto_assist": ai_auto_assist,
        }
        if ai_assist_config:
            data["ai_assist_config"] = ai_assist_config
        # UI（新しいルーム）から紐づけ先を選んだ場合。ダン自動対応が有効になる
        if origin_chat_room_id:
            data["origin_chat_room_id"] = origin_chat_room_id
            data["origin_kind"] = "done_chat"

        result = await self._retry("create_room",
            lambda: self.supabase.table("collab_rooms").insert(data).execute())
        return result.data[0]

    async def get_room(self, room_id: str) -> Optional[dict]:
        result = await self._retry("get_room",
            lambda: self.supabase.table("collab_rooms").select("*").eq("id", room_id).execute())
        return result.data[0] if result.data else None

    async def list_rooms(self, owner_id: str) -> List[dict]:
        result = await self._retry("list_rooms",
            lambda: self.supabase.table("collab_rooms")
                .select("*")
                .eq("owner_id", owner_id)
                .order("updated_at", desc=True)
                .execute())
        return result.data

    async def update_room(self, room_id: str, owner_id: str, updates: dict) -> dict:
        # Only owner can update
        room = await self.get_room(room_id)
        if not room or room["owner_id"] != owner_id:
            raise ValueError("Room not found or not authorized")
        updates = {k: v for k, v in updates.items() if v is not None}
        if not updates:
            return room
        result = await self._retry("update_room",
            lambda: self.supabase.table("collab_rooms").update(updates).eq("id", room_id).execute())
        return result.data[0]

    async def delete_room(self, room_id: str):
        """Delete a room and all related data (CASCADE handles children)."""
        await self._retry("delete_room",
            lambda: self.supabase.table("collab_rooms").delete().eq("id", room_id).execute())

    # ==================== External Threads (本体チャット⇄コラボの橋渡し) ====================

    async def create_external_thread(self, *, owner_id: str, origin_room_id: str, title: str,
                                     description: str = None, origin_message_id: str = None,
                                     expires_hours: int = 168) -> dict:
        """本体チャットの部屋に紐付いた外部窓口（コラボルーム＋招待）を作る。

        ゲストの発言は origin の部屋でダンが自動起動して受け取る
        （collab_routes → chat_routes /internal/collab-inbound → inbound_wakeup）。
        """
        # origin の部屋にオーナーが居ることを軽く確認（membership 行が無い部屋もあるため警告のみ）
        try:
            member = self.supabase.table("chat_room_members").select("id") \
                .eq("room_id", origin_room_id).eq("user_id", owner_id).limit(1).execute()
            if not member.data:
                self.logger.warning(
                    "create_external_thread: owner %s not in chat_room_members of %s",
                    owner_id, origin_room_id)
        except Exception:
            pass

        data = {
            "owner_id": owner_id,
            "title": title,
            "description": description,
            "ai_auto_assist": True,
            "origin_chat_room_id": origin_room_id,
            "origin_chat_message_id": origin_message_id,
            "origin_kind": "done_chat",
        }
        result = await self._retry("create_external_thread",
            lambda: self.supabase.table("collab_rooms").insert(data).execute())
        room = result.data[0]
        invite = await self.create_invite(room["id"], owner_id, expires_hours=expires_hours)
        return {"room": room, "invite": invite}

    async def notify_origin_chat_of_guest_message(self, collab_room_id: str, message: dict) -> Optional[dict]:
        """ゲスト発言を origin の本体チャット宛の通知（dan_proposals）に落とす。

        通常は /internal/collab-inbound の wake（ルームでダン自動起動）が先で、
        これは wake できない時のフォールバック（取りこぼし防止）。
        guest 以外の発言では何も作らない。
        """
        if (message or {}).get("sender_type") != "guest":
            return None
        room = await self.get_room(collab_room_id)
        if not room or not room.get("origin_chat_room_id"):
            return None
        sender = message.get("sender_name") or "ゲスト"
        body = (message.get("content") or "").strip()
        content = (
            f"コラボチャット「{room.get('title') or ''}」で {sender} さんからメッセージが届きました。\n\n"
            f"--- 本文 ---\n{body[:1200]}"
        )
        result = await self._retry("notify_origin_chat",
            lambda: self.supabase.table("dan_proposals").insert({
                "user_id": room["owner_id"],
                "type": "action",
                "title": f"{sender}さんから連絡",
                "content": content,
                "source_room_id": room["origin_chat_room_id"],
                "source_message_id": room.get("origin_chat_message_id"),
                "status": "pending",
                "action_data": {
                    "action": "collab_guest_message",
                    "channel": "collab",
                    "collab_room_id": collab_room_id,
                    "collab_message_id": message.get("id"),
                },
            }).execute())
        return result.data[0] if result.data else None

    async def set_thread_policy(self, collab_room_id: str, *, autonomy: str = None,
                                guidance: str = None) -> dict:
        """窓口の運用方針を設定する。

        autonomy: "approval"（既定: 返信は全件ユーザー承認）/ "auto"（guidance の範囲だけ
        承認なしで送信可）。guidance: 自動返信してよい範囲の自由記述。
        ai_assist_config(JSON) に保存し、着信 wake のプロンプトに反映される。
        """
        room = await self.get_room(collab_room_id)
        if not room:
            raise ValueError("Room not found")
        cfg = dict(room.get("ai_assist_config") or {})
        if autonomy is not None:
            autonomy = autonomy.strip().lower()
            if autonomy not in ("approval", "auto"):
                raise ValueError('autonomy は "approval" か "auto"')
            cfg["autonomy"] = autonomy
        if guidance is not None:
            cfg["auto_guidance"] = guidance.strip()
        result = await self._retry("set_thread_policy",
            lambda: self.supabase.table("collab_rooms")
                .update({"ai_assist_config": cfg})
                .eq("id", collab_room_id).execute())
        return result.data[0] if result.data else {**room, "ai_assist_config": cfg}

    async def list_participants(self, room_id: str) -> List[dict]:
        """参加済みゲストの名簿（入室した時点で掲載。オンライン判定はしない）。"""
        invites = await self.list_invites(room_id)
        return [
            {
                "id": inv["id"],
                "name": inv.get("guest_name") or "ゲスト",
                "joined_at": inv.get("joined_at"),
                "last_read_at": inv.get("last_read_at"),
            }
            for inv in invites
            if inv.get("status") == "joined" and inv.get("guest_name")
        ]

    async def mark_read(self, room_id: str, *, guest_invite_id: str = None,
                        as_owner: bool = False) -> None:
        """既読位置の更新（REST方式。WS不通のスマホでも確実に動く）。"""
        from datetime import datetime as _dt, timezone as _tz
        now = _dt.now(_tz.utc).isoformat()
        if as_owner:
            await self._retry("mark_read_owner",
                lambda: self.supabase.table("collab_rooms")
                    .update({"owner_last_read_at": now}).eq("id", room_id).execute())
        elif guest_invite_id:
            await self._retry("mark_read_guest",
                lambda: self.supabase.table("collab_invites")
                    .update({"last_read_at": now}).eq("id", guest_invite_id).execute())

    async def list_threads_for_origin(self, origin_room_id: str) -> List[dict]:
        """本体チャットの部屋に紐付いた外部窓口（コラボルーム）一覧。"""
        result = await self._retry("list_threads_for_origin",
            lambda: self.supabase.table("collab_rooms")
                .select("*")
                .eq("origin_chat_room_id", origin_room_id)
                .order("updated_at", desc=True)
                .execute())
        return result.data

    # ==================== Invites ====================

    async def create_invite(self, room_id: str, user_id: str, role: str = "reviewer",
                            expires_hours: int = 72) -> dict:
        room = await self.get_room(room_id)
        if not room:
            raise ValueError("Room not found")
        # Allow owner or linked guest user
        is_owner = room["owner_id"] == user_id
        if not is_owner:
            invites = await self.list_invites(room_id)
            is_member = any(
                inv.get("user_id") == user_id and inv["status"] == "joined"
                for inv in invites
            )
            if not is_member:
                raise ValueError("Not authorized")

        token = generate_invite_token()
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=expires_hours)).isoformat()

        data = {
            "room_id": room_id,
            "token": token,
            "role": role,
            "expires_at": expires_at,
        }
        result = await self._retry("create_invite",
            lambda: self.supabase.table("collab_invites").insert(data).execute())
        return result.data[0]

    async def get_invite_by_token(self, token: str) -> Optional[dict]:
        result = await self._retry("get_invite",
            lambda: self.supabase.table("collab_invites").select("*, collab_rooms(*)").eq("token", token).execute())
        return result.data[0] if result.data else None

    async def list_invites(self, room_id: str) -> List[dict]:
        result = await self._retry("list_invites",
            lambda: self.supabase.table("collab_invites")
                .select("*")
                .eq("room_id", room_id)
                .order("created_at", desc=True)
                .execute())
        return result.data

    async def join_room(self, token: str, guest_name: str, guest_jwt: str) -> dict:
        invite = await self.get_invite_by_token(token)
        if not invite:
            raise ValueError("Invalid invite token")
        if invite["status"] == "expired":
            raise ValueError("Invite expired")
        # Allow re-joining with same invite (different browser/device)

        from app.services.chat_service import parse_datetime
        expires_at = parse_datetime(invite["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            await self._retry("expire_invite",
                lambda: self.supabase.table("collab_invites")
                    .update({"status": "expired"})
                    .eq("id", invite["id"]).execute())
            raise ValueError("Invite expired")

        # Mark as joined
        await self._retry("join_invite",
            lambda: self.supabase.table("collab_invites").update({
                "status": "joined",
                "guest_name": guest_name,
                "guest_token": guest_jwt,
                "joined_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", invite["id"]).execute())

        room = invite.get("collab_rooms") or await self.get_room(invite["room_id"])
        return {
            "room_id": invite["room_id"],
            "room_title": room["title"] if room else "",
            "guest_name": guest_name,
            "role": invite["role"],
        }

    async def create_joiner_identity(self, room_id: str, guest_name: str, role: str) -> dict:
        """共有された招待URLから参加する「2人目以降」用の身分証を発行する。

        設計: 1つの招待URL＝部屋の入口（何人でも使える）。参加者ごとに
        collab_invites に1行＝1身分（名前・トークン）を持つ。URL自体に人は紐づかない。
        """
        data = {
            "room_id": room_id,
            "token": generate_invite_token(),   # 内部ID用。URLとしては配られない
            "role": role,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat(),
            "status": "joined",
            "guest_name": guest_name,
            "joined_at": datetime.now(timezone.utc).isoformat(),
        }
        result = await self._retry("create_joiner_identity",
            lambda: self.supabase.table("collab_invites").insert(data).execute())
        return result.data[0]

    async def update_invite_guest_token(self, invite_id: str, guest_jwt: str) -> None:
        await self._retry("update_invite_guest_token",
            lambda: self.supabase.table("collab_invites")
                .update({"guest_token": guest_jwt}).eq("id", invite_id).execute())

    async def update_invite_name(self, invite_id: str, guest_name: str) -> Optional[dict]:
        """表示名の変更（サーバー側の身分に反映。以後の発言は新しい名前になる）。"""
        result = await self._retry("update_invite_name",
            lambda: self.supabase.table("collab_invites")
                .update({"guest_name": guest_name}).eq("id", invite_id).execute())
        return result.data[0] if result.data else None

    async def link_user_by_tokens(self, user_id: str, guest_tokens: list[str]):
        """Link a registered user to their guest invites by decoding guest JWTs."""
        from app.config import settings
        from jose import jwt as jose_jwt
        jwt_secret = settings.JWT_SECRET_KEY or settings.APP_SECRET_KEY

        for token in guest_tokens:
            try:
                payload = jose_jwt.decode(token, jwt_secret, algorithms=["HS256"])
                if payload.get("type") != "guest":
                    continue
                invite_id = payload.get("sub")
                if not invite_id:
                    continue
                await self._retry("link_user_invite",
                    lambda inv_id=invite_id: self.supabase.table("collab_invites")
                        .update({"user_id": user_id})
                        .eq("id", inv_id)
                        .eq("status", "joined")
                        .is_("user_id", "null")
                        .execute())
            except Exception:
                continue  # Invalid/expired token, skip

    async def list_guest_rooms(self, user_id: str) -> List[dict]:
        """List rooms where the user is a guest (via user_id in collab_invites)."""
        invites = await self._retry("list_guest_invites",
            lambda: self.supabase.table("collab_invites")
                .select("*, collab_rooms(*)")
                .eq("user_id", user_id)
                .eq("status", "joined")
                .execute())
        rooms = []
        for inv in invites.data:
            room = inv.get("collab_rooms")
            if room:
                room["_invite_token"] = inv["token"]
                room["_guest_name"] = inv.get("guest_name", "")
                rooms.append(room)
        return rooms

    # ==================== Messages ====================

    async def send_message(self, room_id: str, sender_type: str, sender_name: str,
                           content: str, metadata: dict = None) -> dict:
        data = {
            "room_id": room_id,
            "sender_type": sender_type,
            "sender_name": sender_name,
            "content": content,
            "metadata": metadata or {},
        }
        result = await self._retry("send_message",
            lambda: self.supabase.table("collab_messages").insert(data).execute())

        # Update room's updated_at
        await self._retry("touch_room",
            lambda: self.supabase.table("collab_rooms")
                .update({"updated_at": datetime.now(timezone.utc).isoformat()})
                .eq("id", room_id).execute())

        return result.data[0]

    async def add_reaction(self, room_id: str, message_id: str, emoji: str, by: str = "ダン",
                           toggle: bool = False) -> Optional[dict]:
        """メッセージにリアクションを付ける（metadata.reactions に追記）。

        リアクションはメッセージではない: 通知・Push・未読は一切発生しない。
        toggle=True なら同じ人の同じ絵文字は付け外し（人間の操作用）。
        """
        r = await self._retry("get_msg_for_reaction",
            lambda: self.supabase.table("collab_messages").select("id,metadata")
                .eq("id", message_id).eq("room_id", room_id).limit(1).execute())
        if not r.data:
            return None
        md = dict(r.data[0].get("metadata") or {})
        reactions = dict(md.get("reactions") or {})
        names = list(reactions.get(emoji) or [])
        if by in names:
            if toggle:
                names.remove(by)
        else:
            names.append(by)
        if names:
            reactions[emoji] = names
        else:
            reactions.pop(emoji, None)
        md["reactions"] = reactions
        upd = await self._retry("add_reaction",
            lambda: self.supabase.table("collab_messages")
                .update({"metadata": md}).eq("id", message_id).execute())
        return upd.data[0] if upd.data else None

    async def get_messages(self, room_id: str, limit: int = 50, before: str = None) -> List[dict]:
        query = self.supabase.table("collab_messages").select("*").eq("room_id", room_id)
        if before:
            query = query.lt("created_at", before)
        result = await self._retry("get_messages",
            lambda: query.order("created_at", desc=True).limit(limit).execute())
        return list(reversed(result.data))

    # ==================== Files ====================

    async def save_file_record(self, room_id: str, uploaded_by: str, file_name: str,
                               file_path: str, file_type: str = None, file_size: int = None,
                               message_id: str = None) -> dict:
        data = {
            "room_id": room_id,
            "uploaded_by": uploaded_by,
            "file_name": file_name,
            "file_path": file_path,
            "file_type": file_type,
            "file_size": file_size,
            "message_id": message_id,
        }
        result = await self._retry("save_file",
            lambda: self.supabase.table("collab_files").insert(data).execute())
        return result.data[0]

    async def get_files(self, room_id: str) -> List[dict]:
        result = await self._retry("get_files",
            lambda: self.supabase.table("collab_files")
                .select("*")
                .eq("room_id", room_id)
                .order("created_at", desc=True)
                .execute())
        return result.data

    # ==================== Auth Helpers ====================

    async def verify_room_access(self, room_id: str, user_id: str = None,
                                  invite_token: str = None) -> bool:
        """Verify that a user (owner or guest) has access to a room."""
        room = await self.get_room(room_id)
        if not room:
            return False
        # Owner always has access
        if user_id and room["owner_id"] == user_id:
            return True
        # Linked guest user access (registered user linked via collab_invites.user_id)
        if user_id:
            invites = await self.list_invites(room_id)
            if any(inv.get("user_id") == user_id and inv["status"] == "joined" for inv in invites):
                return True
        # Guest access via invite token
        if invite_token:
            invite = await self.get_invite_by_token(invite_token)
            if invite and invite["room_id"] == room_id and invite["status"] == "joined":
                return True
        return False
