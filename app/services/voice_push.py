"""
Voice Push Utility
Dan発話プッシュ — TTS音声付きでcompanionセッションに送信
"""
import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def push_voice_message(user_id: str, text: str) -> int:
    """
    Danから音声付きメッセージをプッシュ送信する。

    Args:
        user_id: 対象ユーザーID
        text: 送信テキスト

    Returns:
        送信成功したセッション数
    """
    from app.services.dan_notifier import voice_session_registry
    from app.services.voice_service import get_voice_service

    sessions = voice_session_registry.list_sessions(user_id)
    if not sessions:
        return 0

    audio_base64: Optional[str] = None
    try:
        svc = get_voice_service()
        mp3_bytes = await svc.text_to_speech(text)
        if mp3_bytes:
            audio_base64 = base64.b64encode(mp3_bytes).decode("utf-8")
    except Exception as exc:
        logger.warning("Voice push TTS failed: %s", exc)

    payload = {
        "type": "dan_initiated",
        "text": text,
        "audio_base64": audio_base64,
    }
    sent = await voice_session_registry.broadcast_to_user(user_id, payload)
    logger.info("Voice push sent to %d session(s) for user=%s", sent, user_id)
    return sent
