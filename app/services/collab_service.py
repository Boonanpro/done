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
                          ai_assist_config: dict = None) -> dict:
        data = {
            "owner_id": owner_id,
            "title": title,
            "description": description,
            "project_ref": project_ref,
            "ai_auto_assist": ai_auto_assist,
        }
        if ai_assist_config:
            data["ai_assist_config"] = ai_assist_config

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

    # ==================== Invites ====================

    async def create_invite(self, room_id: str, owner_id: str, role: str = "reviewer",
                            expires_hours: int = 72) -> dict:
        room = await self.get_room(room_id)
        if not room or room["owner_id"] != owner_id:
            raise ValueError("Room not found or not authorized")

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
        if invite["status"] == "joined":
            raise ValueError("Invite already used")
        if invite["status"] == "expired":
            raise ValueError("Invite expired")

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
        # Guest access via invite token
        if invite_token:
            invite = await self.get_invite_by_token(invite_token)
            if invite and invite["room_id"] == room_id and invite["status"] == "joined":
                return True
        return False
