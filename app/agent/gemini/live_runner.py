"""
GeminiLiveRunner — Main orchestrator for Gemini Native Audio voice sessions.

Bridges:
  - Voice devices (WebSocket, binary PCM audio)
  - PC observer clients (WebSocket, JSON text/steps)
  - Gemini Live API (audio + function calling)

Reuses existing tool infrastructure from app.agent.v2.tools.
"""

import json
import logging
import asyncio
from typing import Optional, Dict, Any, List, Set
from datetime import datetime

from fastapi import WebSocket

from google.genai import types as genai_types

from app.agent.gemini.client import GeminiLiveClient
from app.agent.gemini.tool_converter import convert_all_tools
from app.agent.gemini.prompt_builder import build_system_prompt
from app.agent.v2.tools import (
    execute_tool, format_tool_result, parse_tool_name,
    get_all_skill_tools,
)

logger = logging.getLogger(__name__)

# Active runners keyed by session_id
_active_runners: Dict[str, "GeminiLiveRunner"] = {}


def get_runner(session_id: str) -> Optional["GeminiLiveRunner"]:
    """Get an active runner by session ID."""
    return _active_runners.get(session_id)


def get_runner_for_user(user_id: str) -> Optional["GeminiLiveRunner"]:
    """Get any active runner for a given user (for observer auto-discovery)."""
    for runner in _active_runners.values():
        if runner.user_id == user_id:
            return runner
    return None



class GeminiLiveRunner:
    """Orchestrates a Gemini Live API voice session with tool execution."""

    def __init__(self, user_id: str, session_id: str, text_mode: bool = False):
        self.user_id = user_id
        self.session_id = session_id
        self.text_mode = text_mode
        self._gemini = GeminiLiveClient(text_mode=text_mode)
        self._voice_clients: Set[WebSocket] = set()
        self._observer_clients: Set[WebSocket] = set()
        self._running = False
        self._response_task: Optional[asyncio.Task] = None
        self._delayed_stop_task: Optional[asyncio.Task] = None
        self._conversation_log: List[Dict[str, Any]] = []
        # Turn-level buffers for DB persistence
        self._current_turn_user_text = ""
        self._current_turn_assistant_text = ""

    @property
    def is_active(self) -> bool:
        return self._running

    def add_voice_client(self, ws: WebSocket) -> None:
        self._voice_clients.add(ws)
        logger.info("Voice client added (session=%s, total=%d)", self.session_id, len(self._voice_clients))

    def remove_voice_client(self, ws: WebSocket) -> None:
        self._voice_clients.discard(ws)
        logger.info("Voice client removed (session=%s, remaining=%d)", self.session_id, len(self._voice_clients))

    def add_observer_client(self, ws: WebSocket) -> None:
        self._observer_clients.add(ws)
        logger.info("Observer client added (session=%s, total=%d)", self.session_id, len(self._observer_clients))

    def remove_observer_client(self, ws: WebSocket) -> None:
        self._observer_clients.discard(ws)
        logger.info("Observer client removed (session=%s, remaining=%d)", self.session_id, len(self._observer_clients))

    def schedule_delayed_stop(self, delay: float = 30.0) -> None:
        """Schedule a stop after `delay` seconds unless a voice client reconnects."""
        if self._delayed_stop_task and not self._delayed_stop_task.done():
            return  # Already scheduled
        self._delayed_stop_task = asyncio.create_task(self._delayed_stop(delay))
        logger.info("Delayed stop scheduled in %.0fs (session=%s)", delay, self.session_id)

    def cancel_delayed_stop(self) -> None:
        """Cancel a pending delayed stop (voice client reconnected)."""
        if self._delayed_stop_task and not self._delayed_stop_task.done():
            self._delayed_stop_task.cancel()
            self._delayed_stop_task = None
            logger.info("Delayed stop cancelled (session=%s)", self.session_id)

    async def _delayed_stop(self, delay: float) -> None:
        """Wait, then stop if no clients have reconnected."""
        try:
            await asyncio.sleep(delay)
            if not self._voice_clients and not self._observer_clients:
                logger.info("No clients after %.0fs, stopping (session=%s)", delay, self.session_id)
                await self.stop()
            else:
                logger.info("Client reconnected, delayed stop aborted (session=%s)", self.session_id)
        except asyncio.CancelledError:
            pass

    async def start(self) -> None:
        """Build system prompt, convert tools, connect to Gemini Live API."""
        system_prompt = self._build_system_prompt()
        anthropic_tools = get_all_skill_tools()
        gemini_tools = convert_all_tools(anthropic_tools)

        await self._gemini.connect(
            system_instruction=system_prompt,
            tools=gemini_tools,
        )

        self._running = True
        _active_runners[self.session_id] = self

        # Start the response loop in background
        self._response_task = asyncio.create_task(self._run_response_loop())
        logger.info("GeminiLiveRunner started (session=%s)", self.session_id)

    async def stop(self) -> None:
        """Shut down the session and persist conversation."""
        self._running = False
        _active_runners.pop(self.session_id, None)

        # Cancel any pending delayed stop
        if self._delayed_stop_task and not self._delayed_stop_task.done():
            self._delayed_stop_task.cancel()
            self._delayed_stop_task = None

        # Notify all clients that the session is ending
        end_msg = json.dumps({"type": "session_ended"})
        for ws in list(self._observer_clients) + list(self._voice_clients):
            try:
                await ws.send_text(end_msg)
            except Exception:
                pass

        if self._response_task and not self._response_task.done():
            self._response_task.cancel()
            try:
                await self._response_task
            except asyncio.CancelledError:
                pass

        await self._gemini.close()

        # Persist any remaining buffered turn (in case turn_complete wasn't received)
        if self._current_turn_user_text or self._current_turn_assistant_text:
            try:
                await self._persist_turn()
            except Exception as e:
                logger.error("Failed to persist final turn: %s", e)

        logger.info("GeminiLiveRunner stopped (session=%s)", self.session_id)

    async def handle_audio(self, pcm_bytes: bytes) -> None:
        """Forward PCM audio from voice client to Gemini."""
        if self._running:
            await self._gemini.send_audio(pcm_bytes)

    async def handle_text(self, text: str, save_user_to_db: bool = False) -> None:
        """Forward text input to Gemini.

        Args:
            text: User text message.
            save_user_to_db: If True, save user message to chat_messages (text mode).
        """
        if self._running:
            self._log_conversation("user", text)
            self._current_turn_user_text += text

            if save_user_to_db:
                try:
                    await self._save_user_message_to_db(text)
                except Exception as e:
                    logger.error("Failed to save user message to DB: %s", e)

            await self._notify_observers({
                "type": "user_text",
                "text": text,
            })
            await self._gemini.send_text(text)

    # ----------------------------------------------------------------
    # Response loop: reads from Gemini, dispatches audio/text/tools
    # ----------------------------------------------------------------

    async def _run_response_loop(self) -> None:
        """Main loop: receive messages from Gemini and dispatch."""
        try:
            async for message in self._gemini.receive():
                if not self._running:
                    break
                await self._handle_server_message(message)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("Gemini response loop error: %s", e)
            await self._notify_observers({
                "type": "error",
                "message": f"Gemini session error: {e}",
            })
        finally:
            self._running = False
            _active_runners.pop(self.session_id, None)

    async def _handle_server_message(self, message: genai_types.LiveServerMessage) -> None:
        """Process a single server message from Gemini."""

        # --- Audio data + text (model_turn) ---
        if message.server_content and message.server_content.model_turn:
            for part in message.server_content.model_turn.parts:
                # Audio chunk → broadcast to voice clients (only when voice clients connected)
                if part.inline_data and part.inline_data.data:
                    if self._voice_clients:
                        await self._broadcast_audio(part.inline_data.data)

                # Text in model_turn is always thinking/reasoning (both modes).
                # Actual response comes via output_transcription (audio→text).
                if part.text:
                    text = part.text.strip()
                    if text:
                        self._log_conversation("thinking", text)
                        await self._notify_observers({
                            "type": "process_step",
                            "step": text,
                        })

        # --- Input transcription (user's speech → text) ---
        if message.server_content and message.server_content.input_transcription:
            text = (message.server_content.input_transcription.text or "").strip()
            if text:
                self._current_turn_user_text += text
                self._log_conversation("user", text)
                await self._notify_observers({
                    "type": "user_text",
                    "text": text,
                })

        # --- Output transcription (model's audio → text) ---
        if message.server_content and message.server_content.output_transcription:
            text = (message.server_content.output_transcription.text or "").strip()
            if text:
                self._current_turn_assistant_text += text
                self._log_conversation("assistant", text)
                await self._notify_observers({
                    "type": "assistant_text",
                    "text": text,
                })

        # --- Turn complete ---
        if message.server_content and message.server_content.turn_complete:
            await self._persist_turn()
            await self._notify_observers({"type": "turn_complete"})

        # --- Tool calls ---
        if message.tool_call:
            await self._handle_tool_calls(message.tool_call)

    async def _handle_tool_calls(self, tool_call: genai_types.LiveServerToolCall) -> None:
        """Execute function calls from Gemini and return results."""
        function_responses = []

        for fc in tool_call.function_calls:
            tool_name = fc.name
            params = dict(fc.args) if fc.args else {}

            logger.info("Gemini tool call: %s(%s)", tool_name, params)

            # Notify observers
            await self._notify_observers({
                "type": "tool_start",
                "tool": tool_name,
                "params": params,
            })

            # Parse tool name to get skill/action (reuse existing parser)
            parsed = parse_tool_name(tool_name)
            if not parsed:
                logger.warning("Unknown tool name from Gemini: %s", tool_name)
                result = {"success": False, "error": f"Unknown tool: {tool_name}"}
                function_responses.append(
                    genai_types.FunctionResponse(
                        id=fc.id,
                        name=tool_name,
                        response={"result": f"Error: unknown tool '{tool_name}'"},
                    )
                )
                continue

            skill_name = parsed[0]
            action = parsed[1]

            tool_call_dict = {
                "skill": skill_name,
                "action": action,
                "params": params,
            }

            # Log
            self._log_conversation("tool_call", json.dumps({
                "tool": tool_name, "params": params,
            }, ensure_ascii=False))

            # Execute
            try:
                result = await execute_tool(
                    tool_call=tool_call_dict,
                    user_id=self.user_id,
                    session_id=self.session_id,
                )
            except Exception as e:
                logger.exception("Tool execution error: %s", e)
                result = {"success": False, "error": str(e)}

            success = result.get("success", False)

            # Notify observers of result
            await self._notify_observers({
                "type": "tool_result",
                "tool": tool_name,
                "success": success,
                "summary": result.get("message", "")[:200],
            })

            # Format result text for Gemini
            formatted = format_tool_result(result, skill_name, action)
            result_text = formatted.text

            self._log_conversation("tool_result", json.dumps({
                "tool": tool_name,
                "success": success,
                "text": result_text[:500],
            }, ensure_ascii=False))

            function_responses.append(
                genai_types.FunctionResponse(
                    id=fc.id,
                    name=tool_name,
                    response={"result": result_text},
                )
            )

        # Send all responses back to Gemini
        try:
            await self._gemini.send_tool_response(function_responses)
        except Exception as e:
            logger.exception("Failed to send tool response to Gemini: %s", e)
            await self._notify_observers({
                "type": "error",
                "message": f"Tool response error: {e}",
            })

    # ----------------------------------------------------------------
    # Persistence: save voice turns to DB
    # ----------------------------------------------------------------

    async def _persist_turn(self) -> None:
        """Persist the current turn's user/assistant text to DB, then reset buffers."""
        user_text = self._current_turn_user_text.strip()
        assistant_text = self._current_turn_assistant_text.strip()
        self._current_turn_user_text = ""
        self._current_turn_assistant_text = ""

        if not user_text and not assistant_text:
            return

        room_id = self.session_id  # session_id == room_id in this system

        try:
            await self._save_to_chat_messages(room_id, user_text, assistant_text)
        except Exception as e:
            logger.error("Failed to save voice turn to chat_messages: %s", e)

        try:
            await self._inject_into_agent_session(room_id, user_text, assistant_text)
        except Exception as e:
            logger.error("Failed to inject voice turn into agent session: %s", e)

    async def _save_user_message_to_db(self, text: str) -> None:
        """Save a user message to chat_messages immediately (text mode)."""
        from app.services.supabase_client import get_supabase_client
        supabase = get_supabase_client().client

        supabase.table("chat_messages").insert({
            "room_id": self.session_id,
            "sender_id": self.user_id,
            "sender_type": "human",
            "content": text,
            "ai_context": {"source": "text", "provider": "gemini"},
        }).execute()

    async def _save_to_chat_messages(self, room_id: str, user_text: str, assistant_text: str) -> None:
        """Insert turn messages into chat_messages table."""
        from app.services.supabase_client import get_supabase_client
        supabase = get_supabase_client().client

        source = "text" if self.text_mode else "voice"

        rows = []
        # In text mode, user message is already saved by _save_user_message_to_db
        if user_text and not self.text_mode:
            rows.append({
                "room_id": room_id,
                "sender_id": self.user_id,
                "sender_type": "human",
                "content": user_text,
                "ai_context": {"source": source, "provider": "gemini"},
            })
        if assistant_text:
            rows.append({
                "room_id": room_id,
                "sender_id": None,
                "sender_type": "ai",
                "content": assistant_text,
                "ai_context": {"source": source, "provider": "gemini"},
            })

        for row in rows:
            supabase.table("chat_messages").insert(row).execute()

    async def _inject_into_agent_session(self, room_id: str, user_text: str, assistant_text: str) -> None:
        """Inject voice conversation into the Claude agent session for context continuity."""
        from app.agent.v2.session import get_session_store

        store = get_session_store()
        session = await store.get_or_create(room_id, self.user_id)

        if user_text:
            session.add_user_message(f"[音声会話] {user_text}")
        if assistant_text:
            session.add_assistant_message(f"[音声会話] {assistant_text}")

        await store.save(session)

    # ----------------------------------------------------------------
    # Broadcasting helpers
    # ----------------------------------------------------------------

    async def _broadcast_audio(self, audio_bytes: bytes) -> None:
        """Send audio data to all connected voice clients."""
        disconnected = []
        for ws in self._voice_clients:
            try:
                await ws.send_bytes(audio_bytes)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self._voice_clients.discard(ws)

    async def _notify_observers(self, data: Dict[str, Any]) -> None:
        """Send JSON message to all observer clients (and voice clients for text)."""
        msg = json.dumps(data, ensure_ascii=False)
        disconnected = []

        # Send to observers
        for ws in self._observer_clients:
            try:
                await ws.send_text(msg)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self._observer_clients.discard(ws)

        # Also send text messages to voice clients (for display)
        if data.get("type") in ("assistant_text", "process_step", "tool_start", "tool_result", "turn_complete"):
            disconnected = []
            for ws in self._voice_clients:
                try:
                    await ws.send_text(msg)
                except Exception:
                    disconnected.append(ws)
            for ws in disconnected:
                self._voice_clients.discard(ws)

    # ----------------------------------------------------------------
    # System prompt
    # ----------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Build the system prompt."""
        return build_system_prompt(
            include_voice_rules=not self.text_mode,
            session_id=self.session_id,
        )

    # ----------------------------------------------------------------
    # Conversation logging
    # ----------------------------------------------------------------

    def _log_conversation(self, role: str, content: str) -> None:
        """Record a conversation entry for later persistence."""
        self._conversation_log.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })

    def get_conversation_log(self) -> List[Dict[str, Any]]:
        """Return the conversation log for persistence."""
        return list(self._conversation_log)
