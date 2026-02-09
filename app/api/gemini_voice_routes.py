"""
Gemini Native Audio WebSocket endpoint.

Handles two client modes over a single /ws/gemini-voice endpoint:
  - voice: sends/receives binary PCM audio
  - observer: receives text + process steps, can send text input

Protocol:
  Client→Server:
    JSON  {"type":"auth","token":"JWT","session_id":"..."}
    JSON  {"type":"config","mode":"voice"|"observer"}
    Binary PCM 16kHz 16-bit LE mono (voice mode only)
    JSON  {"type":"text","text":"..."} (observer/voice text input)
    JSON  {"type":"ping"}

  Server→Client:
    Binary PCM 24kHz 16-bit LE mono (voice mode only)
    JSON  {"type":"assistant_text","text":"..."}
    JSON  {"type":"process_step","step":"..."}
    JSON  {"type":"tool_start","tool":"browser_open"}
    JSON  {"type":"tool_result","tool":"...","success":bool}
    JSON  {"type":"turn_complete"}
    JSON  {"type":"error","message":"..."}
"""

import uuid
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.auth_service import decode_access_token
from app.agent.gemini.live_runner import GeminiLiveRunner, get_runner, get_runner_for_user, _active_runners

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"


@router.websocket("/ws/gemini-voice")
async def gemini_voice_websocket(websocket: WebSocket):
    """Gemini Native Audio WebSocket endpoint."""
    logger.info("Gemini voice WS: new connection from %s", websocket.client)
    await websocket.accept()
    logger.info("Gemini voice WS: accepted")

    user_id: Optional[str] = None
    session_id: Optional[str] = None
    mode: Optional[str] = None  # "voice" or "observer"
    runner: Optional[GeminiLiveRunner] = None

    try:
        # --- Phase 1: Auth ---
        logger.info("Gemini voice WS: waiting for auth message...")
        auth_data = await websocket.receive_json()
        logger.info("Gemini voice WS: received auth data: %s", auth_data)
        if auth_data.get("type") != "auth":
            await websocket.send_json({"type": "error", "message": "Expected auth message"})
            await websocket.close()
            return

        token = auth_data.get("token")
        session_id = auth_data.get("session_id") or str(uuid.uuid4())

        user_id = DEFAULT_USER_ID
        if token:
            token_data = decode_access_token(token)
            if not token_data:
                logger.warning("Gemini voice WS: invalid token")
                await websocket.send_json({"type": "error", "message": "Invalid or expired token"})
                await websocket.close()
                return
            user_id = token_data.user_id

        logger.info("Gemini voice WS: auth success, user=%s, session=%s", user_id, session_id)
        await websocket.send_json({
            "type": "auth_success",
            "user_id": user_id,
            "session_id": session_id,
        })

        # --- Phase 2: Config ---
        config_data = await websocket.receive_json()
        if config_data.get("type") != "config":
            await websocket.send_json({"type": "error", "message": "Expected config message"})
            await websocket.close()
            return

        mode = config_data.get("mode", "voice")

        if mode == "voice":
            # Check for existing runner (reconnection)
            runner = get_runner(session_id)
            if not runner:
                runner = GeminiLiveRunner(user_id=user_id, session_id=session_id)
                try:
                    await runner.start()
                except Exception as e:
                    logger.exception("Gemini voice WS: failed to start runner: %s", e)
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Gemini connection failed: {e}",
                    })
                    await websocket.close()
                    return

            runner.add_voice_client(websocket)
            await websocket.send_json({"type": "ready", "mode": "voice"})

        elif mode == "observer":
            # Observer joins an existing session (try exact ID first, then any session for this user)
            runner = get_runner(session_id) or get_runner_for_user(user_id)
            if not runner:
                await websocket.send_json({
                    "type": "error",
                    "message": "No active voice session found",
                })
                await websocket.close()
                return
            logger.info("Gemini voice WS: observer joining runner session=%s", runner.session_id)

            runner.add_observer_client(websocket)
            await websocket.send_json({"type": "ready", "mode": "observer"})

        else:
            await websocket.send_json({"type": "error", "message": f"Unknown mode: {mode}"})
            await websocket.close()
            return

        # --- Phase 3: Message loop ---
        while True:
            message = await websocket.receive()

            # Binary frame = PCM audio (voice mode)
            if "bytes" in message and message["bytes"]:
                if mode == "voice" and runner:
                    await runner.handle_audio(message["bytes"])
                continue

            # Text frame = JSON
            if "text" in message and message["text"]:
                try:
                    data = __import__("json").loads(message["text"])
                except Exception:
                    continue

                msg_type = data.get("type")

                if msg_type == "ping":
                    await websocket.send_json({"type": "pong"})

                elif msg_type == "text":
                    text = (data.get("text") or "").strip()
                    if text and runner:
                        await runner.handle_text(text)

                elif msg_type == "stop":
                    # Client requests session stop
                    break

    except WebSocketDisconnect:
        logger.info("Gemini voice WebSocket disconnected (session=%s, mode=%s)", session_id, mode)
    except Exception as e:
        logger.exception("Gemini voice WebSocket error: %s", e)
    finally:
        # Clean up
        if runner:
            if mode == "voice":
                runner.remove_voice_client(websocket)
                # If no more voice clients, stop the runner
                if not runner._voice_clients:
                    await runner.stop()
            elif mode == "observer":
                runner.remove_observer_client(websocket)
