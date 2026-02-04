"""
Dan Notifier (Phase 1-3 foundation)
Voice WebSocket sessions are tracked here so future background notifications
can target the active session or fallback to push notifications.
"""
from __future__ import annotations

from typing import Optional
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class VoiceSessionRegistry:
    """Tracks active voice WebSocket sessions by user and session id."""

    def __init__(self) -> None:
        self._connections: dict[str, dict[str, WebSocket]] = {}

    def add(self, user_id: str, session_id: str, websocket: WebSocket) -> None:
        self._connections.setdefault(user_id, {})[session_id] = websocket
        logger.debug("Voice session registered user=%s session=%s", user_id, session_id)

    def remove(self, user_id: str, session_id: str) -> None:
        sessions = self._connections.get(user_id)
        if not sessions:
            return
        sessions.pop(session_id, None)
        if not sessions:
            self._connections.pop(user_id, None)
        logger.debug("Voice session removed user=%s session=%s", user_id, session_id)

    def get(self, user_id: str, session_id: str) -> Optional[WebSocket]:
        return self._connections.get(user_id, {}).get(session_id)

    def list_sessions(self, user_id: str) -> list[str]:
        return list(self._connections.get(user_id, {}).keys())

    async def send_to_session(self, user_id: str, session_id: str, payload: dict) -> bool:
        websocket = self.get(user_id, session_id)
        if not websocket:
            return False
        try:
            await websocket.send_json(payload)
            return True
        except Exception as exc:
            logger.warning("Voice session send failed user=%s session=%s: %s", user_id, session_id, exc)
            return False

    async def broadcast_to_user(self, user_id: str, payload: dict) -> int:
        sessions = self._connections.get(user_id, {})
        sent = 0
        for session_id, websocket in list(sessions.items()):
            try:
                await websocket.send_json(payload)
                sent += 1
            except Exception as exc:
                logger.warning("Voice session broadcast failed user=%s session=%s: %s", user_id, session_id, exc)
        return sent


class DanNotifier:
    """Minimal notifier used by Phase 1-3 to target active voice sessions."""

    def __init__(self, registry: VoiceSessionRegistry) -> None:
        self._registry = registry

    async def notify_voice_session(self, user_id: str, session_id: str, message: str) -> bool:
        payload = {"type": "notify", "message": message}
        return await self._registry.send_to_session(user_id, session_id, payload)

    async def notify_active_voice_sessions(self, user_id: str, message: str) -> int:
        payload = {"type": "notify", "message": message}
        return await self._registry.broadcast_to_user(user_id, payload)


voice_session_registry = VoiceSessionRegistry()
dan_notifier = DanNotifier(voice_session_registry)


def get_dan_notifier() -> DanNotifier:
    return dan_notifier
