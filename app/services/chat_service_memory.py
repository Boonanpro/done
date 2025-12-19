"""
In-Memory Chat Service for Testing
DBに依存しないテスト用のチャットサービス
"""
from typing import Optional
from datetime import datetime, timedelta
import secrets
import uuid

from app.services.auth_service import get_password_hash, verify_password


def generate_invite_code(length: int = 8) -> str:
    """Generate a random invite code"""
    return secrets.token_urlsafe(length)[:length]


class InMemoryChatService:
    """In-memory implementation of ChatService for testing"""
    
    def __init__(self):
        # In-memory storage
        self.users: dict[str, dict] = {}
        self.invites: dict[str, dict] = {}
        self.friendships: dict[str, dict] = {}
        self.rooms: dict[str, dict] = {}
        self.room_members: dict[str, dict] = {}
        self.messages: dict[str, dict] = {}
        self.ai_settings: dict[str, dict] = {}
    
    # ==================== User Management ====================
    
    async def create_user(self, email: str, password: str, display_name: str) -> dict:
        """Create a new chat user"""
        # Check for duplicate email
        for user in self.users.values():
            if user["email"] == email:
                raise ValueError("Email already registered")
        
        password_hash = get_password_hash(password)
        user_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        
        user = {
            "id": user_id,
            "email": email,
            "password_hash": password_hash,
            "display_name": display_name,
            "avatar_url": None,
            "created_at": now,
            "updated_at": now,
        }
        self.users[user_id] = user
        
        return {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "avatar_url": user.get("avatar_url"),
            "created_at": user["created_at"],
        }
    
    async def get_user_by_email(self, email: str) -> Optional[dict]:
        """Get user by email"""
        for user in self.users.values():
            if user["email"] == email:
                return user
        return None
    
    async def get_user_by_id(self, user_id: str) -> Optional[dict]:
        """Get user by ID"""
        user = self.users.get(user_id)
        if user:
            return {
                "id": user["id"],
                "email": user["email"],
                "display_name": user["display_name"],
                "avatar_url": user.get("avatar_url"),
                "created_at": user["created_at"],
                "updated_at": user.get("updated_at"),
            }
        return None
    
    async def update_user(self, user_id: str, display_name: Optional[str] = None, avatar_url: Optional[str] = None) -> Optional[dict]:
        """Update user profile"""
        user = self.users.get(user_id)
        if not user:
            return None
        
        if display_name is not None:
            user["display_name"] = display_name
        if avatar_url is not None:
            user["avatar_url"] = avatar_url
        user["updated_at"] = datetime.utcnow().isoformat()
        
        return {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "avatar_url": user.get("avatar_url"),
            "created_at": user["created_at"],
            "updated_at": user["updated_at"],
        }
    
    async def authenticate_user(self, email: str, password: str) -> Optional[dict]:
        """Authenticate user with email and password"""
        user = await self.get_user_by_email(email)
        if not user:
            return None
        if not verify_password(password, user["password_hash"]):
            return None
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
        invite_id = str(uuid.uuid4())
        now = datetime.utcnow()
        expires_at = None
        if expires_in_hours:
            expires_at = (now + timedelta(hours=expires_in_hours)).isoformat()
        
        invite = {
            "id": invite_id,
            "code": code,
            "creator_id": creator_id,
            "max_uses": max_uses,
            "use_count": 0,
            "expires_at": expires_at,
            "created_at": now.isoformat(),
        }
        self.invites[invite_id] = invite
        
        return invite
    
    async def get_invite_by_code(self, code: str) -> Optional[dict]:
        """Get invite by code"""
        for invite in self.invites.values():
            if invite["code"] == code:
                creator = self.users.get(invite["creator_id"])
                result = invite.copy()
                if creator:
                    result["creator"] = {
                        "id": creator["id"],
                        "display_name": creator["display_name"],
                        "avatar_url": creator.get("avatar_url"),
                    }
                return result
        return None
    
    async def accept_invite(self, code: str, user_id: str) -> dict:
        """Accept an invite and create friendship"""
        invite = await self.get_invite_by_code(code)
        if not invite:
            raise ValueError("Invite not found")
        
        # Check if expired
        if invite.get("expires_at"):
            expires_at = datetime.fromisoformat(invite["expires_at"])
            if datetime.utcnow() > expires_at:
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
        for inv in self.invites.values():
            if inv["code"] == code:
                inv["use_count"] += 1
                break
        
        return {
            "friend_id": creator_id,
            "room_id": room["id"],
        }
    
    async def _create_friendship(self, user_id: str, friend_id: str) -> None:
        """Create a one-way friendship"""
        key = f"{user_id}:{friend_id}"
        if key not in self.friendships:
            self.friendships[key] = {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "friend_id": friend_id,
                "status": "active",
                "created_at": datetime.utcnow().isoformat(),
            }
    
    async def _create_direct_room(self, user1_id: str, user2_id: str) -> dict:
        """Create a direct chat room between two users"""
        # Check if room already exists
        for room_id, room in self.rooms.items():
            if room["type"] == "direct":
                members = [m for m in self.room_members.values() if m["room_id"] == room_id]
                member_ids = {m["user_id"] for m in members}
                if member_ids == {user1_id, user2_id}:
                    return room
        
        # Create new room
        room_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        
        room = {
            "id": room_id,
            "name": None,
            "type": "direct",
            "created_at": now,
            "updated_at": now,
        }
        self.rooms[room_id] = room
        
        # Add both users as members
        for uid in [user1_id, user2_id]:
            member_id = str(uuid.uuid4())
            self.room_members[member_id] = {
                "id": member_id,
                "room_id": room_id,
                "user_id": uid,
                "role": "member",
                "ai_mode": "off",
                "last_read_at": None,
                "joined_at": now,
            }
        
        # Create default AI settings
        self.ai_settings[room_id] = {
            "id": str(uuid.uuid4()),
            "room_id": room_id,
            "enabled": False,
            "mode": "off",
            "personality": None,
            "auto_reply_delay_ms": 3000,
            "created_at": now,
            "updated_at": now,
        }
        
        return room
    
    # ==================== Friends Management ====================
    
    async def get_friends(self, user_id: str) -> list[dict]:
        """Get user's friends list"""
        friends = []
        for friendship in self.friendships.values():
            if friendship["user_id"] == user_id and friendship["status"] == "active":
                friend = self.users.get(friendship["friend_id"])
                if friend:
                    friends.append({
                        "id": friend["id"],
                        "display_name": friend["display_name"],
                        "avatar_url": friend.get("avatar_url"),
                        "created_at": friendship["created_at"],
                    })
        return friends
    
    async def delete_friend(self, user_id: str, friend_id: str) -> bool:
        """Delete a friendship"""
        keys_to_delete = [
            f"{user_id}:{friend_id}",
            f"{friend_id}:{user_id}",
        ]
        for key in keys_to_delete:
            if key in self.friendships:
                del self.friendships[key]
        return True
    
    # ==================== Room Management ====================
    
    async def get_rooms(self, user_id: str) -> list[dict]:
        """Get user's chat rooms"""
        rooms = []
        for member in self.room_members.values():
            if member["user_id"] == user_id:
                room = self.rooms.get(member["room_id"])
                if room:
                    room_copy = room.copy()
                    room_copy["my_role"] = member["role"]
                    room_copy["my_ai_mode"] = member["ai_mode"]
                    room_copy["last_read_at"] = member["last_read_at"]
                    rooms.append(room_copy)
        return rooms
    
    async def create_room(self, creator_id: str, name: str, member_ids: list[str]) -> dict:
        """Create a group chat room"""
        room_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        
        room = {
            "id": room_id,
            "name": name,
            "type": "group",
            "created_at": now,
            "updated_at": now,
        }
        self.rooms[room_id] = room
        
        # Add creator as owner
        owner_member_id = str(uuid.uuid4())
        self.room_members[owner_member_id] = {
            "id": owner_member_id,
            "room_id": room_id,
            "user_id": creator_id,
            "role": "owner",
            "ai_mode": "off",
            "last_read_at": None,
            "joined_at": now,
        }
        
        # Add other members
        for member_id in member_ids:
            if member_id != creator_id:
                mem_id = str(uuid.uuid4())
                self.room_members[mem_id] = {
                    "id": mem_id,
                    "room_id": room_id,
                    "user_id": member_id,
                    "role": "member",
                    "ai_mode": "off",
                    "last_read_at": None,
                    "joined_at": now,
                }
        
        # Create default AI settings
        self.ai_settings[room_id] = {
            "id": str(uuid.uuid4()),
            "room_id": room_id,
            "enabled": False,
            "mode": "off",
            "personality": None,
            "auto_reply_delay_ms": 3000,
            "created_at": now,
            "updated_at": now,
        }
        
        return room
    
    async def get_room(self, room_id: str, user_id: str) -> Optional[dict]:
        """Get room details"""
        # Verify membership
        member = None
        for m in self.room_members.values():
            if m["room_id"] == room_id and m["user_id"] == user_id:
                member = m
                break
        
        if not member:
            return None
        
        room = self.rooms.get(room_id)
        if room:
            room_copy = room.copy()
            room_copy["my_role"] = member["role"]
            room_copy["my_ai_mode"] = member["ai_mode"]
            return room_copy
        return None
    
    async def update_room(self, room_id: str, user_id: str, name: Optional[str] = None) -> Optional[dict]:
        """Update room settings"""
        # Verify membership and role
        member = None
        for m in self.room_members.values():
            if m["room_id"] == room_id and m["user_id"] == user_id:
                member = m
                break
        
        if not member:
            return None
        
        if member["role"] not in ["owner", "admin"]:
            raise ValueError("Permission denied")
        
        room = self.rooms.get(room_id)
        if room and name is not None:
            room["name"] = name
            room["updated_at"] = datetime.utcnow().isoformat()
        
        return await self.get_room(room_id, user_id)
    
    async def get_room_members(self, room_id: str, user_id: str) -> list[dict]:
        """Get room members"""
        # Verify membership
        is_member = any(
            m["room_id"] == room_id and m["user_id"] == user_id
            for m in self.room_members.values()
        )
        if not is_member:
            raise ValueError("Not a member of this room")
        
        members = []
        for m in self.room_members.values():
            if m["room_id"] == room_id:
                user = self.users.get(m["user_id"])
                if user:
                    members.append({
                        "user_id": user["id"],
                        "display_name": user["display_name"],
                        "avatar_url": user.get("avatar_url"),
                        "role": m["role"],
                        "ai_mode": m["ai_mode"],
                        "joined_at": m["joined_at"],
                    })
        return members
    
    async def add_room_member(self, room_id: str, user_id: str, new_member_id: str) -> dict:
        """Add a member to a room"""
        # Verify membership and role
        member = None
        for m in self.room_members.values():
            if m["room_id"] == room_id and m["user_id"] == user_id:
                member = m
                break
        
        if not member:
            raise ValueError("Not a member of this room")
        
        if member["role"] not in ["owner", "admin"]:
            raise ValueError("Permission denied")
        
        # Add new member
        now = datetime.utcnow().isoformat()
        mem_id = str(uuid.uuid4())
        new_member = {
            "id": mem_id,
            "room_id": room_id,
            "user_id": new_member_id,
            "role": "member",
            "ai_mode": "off",
            "last_read_at": None,
            "joined_at": now,
        }
        self.room_members[mem_id] = new_member
        
        return new_member
    
    # ==================== Message Management ====================
    
    async def send_message(self, room_id: str, sender_id: str, content: str, sender_type: str = "human") -> dict:
        """Send a message to a room"""
        # Verify membership
        is_member = any(
            m["room_id"] == room_id and m["user_id"] == sender_id
            for m in self.room_members.values()
        )
        if not is_member:
            raise ValueError("Not a member of this room")
        
        message_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        
        message = {
            "id": message_id,
            "room_id": room_id,
            "sender_id": sender_id,
            "sender_type": sender_type,
            "content": content,
            "created_at": now,
        }
        self.messages[message_id] = message
        
        return message
    
    async def get_messages(self, room_id: str, user_id: str, limit: int = 50, before: Optional[str] = None) -> list[dict]:
        """Get messages from a room"""
        # Verify membership
        is_member = any(
            m["room_id"] == room_id and m["user_id"] == user_id
            for m in self.room_members.values()
        )
        if not is_member:
            raise ValueError("Not a member of this room")
        
        room_messages = [m for m in self.messages.values() if m["room_id"] == room_id]
        room_messages.sort(key=lambda x: x["created_at"], reverse=True)
        
        if before:
            room_messages = [m for m in room_messages if m["created_at"] < before]
        
        room_messages = room_messages[:limit]
        
        result = []
        for msg in room_messages:
            sender = self.users.get(msg["sender_id"])
            result.append({
                "id": msg["id"],
                "room_id": msg["room_id"],
                "sender_id": msg["sender_id"],
                "sender_name": sender["display_name"] if sender else "Unknown",
                "sender_type": msg["sender_type"],
                "content": msg["content"],
                "created_at": msg["created_at"],
            })
        
        return result
    
    async def mark_as_read(self, room_id: str, user_id: str) -> bool:
        """Mark messages as read"""
        for m in self.room_members.values():
            if m["room_id"] == room_id and m["user_id"] == user_id:
                m["last_read_at"] = datetime.utcnow().isoformat()
                return True
        return False
    
    # ==================== AI Settings ====================
    
    async def get_ai_settings(self, room_id: str, user_id: str) -> Optional[dict]:
        """Get AI settings for a room"""
        # Verify membership
        is_member = any(
            m["room_id"] == room_id and m["user_id"] == user_id
            for m in self.room_members.values()
        )
        if not is_member:
            raise ValueError("Not a member of this room")
        
        return self.ai_settings.get(room_id)
    
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
        is_member = any(
            m["room_id"] == room_id and m["user_id"] == user_id
            for m in self.room_members.values()
        )
        if not is_member:
            raise ValueError("Not a member of this room")
        
        settings = self.ai_settings.get(room_id)
        if settings:
            if enabled is not None:
                settings["enabled"] = enabled
            if mode is not None:
                settings["mode"] = mode
            if personality is not None:
                settings["personality"] = personality
            if auto_reply_delay_ms is not None:
                settings["auto_reply_delay_ms"] = auto_reply_delay_ms
            settings["updated_at"] = datetime.utcnow().isoformat()
        
        return settings
    
    async def get_ai_summary(self, room_id: str, user_id: str) -> dict:
        """Get AI summary of recent conversation"""
        # Verify membership
        is_member = any(
            m["room_id"] == room_id and m["user_id"] == user_id
            for m in self.room_members.values()
        )
        if not is_member:
            raise ValueError("Not a member of this room")
        
        messages = await self.get_messages(room_id, user_id, limit=50)
        
        if not messages:
            return {"summary": "No messages yet.", "message_count": 0}
        
        return {
            "summary": f"Recent conversation with {len(messages)} messages.",
            "message_count": len(messages),
            "last_message_at": messages[0]["created_at"] if messages else None,
        }


# Singleton instance for testing
_memory_chat_service: Optional[InMemoryChatService] = None


def get_memory_chat_service() -> InMemoryChatService:
    """Get in-memory chat service singleton"""
    global _memory_chat_service
    if _memory_chat_service is None:
        _memory_chat_service = InMemoryChatService()
    return _memory_chat_service


def reset_memory_chat_service() -> None:
    """Reset in-memory chat service (for tests)"""
    global _memory_chat_service
    _memory_chat_service = None
