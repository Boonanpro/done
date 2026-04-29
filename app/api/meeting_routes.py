"""
Meeting Room WebSocket endpoint.

Protocol:
  Client→Server:
    JSON {"type":"auth","token":"JWT","session_id":"..."}
    JSON {"type":"start","topic":"...","proposal_content":"..."}
    JSON {"type":"user_message","text":"..."}
    JSON {"type":"control","action":"pause|resume|next|prev|end"}
    JSON {"type":"ping"}

  Server→Client:
    JSON {"type":"state","state":{...}}
    JSON {"type":"slide","slide":{...},"narration":"..."}
    JSON {"type":"transcript","speaker":"dan|user","text":"..."}
    JSON {"type":"audio_end"}
    JSON {"type":"summary","text":"...","transcript":[...]}
    JSON {"type":"error","message":"..."}
    Binary: MP3 audio chunks (streamed TTS)
"""
import uuid
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.auth_service import decode_access_token
from app.services.meeting_service import (
    MeetingSession, register_meeting, unregister_meeting,
)

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"


@router.websocket("/ws/meeting")
async def meeting_websocket(websocket: WebSocket):
    """Meeting Room WebSocket endpoint."""
    await websocket.accept()

    user_id: Optional[str] = None
    session_id: Optional[str] = None
    meeting: Optional[MeetingSession] = None

    try:
        # --- Phase 1: Auth ---
        auth_data = await websocket.receive_json()
        if auth_data.get("type") != "auth":
            await websocket.send_json({"type": "error", "message": "Expected auth message"})
            await websocket.close()
            return

        token = auth_data.get("token")
        session_id = auth_data.get("session_id") or str(uuid.uuid4())

        user_id = DEFAULT_USER_ID
        if token:
            token_data = decode_access_token(token)
            if token_data:
                user_id = token_data.user_id

        await websocket.send_json({
            "type": "auth_success",
            "user_id": user_id,
            "session_id": session_id,
        })

        # Create meeting session
        meeting = MeetingSession(session_id, user_id, websocket)
        register_meeting(meeting)

        await websocket.send_json({"type": "ready"})

        # --- Phase 2: Message loop ---
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "start":
                topic = data.get("topic", "提案")
                content = data.get("proposal_content", "")
                await meeting.prepare(topic, content)

            elif msg_type == "user_message":
                text = (data.get("text") or "").strip()
                if text:
                    await meeting.handle_question(text)

            elif msg_type == "audio_played":
                meeting.notify_audio_played()

            elif msg_type == "control":
                action = data.get("action", "")
                if action == "next":
                    await meeting.go_to_slide("next")
                elif action == "prev":
                    await meeting.go_to_slide("prev")
                elif action == "resume":
                    await meeting.resume_presentation()
                elif action == "end":
                    await meeting.end()
                    break
                elif action == "pause":
                    meeting._cancel_presentation = True

            elif msg_type == "stop":
                break

    except WebSocketDisconnect:
        logger.info("Meeting WebSocket disconnected (session=%s)", session_id)
    except Exception as e:
        logger.exception("Meeting WebSocket error: %s", e)
    finally:
        if meeting:
            await meeting.end()
        if session_id:
            unregister_meeting(session_id)
