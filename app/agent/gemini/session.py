"""
Gemini voice session persistence.

Saves conversation logs from GeminiLiveRunner to the database.
Uses the existing agent_sessions_v2 table with provider='gemini' to
distinguish from Claude sessions.
"""

import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class GeminiSessionStore:
    """Persists Gemini voice conversation logs to Supabase."""

    def __init__(self):
        self._supabase = None

    def _get_supabase(self):
        if self._supabase is None:
            try:
                from app.config import settings
                from supabase import create_client
                self._supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
            except Exception as e:
                logger.warning("Failed to initialize Supabase client: %s", e)
        return self._supabase

    async def save_conversation(
        self,
        session_id: str,
        user_id: str,
        conversation_log: List[Dict[str, Any]],
    ) -> bool:
        """Save a Gemini voice conversation log to the database.

        Extracts messages from the raw conversation log and stores them
        in the same format as Claude sessions for compatibility.

        Args:
            session_id: Session identifier
            user_id: User identifier
            conversation_log: Raw conversation log from GeminiLiveRunner

        Returns:
            True if saved successfully
        """
        supabase = self._get_supabase()
        if not supabase:
            logger.warning("Cannot save: Supabase not available")
            return False

        # Convert conversation log to messages format
        messages = self._log_to_messages(conversation_log)

        now = datetime.now(timezone.utc).isoformat()
        data = {
            "session_id": session_id,
            "user_id": user_id,
            "messages": messages,
            "current_state": "chat",
            "reasoning_steps": [],
            "context": {
                "provider": "gemini",
                "voice_session": True,
            },
            "updated_at": now,
        }

        try:
            supabase.table("agent_sessions_v2").upsert(
                data,
                on_conflict="session_id,user_id"
            ).execute()
            logger.info("Gemini session saved: %s (%d messages)", session_id, len(messages))
            return True
        except Exception as e:
            logger.error("Failed to save Gemini session: %s", e)
            return False

    async def load_conversation(
        self,
        session_id: str,
        user_id: str,
    ) -> Optional[List[Dict[str, Any]]]:
        """Load a previous conversation for context resumption.

        Args:
            session_id: Session identifier
            user_id: User identifier

        Returns:
            List of message dicts, or None if not found
        """
        supabase = self._get_supabase()
        if not supabase:
            return None

        try:
            result = supabase.table("agent_sessions_v2").select("messages, context").eq(
                "session_id", session_id
            ).eq("user_id", user_id).limit(1).execute()

            if result.data and len(result.data) > 0:
                return result.data[0].get("messages", [])
            return None
        except Exception as e:
            logger.warning("Failed to load Gemini session: %s", e)
            return None

    def _log_to_messages(self, conversation_log: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert raw conversation log entries to Claude-compatible messages format.

        This enables the chat UI to display Gemini voice conversations
        alongside Claude text conversations.
        """
        messages = []

        for entry in conversation_log:
            role = entry.get("role", "")
            content = entry.get("content", "")

            if role == "user":
                messages.append({
                    "role": "user",
                    "content": content,
                })
            elif role == "assistant":
                # Merge consecutive assistant messages
                if messages and messages[-1]["role"] == "assistant":
                    prev_content = messages[-1]["content"]
                    if isinstance(prev_content, str):
                        messages[-1]["content"] = prev_content + " " + content
                    continue
                messages.append({
                    "role": "assistant",
                    "content": content,
                })
            elif role == "tool_call":
                # Store tool calls as assistant messages with metadata
                messages.append({
                    "role": "assistant",
                    "content": [{
                        "type": "text",
                        "text": f"[Tool: {content}]",
                    }],
                })
            elif role == "tool_result":
                # Store tool results
                messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "content": content,
                    }],
                })

        return messages


# Singleton
_gemini_session_store: Optional[GeminiSessionStore] = None


def get_gemini_session_store() -> GeminiSessionStore:
    global _gemini_session_store
    if _gemini_session_store is None:
        _gemini_session_store = GeminiSessionStore()
    return _gemini_session_store
