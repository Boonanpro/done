"""
Chat Service - Business Logic for Done Chat
"""
from typing import Optional
from datetime import datetime, timedelta
import secrets
import re

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


class ChatService:
    """Done Chat business logic"""
    
    def __init__(self):
        self.supabase = get_supabase_client().client  # Use the underlying supabase client
    
    # ==================== User Management ====================
    
    async def create_user(self, email: str, password: str, display_name: str) -> dict:
        """Create a new chat user"""
        password_hash = get_password_hash(password)
        
        result = self.supabase.table("chat_users").insert({
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
        result = self.supabase.table("chat_users").select("*").eq("email", email).execute()
        return result.data[0] if result.data else None
    
    async def get_user_by_id(self, user_id: str) -> Optional[dict]:
        """Get user by ID (excludes password_hash)"""
        result = self.supabase.table("chat_users").select(
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
        
        result = self.supabase.table("chat_users").update(update_data).eq("id", user_id).execute()
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
            expires_at = (datetime.utcnow() + timedelta(hours=expires_in_hours)).isoformat()
        
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
            "*, creator:chat_users!creator_id(id, display_name, avatar_url)"
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
            if datetime.utcnow().replace(tzinfo=expires_at.tzinfo) > expires_at:
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
            "*, friend:chat_users!friend_id(id, display_name, avatar_url)"
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
        member = self.supabase.table("chat_room_members").select("*").eq("room_id", room_id).eq("user_id", user_id).execute()
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
        member = self.supabase.table("chat_room_members").select("*").eq("room_id", room_id).eq("user_id", user_id).execute()
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
            "*, user:chat_users!user_id(id, display_name, avatar_url)"
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
    
    async def send_message(self, room_id: str, sender_id: str, content: str, sender_type: str = "human") -> dict:
        """Send a message to a room"""
        # Verify membership
        member = self.supabase.table("chat_room_members").select("*").eq("room_id", room_id).eq("user_id", sender_id).execute()
        if not member.data:
            raise ValueError("Not a member of this room")

        # Get sender info
        sender = self.supabase.table("chat_users").select("display_name, done_user_id").eq("id", sender_id).execute()
        sender_name = sender.data[0]["display_name"] if sender.data else "Unknown"
        done_user_id = sender.data[0].get("done_user_id") if sender.data else None

        result = self.supabase.table("chat_messages").insert({
            "room_id": room_id,
            "sender_id": sender_id,
            "sender_type": sender_type,
            "content": content,
        }).execute()

        if result.data:
            msg = result.data[0]
            msg["sender_name"] = sender_name
            
            # Phase 5A: メッセージ検知フック（AI有効ルームのみ）
            if sender_type == "human":
                await self._trigger_message_detection(
                    room_id=room_id,
                    message_id=msg["id"],
                    sender_id=sender_id,
                    done_user_id=done_user_id,
                    content=content,
                    sender_name=sender_name,
                )
            
            return msg
        raise ValueError("Failed to send message")
    
    async def _trigger_message_detection(
        self,
        room_id: str,
        message_id: str,
        sender_id: str,
        done_user_id: Optional[str],
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
            
            # done_user_idがなければ、検知対象外（Doneアカウントと連携していない）
            if not done_user_id:
                return
            
            # メッセージ検知サービスを呼び出し
            from app.services.message_detection import get_detection_service
            from app.models.detection_schemas import MessageSource
            
            detection_service = get_detection_service()
            await detection_service.detect_message(
                user_id=done_user_id,
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
            "*, sender:chat_users!sender_id(id, display_name, avatar_url)"
        ).eq("room_id", room_id).order("created_at", desc=True).limit(limit)
        
        if before:
            query = query.lt("created_at", before)
        
        result = query.execute()
        
        messages = []
        for msg in result.data or []:
            messages.append({
                "id": msg["id"],
                "room_id": msg["room_id"],
                "sender_id": msg["sender_id"],
                "sender_name": msg["sender"]["display_name"] if msg.get("sender") else "Unknown",
                "sender_type": msg["sender_type"],
                "content": msg["content"],
                "created_at": msg["created_at"],
            })
        
        return messages
    
    async def mark_as_read(self, room_id: str, user_id: str) -> bool:
        """Mark messages as read"""
        result = self.supabase.table("chat_room_members").update({
            "last_read_at": datetime.utcnow().isoformat(),
        }).eq("room_id", room_id).eq("user_id", user_id).execute()
        
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


def get_chat_service() -> ChatService:
    """ChatServiceのシングルトンインスタンスを取得"""
    return ChatService()


# Import timedelta for invite expiration
from datetime import timedelta
