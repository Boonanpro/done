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
from app.agent.v2.tools import (
    execute_tool, format_tool_result, parse_tool_name,
    get_all_skill_tools, SkillRegistry,
)
from app.agent.v2.runner import (
    get_core_prompt, load_all_bootstrap_files, WORKSPACE_DIR,
)
from app.agent.gemini.session import get_gemini_session_store
from app.config import settings

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


VOICE_SYSTEM_RULES = """
## 音声会話ルール
1. 応答は簡潔に。長文を避け、自然な会話調で。
2. ツール実行前に一言声をかける（「確認しますね」「調べてみますね」）
3. ツール結果は要約で報告。詳細HTMLやURL一覧は読み上げない。
4. 長い作業の後は「報告してもよろしいですか？」と確認。
5. 重要な操作（予約、購入）の前は必ず確認。
6. ユーザーの言語に合わせて返答する。
"""


class GeminiLiveRunner:
    """Orchestrates a Gemini Live API voice session with tool execution."""

    def __init__(self, user_id: str, session_id: str):
        self.user_id = user_id
        self.session_id = session_id
        self._gemini = GeminiLiveClient()
        self._voice_clients: Set[WebSocket] = set()
        self._observer_clients: Set[WebSocket] = set()
        self._running = False
        self._response_task: Optional[asyncio.Task] = None
        self._delayed_stop_task: Optional[asyncio.Task] = None
        self._conversation_log: List[Dict[str, Any]] = []

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
        """Wait, then stop if no voice clients have reconnected."""
        try:
            await asyncio.sleep(delay)
            if not self._voice_clients:
                logger.info("No voice clients after %.0fs, stopping (session=%s)", delay, self.session_id)
                await self.stop()
            else:
                logger.info("Voice client reconnected, delayed stop aborted (session=%s)", self.session_id)
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

        # Persist conversation log
        if self._conversation_log:
            try:
                store = get_gemini_session_store()
                await store.save_conversation(
                    session_id=self.session_id,
                    user_id=self.user_id,
                    conversation_log=self._conversation_log,
                )
            except Exception as e:
                logger.error("Failed to persist conversation: %s", e)

        logger.info("GeminiLiveRunner stopped (session=%s)", self.session_id)

    async def handle_audio(self, pcm_bytes: bytes) -> None:
        """Forward PCM audio from voice client to Gemini."""
        if self._running:
            await self._gemini.send_audio(pcm_bytes)

    async def handle_text(self, text: str) -> None:
        """Forward text input (from PC observer) to Gemini."""
        if self._running:
            self._log_conversation("user", text)
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

        # --- Audio data + text ---
        if message.server_content and message.server_content.model_turn:
            for part in message.server_content.model_turn.parts:
                # Audio chunk → broadcast to voice clients
                if part.inline_data and part.inline_data.data:
                    await self._broadcast_audio(part.inline_data.data)

                # Text output = model's internal reasoning (NOT spoken audio)
                # Send as process_step so it shows in process monitor, not chat
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
                self._log_conversation("user", text)
                await self._notify_observers({
                    "type": "user_text",
                    "text": text,
                })

        # --- Output transcription (model's audio → text) ---
        if message.server_content and message.server_content.output_transcription:
            text = (message.server_content.output_transcription.text or "").strip()
            if text:
                self._log_conversation("assistant", text)
                await self._notify_observers({
                    "type": "assistant_text",
                    "text": text,
                })

        # --- Turn complete ---
        if message.server_content and message.server_content.turn_complete:
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
        """Build the system prompt (reuses Claude's bootstrap files)."""
        parts = []

        # Core prompt
        parts.append(get_core_prompt())

        # Current datetime
        now = datetime.now()
        weekdays = ['月', '火', '水', '木', '金', '土', '日']
        parts.append(f"""## 現在の日時
- 今日: {now.strftime('%Y年%m月%d日')}（{weekdays[now.weekday()]}曜日）
- 現在時刻: {now.strftime('%H:%M')}""")

        # Tools list (for model awareness)
        tools = get_all_skill_tools()
        tool_lines = ["## 利用可能なツール"]
        for tool in tools:
            name = tool.get("name", "")
            desc = tool.get("description", "").split("\n")[0]
            tool_lines.append(f"- `{name}`: {desc}")
        tool_lines.append("- `google_search`: Web検索（自動実行）")
        parts.append("\n".join(tool_lines))

        # Skill list
        skills = SkillRegistry.list_all()
        if skills:
            skill_lines = ["## 利用可能なスキル", ""]
            for skill in skills:
                skill_lines.append(f"- `{skill.name}`: {skill.description}")
            skill_lines.append("")
            skill_lines.append("### スキル使用ルール（必須）")
            skill_lines.append("")
            skill_lines.append("1. ユーザーの依頼が上記スキルに該当する場合、**必ず最初に `check_skill` ツールで手順書を取得すること**。")
            skill_lines.append("2. 手順書を取得したら、その手順に従って `browser_open`/`browser_click`/`browser_type` 等で操作する。")
            skill_lines.append("3. 該当するスキルがない場合は、自分の判断でブラウザ操作して構わない。")
            parts.append("\n".join(skill_lines))

        # Bootstrap files (USER → MEMORY → SOUL → RULES)
        bootstrap = load_all_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        # Voice-specific rules (last for recency bias)
        parts.append(VOICE_SYSTEM_RULES)

        return "\n\n---\n\n".join(parts)

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
