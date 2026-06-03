"""
CLI Runner - プロジェクト実行をClaude CLI (subprocess) で行う

SDK経由だとTask tool（分身）がフリーズする問題を回避するため、
CLIプロセスを直接起動してJSON streamを読む方式に切り替え。

Windows + uvicorn の制約:
  uvicorn --reload は SelectorEventLoop を使うため、サブプロセス生成ができない。
  → CLI呼び出しを別スレッドで実行し、そのスレッド内でsubprocessを管理する。
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
import queue as thread_queue
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional, Dict, Any

logger = logging.getLogger(__name__)

# セッション管理: インメモリキャッシュ + DB永続化
_cli_sessions: Dict[str, str] = {}

PROJECT_ROOT = Path(__file__).parent.parent.parent  # app/agent/ → app/ → D:\done\

# 事業部の作業ディレクトリ（D:\done の外に置くことで開発者向け CLAUDE.md の混入を防ぐ）
CLI_WORKSPACE = Path("D:/dan-workspace")
CLI_WORKSPACE.mkdir(parents=True, exist_ok=True)

# ワンショット生成（タイトル等）専用の中立な空ディレクトリ。
# CLAUDE.md / MCP / プロジェクト設定を一切読み込ませず、起動を軽く・出力を素にする。
_ONESHOT_CWD = Path(tempfile.gettempdir()) / "dan_oneshot"
_ONESHOT_CWD.mkdir(parents=True, exist_ok=True)

_SENTINEL = object()  # キュー終了シグナル

# Streaming path tuning.
# Idle (no-output) seconds before a turn is treated as hung. This is NOT a cap
# on total turn duration — an actively streaming turn runs as long as it needs.
# Generous so a long bash/build or a Task subagent that stays quiet for a while
# is not mistaken for a hang.
_STREAMING_IDLE_TIMEOUT = int(os.getenv("DAN_STREAMING_IDLE_TIMEOUT", "1800"))
# Cadence for SSE keepalive frames during silent-but-active stretches so proxies
# don't drop the connection and the live view doesn't blank out.
_STREAMING_KEEPALIVE_SECONDS = 20

# アクティブなCLIプロセスを追跡（room_id → Popen）
_active_processes: Dict[str, subprocess.Popen] = {}
_process_lock = threading.Lock()
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

# 停止されたroom_idを記録（次回起動時に--fork-sessionを付けるため）
_interrupted_rooms: set = set()

# スレッドローカル: 現在のroom_idを自動追跡（_cli_debugで使用）
_thread_local = threading.local()


def _env_flag(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() not in {"0", "false", "no", "off"}


def _latency_debug(message: str) -> None:
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        with (PROJECT_ROOT / "dan_latency.log").open("a", encoding="utf-8") as f:
            f.write(f"{timestamp} {message}\n")
    except Exception:
        logger.debug("Failed to write DAN latency log", exc_info=True)


def is_cli_active(room_id: str) -> bool:
    """CLIサブプロセスがまだ実行中かどうかを返す"""
    with _process_lock:
        return room_id in _active_processes


def kill_cli_process(room_id: str) -> bool:
    """CLIサブプロセスを即座に終了する"""
    with _process_lock:
        process = _active_processes.pop(room_id, None)
    if process is None:
        return False
    _interrupted_rooms.add(room_id)
    _terminate_process(process)
    return True


def _terminate_process(process: subprocess.Popen):
    """プロセスをterminate→wait→kill（フォールバック）で確実に終了させる"""
    try:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _cli_debug(f"Process PID={process.pid} did not exit after terminate, using kill()")
            process.kill()
            process.wait(timeout=3)
    except Exception as e:
        _cli_debug(f"_terminate_process error: {e}")


def _load_session(room_id: str) -> Optional[str]:
    """DBからCLIセッションIDを読み込む（インメモリキャッシュ優先）"""
    if room_id in _cli_sessions:
        return _cli_sessions[room_id]
    try:
        from app.services.supabase_client import get_supabase_client
        sb = get_supabase_client().client
        result = sb.table("cli_sessions").select("cli_session_id").eq("room_id", room_id).execute()
        if result.data:
            session_id = result.data[0].get("cli_session_id")
            if session_id:
                _cli_sessions[room_id] = session_id
                return session_id
    except Exception as e:
        logger.warning(f"Failed to load CLI session for {room_id}: {e}")
    return None


def _save_session(room_id: str, session_id: str):
    """CLIセッションIDをDBに永続化"""
    _cli_sessions[room_id] = session_id
    try:
        from app.services.supabase_client import get_supabase_client
        from datetime import datetime, timezone
        sb = get_supabase_client().client
        sb.table("cli_sessions").upsert({
            "room_id": room_id,
            "cli_session_id": session_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        logger.warning(f"Failed to save CLI session for {room_id}: {e}")


def _clear_cli_session(room_id: str) -> None:
    """Forget a room's saved Claude CLI session (in-memory cache + DB) so the
    next turn starts a fresh conversation instead of resuming a stale or
    poisoned transcript."""
    _cli_sessions.pop(room_id, None)
    try:
        from app.services.supabase_client import get_supabase_client
        get_supabase_client().client.table("cli_sessions").delete().eq("room_id", room_id).execute()
    except Exception as e:
        _cli_debug(f"_clear_cli_session failed: {e}")


def _is_parse_error_text(text: Optional[str]) -> bool:
    """True when a turn result is the CLI's unparseable-tool-call error — the
    signature of the `<invoke>`-as-text leak that poisons a session."""
    return "could not be parsed" in (text or "").lower()


def _is_thinking_desync_error(text: Optional[str]) -> bool:
    """True when a turn failed with the Anthropic 400 that says the assistant's
    `thinking`/`redacted_thinking` blocks were modified, e.g.:

        API Error: 400 messages.N.content.M: thinking or redacted_thinking
        blocks in the latest assistant message cannot be modified. These blocks
        must remain as they were in the original response.

    This happens when a --resume transcript ended up with a turn split across
    messages (a lone `[thinking]` assistant message separated from its `[text]`
    continuation), so replaying it no longer byte-matches the signed original.
    The transcript can't be salvaged in place — like a parse-error poison, the
    only fix is to drop the session and reseed from the DB so the next turn
    starts a fresh, well-formed conversation with the context preserved."""
    low = (text or "").lower()
    return (
        ("thinking" in low and "cannot be modified" in low)
        or "thinking or redacted_thinking blocks" in low
    )


# Lines from history that would re-poison a fresh session if fed back verbatim.
_RESEED_SKIP_MARKERS = ("<invoke", "could not be parsed", "function_calls")


def _detect_user_lang(text: Optional[str]) -> str:
    """Best-effort UI language for harness-generated notices (recovery messages),
    inferred from the user's own message. Returns 'ja' when it contains Japanese
    kana/kanji, 'en' when it is basically Latin script, else 'ja' (this
    deployment's default). Intentionally simple — extend the map below to add
    languages."""
    s = text or ""
    for ch in s:
        o = ord(ch)
        if (0x3040 <= o <= 0x30FF) or (0x4E00 <= o <= 0x9FFF) or (0xFF66 <= o <= 0xFF9D):
            return "ja"
    if any("a" <= c.lower() <= "z" for c in s):
        return "en"
    return "ja"


# Harness-generated recovery notices, by kind and language. These are NOT model
# output — they replace the CLI's cryptic English errors (e.g. the parse-error
# poison) with a clear, localized note telling the user the session was rebuilt
# (context preserved) and they can just resend.
_RECOVERY_MESSAGES = {
    "parse_error": {
        "ja": "うまく処理できませんでした（内部のツール呼び出しが壊れました）。"
        "文脈は保持したままセッションを立て直したので、もう一度同じ内容を送ってください。",
        "en": "Something went wrong (an internal tool call was malformed). "
        "I rebuilt the session with the context preserved — please send the same message again.",
    },
    "thinking_desync": {
        "ja": "前回の会話の内部状態が壊れていたため、文脈は保持したまま"
        "セッションを立て直しました。もう一度同じ内容を送ってください。",
        "en": "The previous turn's internal state was corrupted, so I rebuilt the "
        "session with the context preserved. Please send the same message again.",
    },
    "idle_hang": {
        "ja": "（長時間の処理が一定時間まったく応答しなくなったため、ここで一旦区切りました。"
        "ツールは実行済み＝作業自体は進んでいる場合があります。"
        "「続きをやって」や「今どこまで終わってる？」と送ってください。）",
        "en": "(A long-running task went silent for a while, so I paused here. Tools may "
        "have already run, so the work itself may have progressed. Send \"continue\" "
        "or \"where are we?\" to resume.)",
    },
}


def _recovery_message(kind: str, lang: str = "ja") -> str:
    """Return a localized harness recovery notice, falling back to Japanese."""
    by_lang = _RECOVERY_MESSAGES.get(kind, {})
    return by_lang.get(lang) or by_lang.get("ja", "")


def _one_line(value: Any, limit: int = 240) -> str:
    """Compact DB text for room-state prompts without doing an LLM summary."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = " ".join(part.strip() for part in text.split("\n") if part.strip())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _is_underspecified_continuation(text: str) -> bool:
    """Short messages that depend on current room context, not global memory."""
    s = unicodedata.normalize("NFKC", text or "").strip().lower()
    s = s.strip(" \t\r\n。、.!?！？")
    if not s or len(s) > 80:
        return False
    markers = (
        "continue",
        "go on",
        "resume",
        "carry on",
        "where were we",
        "what were we doing",
        "\u7d9a\u3051\u3066",      # 続けて
        "\u7d9a\u304d",            # 続き
        "\u3064\u3065\u3051\u3066",  # つづけて
        "\u4eca\u3069\u3053\u307e\u3067",  # 今どこまで
        "\u3069\u3053\u307e\u3067",        # どこまで
        "\u3055\u3063\u304d\u306e\u7d9a\u304d",  # さっきの続き
    )
    return any(marker in s for marker in markers)


def _build_room_state_context(
    room_id: str,
    project_id: Optional[str] = None,
    *,
    max_chars: int = 2500,
    message_limit: int = 8,
    event_limit: int = 16,
    run_limit: int = 3,
) -> str:
    """Build a small authoritative room state from DB.

    This is intentionally cheap and rule-based. The full chat DB remains the
    source of truth, while this snapshot gives the model enough context to avoid
    falling back to global Claude history when its CLI transcript is missing or
    unreliable.
    """
    if not room_id:
        return ""
    try:
        from app.services.supabase_client import get_supabase_client

        sb = get_supabase_client().client
        messages = (
            sb.table("chat_messages")
            .select("sender_type,content,created_at")
            .eq("room_id", room_id)
            .order("created_at", desc=True)
            .limit(message_limit)
            .execute()
        ).data or []

        runs = (
            sb.table("agent_runs")
            .select("id,state,created_at,updated_at,claude_session_id,metadata")
            .eq("room_id", room_id)
            .order("created_at", desc=True)
            .limit(run_limit)
            .execute()
        ).data or []

        events_query = (
            sb.table("execution_events")
            .select("event_type,tool_name,tool_label,content,created_at,run_id,seq")
            .eq("room_id", room_id)
            .order("seq", desc=True)
            .limit(event_limit)
        )
        events = events_query.execute().data or []

        project = None
        if project_id:
            result = (
                sb.table("projects")
                .select("id,title,status,description,updated_at")
                .eq("id", project_id)
                .limit(1)
                .execute()
            )
            if result.data:
                project = result.data[0]
    except Exception as e:
        _cli_debug(f"_build_room_state_context fetch failed: {e}")
        return ""

    lines = [
        "<room_state>",
        "Authoritative state from DAN DB for this room. Prefer this over any stale Claude CLI transcript.",
        f"room_id: {room_id}",
    ]
    if project:
        lines.extend([
            "project:",
            f"- title: {_one_line(project.get('title'), 120)}",
            f"- status: {_one_line(project.get('status'), 80)}",
            f"- description: {_one_line(project.get('description'), 260)}",
        ])

    if runs:
        lines.append("recent_runs:")
        for run in reversed(runs):
            sid = (run.get("claude_session_id") or "")[:8]
            lines.append(
                "- "
                f"{run.get('created_at', '')} state={run.get('state', '')} "
                f"run={str(run.get('id', ''))[:8]} cli={sid}"
            )

    if events:
        lines.append("recent_work_events:")
        for ev in reversed(events):
            label = ev.get("tool_label") or ev.get("content") or ev.get("tool_name") or ev.get("event_type")
            lines.append(
                "- "
                f"{ev.get('created_at', '')} {ev.get('event_type', '')}: "
                f"{_one_line(label, 180)}"
            )

    if messages:
        lines.append("recent_chat:")
        for msg in reversed(messages):
            content = (msg.get("content") or "").strip()
            if not content:
                continue
            low = content.lower()
            if any(mark in low for mark in _RESEED_SKIP_MARKERS):
                continue
            role = "user" if msg.get("sender_type") in ("human", "user") else "dan"
            lines.append(f"- {msg.get('created_at', '')} {role}: {_one_line(content, 260)}")

    lines.extend([
        "If the user asks to continue and the current task is unclear, infer from this room_state first.",
        "Do not say you cannot identify the prior work until you have used this room-specific DB state.",
        "</room_state>",
    ])
    body = "\n".join(line for line in lines if line is not None)
    if len(body) > max_chars:
        # Keep the header/rules and the most recent tail.
        head = "\n".join(lines[:4]) + "\n...\n"
        tail_budget = max(0, max_chars - len(head))
        body = head + body[-tail_budget:]
    return body


def _build_reseed_context_legacy_unused(room_id: str, max_chars: int = 8000, max_msgs: int = 40) -> str:
    """Rebuild a room's recent conversation from the DB as a context preamble
    for a FRESH session. Used after a poisoned/desynced session is dropped so
    Dan keeps the context (no re-explaining) without resuming the contaminated
    transcript. Contaminated lines are filtered out so they can't re-poison.
    Returns "" when there is no usable history."""
    try:
        from app.services.supabase_client import get_supabase_client
        rows = (
            get_supabase_client().client.table("chat_messages")
            .select("sender_type,content,created_at")
            .eq("room_id", room_id).order("created_at", desc=True).limit(max_msgs).execute()
        ).data or []
    except Exception as e:
        _cli_debug(f"_build_reseed_context fetch failed: {e}")
        return ""

    lines = []
    for m in reversed(rows):  # oldest -> newest
        content = (m.get("content") or "").strip()
        if not content:
            continue
        low = content.lower()
        if any(mark in low for mark in _RESEED_SKIP_MARKERS):
            continue  # never re-feed contaminated tool-call text
        who = "ユーザー" if m.get("sender_type") == "human" else "ダン"
        lines.append(f"{who}: {content[:1500]}")
    if not lines:
        return ""

    body = "\n".join(lines)
    if len(body) > max_chars:
        body = body[-max_chars:]  # keep the most recent
    return (
        "<conversation_so_far>\n"
        "（内部メモ: セッションがリセットされたため、この部屋のこれまでの会話を再共有します。"
        "この見出し自体やログはユーザーに表示しないこと。文脈として読み、続きから自然に対応してください。"
        "過去のやり取りを最初から繰り返し報告しないこと。）\n\n"
        f"{body}\n"
        "</conversation_so_far>"
    )


# Transcript size guard. A Claude CLI session transcript grows with every tool
def _build_reseed_context(
    room_id: str,
    project_id: Optional[str] = None,
    max_chars: int = 12000,
    max_msgs: int = 40,
) -> str:
    """Rebuild this room's context from DB for a fresh CLI session.

    This intentionally overrides the older chat-only implementation above.
    Recovery needs both chat text and work events; otherwise a fresh model can
    know the conversation topic but still miss where the actual work stopped.
    """
    try:
        from app.services.supabase_client import get_supabase_client

        sb = get_supabase_client().client
        rows = (
            sb.table("chat_messages")
            .select("sender_type,content,created_at")
            .eq("room_id", room_id)
            .order("created_at", desc=True)
            .limit(max_msgs)
            .execute()
        ).data or []
        events = (
            sb.table("execution_events")
            .select("event_type,tool_name,tool_label,content,created_at,run_id,seq")
            .eq("room_id", room_id)
            .order("seq", desc=True)
            .limit(40)
            .execute()
        ).data or []
        runs = (
            sb.table("agent_runs")
            .select("id,state,created_at,updated_at,claude_session_id,metadata")
            .eq("room_id", room_id)
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        ).data or []
    except Exception as e:
        _cli_debug(f"_build_reseed_context fetch failed: {e}")
        return ""

    state = _build_room_state_context(
        room_id,
        project_id,
        max_chars=5000,
        message_limit=12,
        event_limit=24,
        run_limit=5,
    )

    chat_lines = []
    for m in reversed(rows):
        content = (m.get("content") or "").strip()
        if not content:
            continue
        low = content.lower()
        if any(mark in low for mark in _RESEED_SKIP_MARKERS):
            continue
        who = "user" if m.get("sender_type") in ("human", "user") else "dan"
        chat_lines.append(f"- {m.get('created_at', '')} {who}: {_one_line(content, 900)}")

    event_lines = []
    for ev in reversed(events):
        label = ev.get("tool_label") or ev.get("content") or ev.get("tool_name") or ev.get("event_type")
        event_lines.append(
            f"- {ev.get('created_at', '')} {ev.get('event_type', '')}: {_one_line(label, 260)}"
        )

    run_lines = []
    for run in reversed(runs):
        run_lines.append(
            "- "
            f"{run.get('created_at', '')} state={run.get('state', '')} "
            f"run={str(run.get('id', ''))[:8]} cli={str(run.get('claude_session_id') or '')[:8]}"
        )

    sections = []
    if state:
        sections.append(state)
    if run_lines:
        sections.append("<recent_runs_full>\n" + "\n".join(run_lines) + "\n</recent_runs_full>")
    if event_lines:
        sections.append("<recent_work_events_full>\n" + "\n".join(event_lines) + "\n</recent_work_events_full>")
    if chat_lines:
        sections.append("<recent_chat_full>\n" + "\n".join(chat_lines) + "\n</recent_chat_full>")
    if not sections:
        return ""

    body = "\n\n".join(sections)
    if len(body) > max_chars:
        body = body[-max_chars:]
    return (
        "<conversation_so_far>\n"
        "Internal recovery context from this exact room. Use it as context only; "
        "do not quote this wrapper. Continue naturally from the latest room-specific "
        "state and avoid replaying old work.\n\n"
        f"{body}\n"
        "</conversation_so_far>"
    )


def _wrap_latest_user_message(context: str, content: str) -> str:
    if not context:
        return content
    return f"{context}\n\n<latest_user_message>\n{content}\n</latest_user_message>"


# Transcript size guard. A Claude CLI session transcript grows with every tool
# result (Read/Grep/Bash output, file contents, screenshots …). Once it is large,
# resuming it with --resume re-prefills the whole thing and the first token can
# take minutes. Above this size we drop the session and reseed from the DB
# instead: the conversation itself lives in chat_messages, so the context is
# preserved while the per-turn prompt shrinks back to
# system prompt + recent excerpt + the new message. This is the same mechanism
# used when a session is poisoned — here it fires on size. Set
# DAN_TRANSCRIPT_RESET_BYTES=0 to disable the guard.
_TRANSCRIPT_RESET_BYTES = int(os.getenv("DAN_TRANSCRIPT_RESET_BYTES", str(1_500_000)))


def _session_transcript_path(session_id: str) -> Optional[Path]:
    """Locate the Claude CLI transcript .jsonl for a session id, if present.

    The CLI stores transcripts under ~/.claude/projects/<cwd-slug>/<sid>.jsonl.
    We glob by session id so this does not depend on the cwd-slug naming.
    """
    if not session_id:
        return None
    projects = Path.home() / ".claude" / "projects"
    if not projects.exists():
        return None
    try:
        for p in projects.glob(f"*/{session_id}.jsonl"):
            return p
    except Exception:
        return None
    return None


def _transcript_exceeds_limit(session_id: str) -> bool:
    """True when a session transcript is big enough that a --resume prefill would
    dominate latency. Best-effort: returns False when the guard is disabled or
    the transcript file cannot be found."""
    if _TRANSCRIPT_RESET_BYTES <= 0:
        return False
    path = _session_transcript_path(session_id)
    if path is None:
        return False
    try:
        return path.stat().st_size >= _TRANSCRIPT_RESET_BYTES
    except Exception:
        return False


def _is_disconnect_error(err: Exception) -> bool:
    """Detect transient Supabase/httpx disconnect errors worth retrying once."""
    msg = str(err).lower()
    return (
        "server disconnected" in msg
        or "remotedisconnected" in msg
        or "connection reset" in msg
        or "connection aborted" in msg
        or "read timeout" in msg
        or "connection broken" in msg
    )


def _fresh_supabase_client():
    """Rebuild the Supabase client to recover from a stale/disconnected session."""
    from app.services import supabase_client as sbmod
    try:
        sbmod._supabase_client = None  # type: ignore[attr-defined]
    except Exception:
        pass
    return sbmod.get_supabase_client().client


def _save_execution_event_sync(
    room_id: str,
    event_type: str,
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    tool_label: Optional[str] = None,
    content: Optional[str] = None,
):
    """CLIスレッドからDB直接保存（sync）。disconnect時は1度だけ再接続リトライ。"""
    from app.services.execution_events import normalize_event_type
    from app.services.supabase_client import get_supabase_client

    normalized_type, original_type = normalize_event_type(event_type)
    metadata = {}
    if original_type is not None and original_type != normalized_type:
        metadata["original_event_type"] = original_type
    if turn_id:
        metadata["turn_id"] = turn_id
    row = {
        "room_id": room_id,
        "run_id": run_id,
        "turn_id": turn_id,
        "event_type": normalized_type,
        "tool_name": tool_name,
        "tool_label": tool_label,
        "content": content,
        "metadata": metadata,
    }
    if project_id:
        row["project_id"] = project_id

    for attempt in (1, 2):
        try:
            sb = get_supabase_client().client if attempt == 1 else _fresh_supabase_client()
            sb.table("execution_events").insert(row).execute()
            return
        except Exception as e:
            if attempt == 1 and _is_disconnect_error(e):
                _cli_debug(f"_save_execution_event_sync disconnect, retrying: {e}")
                continue
            _cli_debug(f"_save_execution_event_sync failed: {e}")
            return


def _update_run_sync(
    run_id: Optional[str],
    *,
    state: Optional[str] = None,
    claude_session_id: Optional[str] = None,
):
    """Best-effort sync update for the current agent run."""
    if not run_id:
        return
    try:
        from app.services.supabase_client import get_supabase_client

        updates = {}
        if state is not None:
            updates["state"] = state
        if claude_session_id is not None:
            updates["claude_session_id"] = claude_session_id
        if not updates:
            return

        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        sb = get_supabase_client().client
        sb.table("agent_runs").update(updates).eq("id", run_id).execute()
    except Exception as e:
        _cli_debug(f"_update_run_sync failed: {e}")


def _tool_detail(inp, limit: int = 4000) -> str:
    """Readable detail of a tool call's input for the expandable tool row.
    Picks the most useful field (command / file content / edit text / query),
    falling back to compact JSON, and caps the size so ai_context stays small.
    """
    if not inp:
        return ""
    if not isinstance(inp, dict):
        return str(inp)[:limit]
    for key in ("command", "content", "new_string", "code", "query", "prompt", "pattern"):
        v = inp.get(key)
        if isinstance(v, str) and v.strip():
            return v[:limit]
    try:
        s = json.dumps(inp, ensure_ascii=False)
    except Exception:
        s = str(inp)
    return s[:limit]


def _save_ai_message_sync(
    room_id: str,
    content: str,
    reasoning_steps: Optional[list] = None,
    reasoning_full: Optional[list] = None,
    blocks: Optional[list] = None,
    created_at: Optional[str] = None,
    turn_id: Optional[str] = None,
) -> bool:
    """CLIスレッドからAI応答をchat_messagesに直接保存（sync）。成功=True。disconnect時は1度だけリトライ。

    created_at: 明示指定時はその時刻で保存（既定はDBの now()）。ストリーミング経路が
    「ターン開始時刻」を渡すために使う。保存=ターン終了時刻だと、追い連絡で割り込まれた
    ターンの回答が追い連絡より後ろにずれて時系列が崩れるのを防ぐ。
    """
    from app.services.supabase_client import get_supabase_client
    from app.services.chat_service import record_message_delivery_sync
    from app.services.artifact_url_guard import sanitize_artifact_public_urls

    content = sanitize_artifact_public_urls(content)
    if blocks:
        blocks = [
            {**b, "text": sanitize_artifact_public_urls(b.get("text", ""))}
            if isinstance(b, dict) and b.get("type") == "text"
            else b
            for b in blocks
        ]

    ai_context: Optional[dict] = None
    if reasoning_steps:
        ai_context = {"reasoning_steps": reasoning_steps}
        if reasoning_full:
            ai_context["reasoning_full"] = reasoning_full
    # 時系列ブロック（text/tool を順序保持）。フロントのインライン時系列描画用。
    if blocks:
        ai_context = ai_context or {}
        ai_context["blocks"] = blocks
    if turn_id:
        ai_context = ai_context or {}
        ai_context["turn_id"] = turn_id
    insert_data = {
        "room_id": room_id,
        "sender_id": None,
        "sender_type": "ai",
        "content": content,
    }
    if created_at:
        insert_data["created_at"] = created_at
    if ai_context:
        insert_data["ai_context"] = ai_context

    for attempt in (1, 2):
        try:
            sb = get_supabase_client().client if attempt == 1 else _fresh_supabase_client()
            result = sb.table("chat_messages").insert(insert_data).execute()
            if result.data:
                msg_id = result.data[0].get("id")
                # Bump unread for room members so the sidebar/mobile show an
                # indicator. This is the same bookkeeping ChatService.send_*
                # does via _record_message_delivery; without it, AI replies
                # stay invisible as "unread" because we bypass the service.
                record_message_delivery_sync(sb, room_id, msg_id, content=content)
                _cli_debug(
                    f"_save_ai_message_sync OK (attempt {attempt}): msg_id={msg_id or '?'}"
                )
                return True
            _cli_debug(f"_save_ai_message_sync: insert returned no data (attempt {attempt})")
            if attempt == 2:
                return False
        except Exception as e:
            if attempt == 1 and _is_disconnect_error(e):
                _cli_debug(f"_save_ai_message_sync disconnect, retrying: {e}")
                continue
            _cli_debug(f"_save_ai_message_sync failed (attempt {attempt}): {e}")
            return False
    return False


def _build_runtime_contract_section() -> str:
    """Build runtime contract for CLI chat from one versioned template file."""
    from app.agent.v2.tools import (
        SkillRegistry,
        get_all_skill_tools,
    )
    from app.agent.runtime_contract import render_runtime_contract

    cli_builtin_tools = ["read_file", "write_file", "edit_file", "bash", "glob", "grep"]
    mcp_tools = get_all_skill_tools()
    mcp_tool_names = [tool.get("name", "") for tool in mcp_tools if tool.get("name")]
    hidden_skills = {"self-dev"}
    skill_entries = sorted(
        [
            f"{skill.name}: {skill.description}"
            for skill in SkillRegistry.list_all()
            if skill.name not in hidden_skills
        ],
    )

    return render_runtime_contract(
        cli_builtin_tools=cli_builtin_tools,
        mcp_tools=mcp_tool_names,
        available_skills=skill_entries,
        logger=logger,
    )


def _detect_user_language(text: str) -> str:
    """Detect the dominant user language for visible reasoning/response guidance."""
    counts = {"ja": 0, "zh": 0, "ko": 0}
    for ch in text:
        try:
            name = unicodedata.name(ch, "")
        except ValueError:
            continue
        if "HIRAGANA" in name or "KATAKANA" in name:
            counts["ja"] += 3
        elif "CJK" in name:
            counts["zh"] += 1
        elif "HANGUL" in name:
            counts["ko"] += 1
    if counts["ja"] > 0:
        return "Japanese"
    if counts["ko"] > 0:
        return "Korean"
    if counts["zh"] > 0:
        return "Chinese"
    return "English"


def _build_language_alignment_section(latest_user_message: str, user_messages: str = "") -> str:
    """Keep Claude's visible reasoning and answer in the user's language."""
    language = _detect_user_language(latest_user_message or user_messages or "")
    return (
        "## Language Rule (CRITICAL)\n\n"
        f"The user's language is **{language}**. "
        "ALL output — including intermediate reasoning between tool calls, "
        "thinking text, status updates, and the final response — "
        f"MUST be in {language}. Never use English for any visible output."
    )


def _build_system_prompt(
    title: str,
    description: str,
    status: str,
    user_messages: str = "",
    latest_user_message: str = "",
    room_id: str = "",
    user_id: str = "",
) -> str:
    """
    Build CLI system prompt.

    Base identity is minimal — domain-specific behavior is loaded via
    check_skill (e.g. project skill) at runtime.
    """
    from app.agent.bootstrap_context import (
        get_core_prompt, load_all_bootstrap_files, load_active_plan,
        load_artifact_descriptions,
    )

    parts = []

    parts.append(get_core_prompt())

    # Shared memory/rules context used across chat turns.
    bootstrap = load_all_bootstrap_files()
    if bootstrap:
        parts.append(bootstrap)

    # 保存済み個人情報のマスク一覧（実値は出さない）。
    # 「一度教われば二度と聞かない」を実現するため毎ターン注入する。値は固定的なので
    # プロンプトキャッシュが効き、レイテンシへの影響は無視できる。
    if user_id:
        try:
            from app.services.personal_info_service import build_personal_info_prompt_section
            pinfo_section = build_personal_info_prompt_section(user_id)
            if pinfo_section:
                parts.append(pinfo_section)
        except Exception:
            pass

    # Runtime contract: tool/skill visibility and behavior policy.
    parts.append(_build_runtime_contract_section())
    parts.append(_build_language_alignment_section(latest_user_message, user_messages))
    parts.append(
        "## Room State Rule\n\n"
        "- Treat `<room_state>` and `<conversation_so_far>` as DAN's authoritative "
        "DB-backed state for the current room.\n"
        "- Claude CLI transcripts are only a resumable cache. If they are missing, "
        "stale, reset, or contradictory, prefer the room-specific DB context.\n"
        "- For underspecified follow-ups such as continue/resume/where were we, "
        "infer the active task from the room DB context before asking the user. "
        "Do not fall back to global Claude history."
    )

    # Project context is appended only when project metadata exists.
    # NOTE: title is intentionally excluded to prevent the LLM from
    #       mistaking an auto-generated title for the current task
    #       after context compaction.
    if (description or "").strip():
        parts.append(_CLI_PROJECT_TEMPLATE.format(
            description=description,
            status=status,
        ))

    # Artifact descriptions — injected before plan for context.
    artifact_desc = load_artifact_descriptions(room_id=room_id)
    if artifact_desc:
        parts.append(artifact_desc)

    # Approved plan injection is experimental. Keep it switchable so we can
    # compare observer-backed memory against a lean Codex-like runtime.
    if _env_flag("DAN_PLAN_INJECTION_ENABLED", False):
        active_plan = load_active_plan(room_id=room_id)
        if active_plan:
            parts.append(active_plan)

    # Absolute rules — placed LAST for maximum attention.
    parts.append(
        "## Deliverable Placement Rules\n\n"
        "- Treat DAN itself and user deliverables as separate codebases, even when "
        "both live under this repository.\n"
        "- `frontend/src/app/artifacts/<slug>/` and `~/.dan/workspace/artifacts/<room>/` "
        "are user deliverables created by DAN; they are not DAN core.\n"
        "- Editing a user deliverable is not self-development. Do not use the `self-dev` "
        "skill for artifact websites, tools, landing pages, dashboards, or client work.\n"
        "- Use `self-dev` only when the user explicitly asks to change DAN itself: "
        "agent runtime, backend routes/services, DAN UI shell, hooks, deployment, "
        "skills, or infrastructure.\n"
        "- Production websites, dashboards, tools, and client-facing deliverables "
        "must be created under `frontend/src/app/artifacts/<slug>/`.\n"
        "- Do not create or edit deliverables under `frontend/src/app/demo/`. "
        "`/demo` has been removed; use `frontend/src/app/artifacts/<slug>/` for user-visible work.\n"
        "- When creating a deliverable, make sure it has a `page.tsx` entry so it can be "
        "registered as a chat artifact and opened from the chat header.\n"
        "- For navigation inside an artifact, do not import `next/link` directly for "
        "`/artifacts/<slug>` links. Import `ArtifactLink` from "
        "`@/components/artifacts/artifact-link` and alias it as `Link`, or use helpers "
        "from `@/lib/artifact-paths` when storing URLs. This preserves `/preview/<slug>` "
        "and custom-domain clean paths while the source stays under `/artifacts/<slug>`.\n"
        "- Client-facing artifact URLs are stable delivery aliases: "
        "`https://<slug>-done.vercel.app/`. Vercel deployment URLs such as "
        "`frontend-xxxxx.vercel.app` are internal build outputs and must not be given to "
        "the user as the share/delivery URL.\n"
        "- When fixing an existing artifact, update the existing artifact source and make "
        "sure its stable `*-done.vercel.app` alias points at the new deployment; do not "
        "solve delivery by handing out a new deployment URL. Prefer "
        "`python scripts/deploy_frontend_artifacts.py <slug>` after frontend artifact "
        "changes so the production deployment and alias update happen together.\n"
        "- Public artifacts must not inherit DAN's app identity. Add or preserve "
        "artifact-specific metadata and PWA manifest settings; the public manifest must "
        "not be `/manifest.json`, must not use `Done - AI Secretary`, and must not set "
        "`start_url` to `/chat`."
    )
    parts.append(_ABSOLUTE_RULES)
    parts.append(_BROWSER_AUTH_RULES)

    return "\n\n".join(parts)
_CLI_PROJECT_TEMPLATE = """## プロジェクト

- 説明: {description}
- ステータス: {status}

### 着手ルール
- 大きな変更を始める前に、方針を 1〜2 文でチャットに伝えてから手を動かす
- ユーザーが「OK」「やって」「それでいこう」等で承認するまで実装は着手しない
- 軽微な質問・調査・修正は事前承認不要、即実行
- 提案書 HTML や提案動画はユーザーが「提案書作って」「提案動画作って」と明示要求した時だけ作る (それ以外はチャット右ペインのライブプレビューで直接成果物を作って会話しながら詰める)"""

_ABSOLUTE_RULES = """## 絶対ルール
1. 質問にはまず回答。作業はその後。報告を求められたら報告だけして次の指示を待て。
2. 承認済み計画がある場合、逸脱しない。逸脱が必要なら理由を説明し承認を得る。
3. 同じアプローチで2回失敗したら、回避策を試すのではなく根本原因を特定しろ。自分のソースコード（D:/done配下）をRead/Edit/Bashで調査・修正できる。
4. browserツールで実現できない非対話操作（ダウンロード等）だけはBashでPythonスクリプトを書いて直接Playwrightを使え。対話操作・ログイン・認証には必ずbrowserツールを使え。直接Playwrightからbrowserツール用の共有プロファイル `~/.ai_secretary/browser_data` を開いてはいけない。補助スクリプトには別の一時プロファイルを使い、処理後に必ずブラウザを閉じろ。
5. 長期記憶が必要なら `read_file` で `~/.dan/workspace/MEMORY.md` を読め。
6. ターンが終わると次のユーザー発言まで二度と自分から発言できない。だから「完了したら報告します」「少々お待ちください」と言ってターンを終えると続報は永遠に届かない。完了をその場で待てるなら待って実結果を報告せよ。待てない長時間処理（デプロイ/ビルド/外部処理の完了待ち等）の時は、**必ず `schedule_followup(note, delay_seconds)` で続報を予約してから**終われ。予約せずに後で報告すると約束してはならない。
7. ユーザーが個人情報（電話番号・クレジットカード・住所・誕生日・メール等）を口にしたら、その場で即座に `remember_personal_info` で保存しろ。一度教われば二度と聞き返すな。システムプロンプトの「保存済み個人情報」一覧にある情報は既に保有済みなので、実値が要る操作の直前にだけ `get_personal_info` で取り出して使え。ログインID/パスワードは従来通り `save_credentials`。"""


_BROWSER_AUTH_RULES = """## Browser authentication handoff rules

- For interactive browser work that may require user input later, use the `browser` MCP tool. Do not launch a one-shot Playwright script from Bash.
- Start authenticated browser tasks with `browser(action="open_target", url="<actual destination>")`. Never open a login page first. Reuse the existing authenticated session when the destination opens successfully; log in only after the destination redirects to an unauthenticated page.
- When an OTP, SMS code, email code, passkey, or manual approval is required, preserve the current browser page and ask for the missing input. Do not close the browser, navigate away, or resend a code unless the current page has been checked and the code is expired or the user explicitly asks for a resend.
- When the user sends an OTP, inspect the still-open page first and enter it into the existing challenge. If the page is no longer usable, explain that before requesting a new code.
- For SMS OTP, prefer `browser(action="wait_for_otp_from_app", ref="...", press_enter=true)` so the Android app can forward and enter the OTP directly without exposing it in chat or tool output. If no OTP arrives within the timeout, keep the current page open and ask the user for the code.
- Never print, log, or persist OTP values beyond the immediate authentication step."""


def _get_encryption_key() -> str:
    """Settings（.env）からENCRYPTION_KEYを取得"""
    try:
        from app.config import Settings
        return Settings().ENCRYPTION_KEY or ""
    except Exception:
        return ""


def _build_mcp_config(room_id: str, user_id: str, credentials: Optional[Dict] = None) -> str:
    """MCP設定ファイルをセッション固有のパスに書き出して返す"""
    mcp_json = {
        "mcpServers": {
            "dan-tools": {
                "command": "python",
                "args": [str(PROJECT_ROOT / "app" / "mcp_server.py")],
                "env": {
                    "DAN_USER_ID": user_id,
                    "DAN_SESSION_ID": room_id,
                    "DAN_CREDENTIALS": json.dumps(credentials or {}),
                    "DAN_IS_PLANNING": "",
                    "ENCRYPTION_KEY": os.environ.get("ENCRYPTION_KEY", "") or _get_encryption_key(),
                },
            }
        }
    }
    mcp_config_dir = PROJECT_ROOT / ".claude"
    mcp_config_dir.mkdir(parents=True, exist_ok=True)
    # セッションごとに個別ファイル（並行実行時の上書き競合を防止）
    safe_name = room_id.replace("/", "_").replace("\\", "_")
    mcp_config_path = mcp_config_dir / f"mcp_{safe_name}.json"
    mcp_config_path.write_text(json.dumps(mcp_json, indent=2), encoding="utf-8")
    return str(mcp_config_path)


def _cleanup_mcp_config(room_id: str):
    """セッション終了後にMCP設定ファイルを削除する"""
    safe_name = room_id.replace("/", "_").replace("\\", "_")
    config_path = PROJECT_ROOT / ".claude" / f"mcp_{safe_name}.json"
    try:
        config_path.unlink(missing_ok=True)
    except Exception:
        pass


def _cli_debug(msg: str):
    """CLI thread用ファイルデバッグログ（日付+room_id自動付与）"""
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    room_id = getattr(_thread_local, "room_id", "")
    prefix = f"[{ts}]"
    if room_id:
        prefix = f"[{ts}] [{room_id[:8]}]"
    with open(PROJECT_ROOT / "cli_runner_debug.log", "a", encoding="utf-8") as f:
        f.write(f"{prefix} {msg}\n")
        f.flush()


def _classify_content_blocks(blocks: list) -> list[Dict[str, Any]]:
    """
    assistantメッセージのcontent blocksを分類する。

    Returns:
        list of events: {"type": "tool_use"|"reasoning"|"text", ...}
    """
    events = []

    for block in blocks:
        block_type = block.get("type", "")

        if block_type == "tool_use":
            events.append({
                "type": "tool_use",
                "id": block.get("id", ""),
                "name": block.get("name", ""),
                "input": block.get("input", {}),
            })
        elif block_type == "thinking":
            events.append({
                "type": "reasoning",
                "text": block.get("thinking", ""),
            })
        elif block_type == "text":
            text = block.get("text", "")
            if text.strip():
                # tool_useと同居していてもtextとして扱う
                # coordinatorがresultイベントを最優先するので、途中テキストが混じっても問題ない
                events.append({
                    "type": "text",
                    "text": text,
                })
        elif block_type == "server_tool_use":
            # web_search等のサーバー側ツール
            events.append({
                "type": "tool_use",
                "name": block.get("name", "server_tool"),
                "input": block.get("input", {}),
            })

    return events


def _resolve_claude_cli() -> tuple[Optional[str], Optional[str]]:
    """
    Claude CLI の実行パスを解決する。

    Windows では claude.CMD (バッチファイル) 経由だと引数内の日本語や
    特殊文字が壊れるため、node + cli.js を直接呼び出す。

    Returns:
        (executable, cli_js) - cli_js は .CMD 回避時のみ設定、それ以外は None
    """
    claude_path = shutil.which("claude")
    if not claude_path:
        return None, None

    # .CMD ファイルの場合: node + cli.js で直接実行
    if claude_path.lower().endswith(".cmd"):
        node_path = shutil.which("node")
        npm_dir = os.path.dirname(claude_path)
        cli_js = os.path.join(
            npm_dir, "node_modules", "@anthropic-ai", "claude-code", "cli.js"
        )
        if node_path and os.path.exists(cli_js):
            return node_path, cli_js
        # cli.js が見つからなければ .CMD をそのまま使う（フォールバック）
        return claude_path, None

    # .exe やその他: そのまま使う
    return claude_path, None


def run_oneshot_cli(
    prompt: str,
    model: str = "haiku",
    timeout: int = 60,
    cwd: Optional[str] = None,
) -> Optional[str]:
    """Claude CLI を1回だけ起動して短いテキストを生成する軽量ワンショット。

    タイトル/アイコン等の用途。Max 定額プランで動かすため ANTHROPIC_API_KEY を
    env から外して呼ぶ（従量課金を発生させない）。セッション・MCP・カスタム
    システムプロンプトは使わない純粋なテキスト生成。

    同期関数。async から呼ぶ場合は `await asyncio.to_thread(run_oneshot_cli, ...)`。

    Returns:
        生成テキスト（strip 済み）。CLI未検出・タイムアウト・異常終了時は None。
    """
    claude_cmd, cli_js = _resolve_claude_cli()
    if not claude_cmd:
        logger.warning("run_oneshot_cli: claude CLI が見つかりません")
        return None

    cmd = [claude_cmd, cli_js] if cli_js else [claude_cmd]
    cmd.extend([
        "-p", prompt,
        "--output-format", "text",
        "--model", model,
        "--dangerously-skip-permissions",
    ])

    # ANTHROPIC_API_KEY を外して Max 定額を強制 / CLAUDECODE で再帰起動防止
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "ANTHROPIC_API_KEY")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["NO_COLOR"] = "1"

    # CLAUDE.md / プロジェクトフック / MCP を巻き込まないよう空の中立 cwd で実行
    run_cwd = cwd or str(_ONESHOT_CWD)

    try:
        proc = subprocess.run(
            cmd,
            input="",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=run_cwd,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.warning("run_oneshot_cli: %ss でタイムアウト", timeout)
        return None
    except Exception as e:
        logger.warning("run_oneshot_cli: 起動失敗: %s", e)
        return None

    if proc.returncode != 0:
        logger.warning(
            "run_oneshot_cli: exit=%s stderr=%s",
            proc.returncode, (proc.stderr or "")[:300],
        )
        return None

    return (proc.stdout or "").strip() or None


def _build_cli_cmd(
    claude_cmd: str,
    cli_js: Optional[str],
    mcp_config_path: str,
    system_prompt: str,
    resume_session_id: Optional[str] = None,
    fork_session: bool = False,
) -> list[str]:
    """CLIコマンドライン引数を組み立てる"""
    if cli_js:
        cmd = [claude_cmd, cli_js]
    else:
        cmd = [claude_cmd]

    cmd.extend([
        "-p",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--dangerously-skip-permissions",
        "--model", "opus",
        "--max-turns", "200",
        "--mcp-config", mcp_config_path,
        "--append-system-prompt", system_prompt,
        # headless subprocess では interactive UI が無いので以下2つは機能しない
        # → モデルが呼ばないよう無効化。質問はテキストで、計画はメッセージ本文に書く運用に寄せる。
        "--disallowedTools", "ExitPlanMode,AskUserQuestion",
    ])

    if resume_session_id:
        cmd.extend(["--resume", resume_session_id])
        if fork_session:
            cmd.append("--fork-session")

    return cmd


_CLI_ARG_SYSTEM_PROMPT_LIMIT = 8000


def _prepare_cli_launch_payload(system_prompt: str, content: str) -> tuple[str, str]:
    """Avoid Windows CreateProcess argument length failures.

    Claude Code receives --append-system-prompt as a command-line argument.
    Large accumulated runtime context can exceed the Windows command line limit
    before the process starts. In that case, keep a short system prompt and move
    the full runtime context into stdin.
    """
    if len(system_prompt or "") <= _CLI_ARG_SYSTEM_PROMPT_LIMIT:
        return system_prompt, content

    short_prompt = (
        "Follow the runtime instructions included at the top of stdin. "
        "Treat <runtime_system_context> as system-level guidance, then handle "
        "the <user_request>."
    )
    expanded_content = (
        "<runtime_system_context>\n"
        f"{system_prompt}\n"
        "</runtime_system_context>\n\n"
        "<user_request>\n"
        f"{content}\n"
        "</user_request>"
    )
    return short_prompt, expanded_content


def _run_cli_process(
    cmd: list[str],
    content: str,
    env: dict,
    room_id: str,
    event_queue: thread_queue.Queue,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    cwd: Optional[str] = None,
) -> Optional[dict]:
    """
    CLIプロセスを1回実行し、イベントをキューに送る。

    Returns:
        result データ（リトライ判定用）。プロセスが結果を返さなかった場合は None。
    """
    session_id_captured = None
    final_text_parts = []
    result_data = None
    turn_id = turn_id or str(uuid.uuid4())
    reasoning_steps_acc = []  # DB-first: reasoning短縮ラベル蓄積
    reasoning_full_acc = []   # DB-first: reasoning全文蓄積
    # 時系列ブロック: text / tool を「起きた順」に保持し、AIメッセージの
    # ai_context.blocks として保存する。フロントはこれをインライン時系列で描画
    # （最後のテキストだけでなく途中のテキストも回答として表示する）。
    turn_blocks: list = []
    written_file_paths: list[str] = []

    # --include-partial-messages による重複を防ぐ
    # メッセージIDごとに「処理済みブロックのスナップショット」を記録
    # ブロック数だけでなく内容変更も検出するため、各ブロックのハッシュを保持する
    processed_block_snapshots: Dict[str, list] = {}
    # tool_use は ID 単位で一度だけ送信（partial でハッシュが揺れても重複しない）
    emitted_tool_use_ids: set = set()

    popen_start = time.perf_counter()
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd or str(CLI_WORKSPACE),
        env=env,
        encoding="utf-8",
        errors="replace",
        creationflags=_NO_WINDOW,
    )
    latency_message = (
        "[DAN_LATENCY] room=%s popen_started=%.3fs cmd_args=%s cwd=%s"
        % (
            room_id,
            time.perf_counter() - popen_start,
            len(cmd),
            cwd or CLI_WORKSPACE,
        )
    )
    logger.info(
        "%s",
        latency_message,
    )
    _latency_debug(latency_message)

    # プロセスを追跡dictに登録（旧プロセスがあればkill）
    with _process_lock:
        old_process = _active_processes.get(room_id)
        _active_processes[room_id] = process
    if old_process is not None:
        _cli_debug(f"Killing orphaned process PID={old_process.pid} before registering new PID={process.pid}")
        _terminate_process(old_process)

    _cli_debug(f"CLI process started: PID={process.pid}")

    try:
        process.stdin.write(content)
        process.stdin.close()
    except Exception as e:
        _cli_debug(f"stdin write error: {e}")

    # stderrドレインスレッド: stderrを継続的に読み捨ててバッファ満杯によるデッドロックを防ぐ
    # （stderrバッファが満杯になるとプロセスがwrite()でブロックし、stdoutも止まる）
    def _drain_stderr():
        try:
            for line in process.stderr:
                line = line.strip()
                if line:
                    _cli_debug(f"CLI stderr: {line[:200]}")
        except Exception:
            pass

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    # Watchdog: stdout に N 秒イベントが流れなければ hang とみなし強制終了する。
    # Bash の長時間コマンド (例: npm install / Whisper / ffmpeg encode) を許容するため
    # デフォルト 10 分。tool_result が来ない間 (= 実際に hang) に発火する。
    # 元は 5 分 (300s) だったが、Whisper CPU 推論などで 5 分超えが発生したため拡張 (2026-05-10)。
    #
    # 特例: Task (サブエージェント) 呼び出し中は別 Claude Code インスタンスが
    # 裏で 10〜20 分走りうる。その間 dan 本体は沈黙するので通常閾値だと誤発火する。
    # → Task in-flight 中は閾値を 30 分に延長。
    WATCHDOG_TIMEOUT_NORMAL = 600         # seconds (10 min)
    WATCHDOG_TIMEOUT_TASK_ACTIVE = 1800   # 30 min: Task サブエージェント実行中の特例
    _last_activity = [time.time()]
    _watchdog_fired = [False]
    _task_active = [False]  # Task tool が走ってる間 True

    def _current_timeout() -> int:
        return WATCHDOG_TIMEOUT_TASK_ACTIVE if _task_active[0] else WATCHDOG_TIMEOUT_NORMAL

    def _watchdog():
        while process.poll() is None:
            time.sleep(15)
            threshold = _current_timeout()
            elapsed = time.time() - _last_activity[0]
            if elapsed > threshold:
                _watchdog_fired[0] = True
                _cli_debug(
                    f"WATCHDOG: no stdout activity for {elapsed:.0f}s "
                    f"(threshold {threshold}s, task_active={_task_active[0]}), "
                    f"killing PID={process.pid}"
                )
                try:
                    event_queue.put({
                        "type": "error",
                        "message": (
                            f"dan が {threshold//60} 分応答停止したため強制終了しました。"
                            "外部コマンド (git push の credential 待ち等) でハングした可能性があります。"
                            "もう一度メッセージを送ってください。"
                        ),
                    })
                except Exception:
                    pass
                _terminate_process(process)
                return

    watchdog_thread = threading.Thread(target=_watchdog, daemon=True)
    watchdog_thread.start()

    for line in process.stdout:
        _last_activity[0] = time.time()
        line = line.strip()
        if not line:
            continue

        # RAW stdout ログは冗長なため通常無効
        # _cli_debug(f"RAW stdout: {line[:300]}")

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            _cli_debug(f"Non-JSON line: {line[:100]}")
            continue

        msg_type = data.get("type", "")

        if msg_type == "assistant":
            message_data = data.get("message", {})
            msg_id = message_data.get("id", "unknown")
            blocks = message_data.get("content", [])
            block_types = [b.get("type", "?") for b in blocks]
            _cli_debug(f"Assistant msg_id={msg_id} blocks: {block_types} (count={len(blocks)})")

            # partial messages では同じ msg_id で徐々にブロックが増える
            # 各ブロックのハッシュを比較して、新規または変更されたブロックだけ処理する
            def _block_hash(b: dict) -> str:
                """ブロックの内容を識別するハッシュ"""
                bt = b.get("type", "")
                if bt == "text":
                    return f"text:{b.get('text', '')}"
                elif bt == "thinking":
                    return f"thinking:{b.get('thinking', '')}"
                elif bt == "tool_use":
                    return f"tool_use:{b.get('id', '')}:{b.get('name', '')}"
                elif bt == "server_tool_use":
                    return f"server_tool_use:{b.get('name', '')}"
                return f"{bt}:{str(b)[:100]}"

            current_hashes = [_block_hash(b) for b in blocks]
            prev_hashes = processed_block_snapshots.get(msg_id, [])

            # 新規ブロック: インデックスがprev範囲外のもの
            # 変更ブロック: 同じインデックスだがハッシュが異なるもの
            new_blocks = []
            for i, block in enumerate(blocks):
                if i >= len(prev_hashes):
                    # 新規追加されたブロック
                    new_blocks.append(block)
                elif current_hashes[i] != prev_hashes[i]:
                    # 内容が変更されたブロック
                    new_blocks.append(block)

            processed_block_snapshots[msg_id] = current_hashes

            if not new_blocks:
                _cli_debug(f"  No new/changed blocks (prev={len(prev_hashes)}, now={len(blocks)})")
                continue

            _cli_debug(f"  Processing {len(new_blocks)} new/changed blocks (total={len(blocks)}, prev={len(prev_hashes)})")
            classified = _classify_content_blocks(new_blocks)

            for ev in classified:
                # tool_use は ID 単位で一度だけ送信
                if ev["type"] == "tool_use":
                    tool_id = ev.get("id", "")
                    if tool_id and tool_id in emitted_tool_use_ids:
                        continue
                    if tool_id:
                        emitted_tool_use_ids.add(tool_id)
                    try:
                        from app.services.chat_artifact_registration import (
                            add_written_path,
                            written_path_from_tool,
                        )
                        add_written_path(
                            written_file_paths,
                            written_path_from_tool(ev.get("name", ""), ev.get("input", {})),
                        )
                    except Exception as e:
                        _cli_debug(f"artifact path tracking failed: {e}")
                    # Task 系ツールが呼ばれている間は watchdog 閾値を延長
                    # Task 以外のツールに切り替わったらサブエージェント完了扱いでリセット
                    tool_name = ev.get("name", "")
                    task_tools = ("Task", "TaskCreate", "TaskOutput", "TaskGet", "TaskList", "TaskUpdate", "TaskStop")
                    if tool_name in task_tools:
                        _task_active[0] = True
                    else:
                        _task_active[0] = False
                _cli_debug(f"  Event: type={ev['type']}, name={ev.get('name', '')}, text_len={len(ev.get('text', ''))}")
                if ev["type"] == "text":
                    final_text_parts.append(ev["text"])
                    if ev.get("text", "").strip():
                        turn_blocks.append({"type": "text", "text": ev["text"]})
                event_queue.put(ev)

                # DB-first: CLIスレッドから直接DB保存（SSE断線対策）
                if project_id:
                    if ev["type"] == "tool_use":
                        from app.api.project_routes import _format_tool_label
                        tool_label = _format_tool_label(ev.get("name", ""), ev.get("input", {}))
                        _save_execution_event_sync(
                            room_id, "tool_use", project_id=project_id, run_id=run_id,
                            turn_id=turn_id,
                            tool_name=ev.get("name", ""),
                            tool_label=tool_label,
                        )
                        reasoning_steps_acc.append(f"🔧 {tool_label}")
                        turn_blocks.append({
                            "type": "tool",
                            "name": ev.get("name", ""),
                            "label": tool_label,
                            "detail": _tool_detail(ev.get("input", {})),
                        })
                    elif ev["type"] == "reasoning" and ev.get("text", "").strip():
                        # thinkingはプロセスモニターに送らない（英語で読みにくい）
                        # reasoning_full にだけ蓄積（デバッグ用に保持）
                        reasoning_full_acc.append(ev.get("text", ""))
                    elif ev["type"] == "text":
                        # テキスト出力（日本語の独り言）はプロセスモニターに表示
                        text_preview = ev.get("text", "").strip()
                        if text_preview and len(text_preview) > 10:
                            _save_execution_event_sync(
                                room_id, "reasoning", project_id=project_id, run_id=run_id,
                                turn_id=turn_id,
                                content=text_preview,
                            )
                            reasoning_steps_acc.append(text_preview)
                            reasoning_full_acc.append(text_preview)

        elif msg_type == "result":
            session_id_captured = data.get("session_id")
            cost_usd = data.get("cost_usd", 0)
            duration_ms = data.get("duration_ms", 0)
            num_turns = data.get("num_turns", 0)
            is_error = data.get("is_error", False)
            result_text = data.get("result", "")
            errors = data.get("errors", [])

            result_data = {
                "session_id": session_id_captured,
                "is_error": is_error,
                "num_turns": num_turns,
                "errors": errors,
                "result_text": result_text,
                "final_text_parts": final_text_parts,
                "cost": cost_usd,
                "duration_ms": duration_ms,
                "reasoning_steps": reasoning_steps_acc,
                "reasoning_full": reasoning_full_acc,
                "turn_blocks": turn_blocks,
                "written_file_paths": list(written_file_paths),
            }

            _cli_debug(
                f"ResultMessage: cost={cost_usd}, turns={num_turns}, "
                f"error={is_error}, text_len={len(result_text or '')}, "
                f"errors={errors}, result_text={result_text[:300] if result_text else '(empty)'}"
            )

        elif msg_type == "error":
            error_msg = data.get("error", {})
            error_text = error_msg.get("message", str(error_msg)) if isinstance(error_msg, dict) else str(error_msg)
            _cli_debug(f"CLI error event: {error_text[:200]}")
            event_queue.put({"type": "error", "message": error_text})

        elif msg_type == "system":
            session_id_captured = data.get("session_id", session_id_captured)
            # セッションIDを即座にDBへ保存（プロセス強制終了時にresultが来なくても--resumeできるように）
            if session_id_captured:
                _save_session(room_id, session_id_captured)
                _update_run_sync(run_id, claude_session_id=session_id_captured)
            _cli_debug(f"System message: session_id={session_id_captured}")

    # プロセスを追跡dictから削除（自分のプロセスだけ。新プロセスが既に登録されている場合は触らない）
    with _process_lock:
        if _active_processes.get(room_id) is process:
            _active_processes.pop(room_id, None)

    return_code = process.wait(timeout=30)
    _cli_debug(f"CLI process exited with code {return_code}")

    if return_code != 0 and result_data is None:
        # stderrはドレインスレッドが読んでいるので、ここではログのみ
        event_queue.put({"type": "error", "message": f"CLI exited with code {return_code}"})

    return result_data


def _should_retry_without_resume(result_data: Optional[dict], used_resume: bool) -> bool:
    """resumeを使った実行が失敗し、フレッシュセッションでリトライすべきかを判定する。

    セッションIDを消してリトライするのは「セッション自体が見つからない」場合のみ。
    ツールのフリーズやMCPクラッシュ（result_data=None, exit code 1）では
    セッションは無事なので消してはいけない。
    """
    if not used_resume:
        return False
    # result_dataがNone = CLIがresultを出さずに終了（ツールのハング等）
    # → セッション自体は正常な可能性が高い。消さない。
    if result_data is None:
        return False
    # エラーの場合: セッションが見つからないエラーだけリトライ
    if result_data.get("is_error", False):
        errors = result_data.get("errors", [])
        error_text = " ".join(str(e) for e in errors).lower()
        result_text = (result_data.get("result_text") or "").lower()
        combined = error_text + " " + result_text
        # 「セッションが見つからない」系のエラー → セッションクリアしてリトライ
        if "no conversation found" in combined or "session" in combined and "not found" in combined:
            return True
        # 「Prompt is too long」「Out of memory」→ 会話履歴が肥大化。セッションクリアしてリトライ
        if "prompt is too long" in combined or "out of memory" in combined:
            return True
        # thinking ブロック改変の 400 → resume 中の transcript が壊れている。
        # 同じ transcript を消さずに再 resume すると毎ターン同じ 400 で詰まるので、
        # セッションを捨ててフレッシュにリトライ（DB再シードで文脈は保持される）。
        if _is_thinking_desync_error(combined):
            return True
        # その他のエラー（ツール失敗、APIエラー等）→ セッションは消さない
        return False
    return False


def _run_cli_in_thread(
    content: str,
    system_prompt: str,
    mcp_config_path: str,
    room_id: str,
    event_queue: thread_queue.Queue,
    user_id: Optional[str] = None,
    resume_session_id: Optional[str] = None,
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
    cancel_event: Optional[threading.Event] = None,
    skip_save: bool = False,
    cwd: Optional[str] = None,
):
    """
    別スレッドでCLI subprocessを実行する。
    JSON streamを1行ずつ読み、イベントをキューに入れる。

    セッション再開が失敗した場合（セッションが見つからない等）、
    保存済みセッションIDをクリアして新規会話として自動リトライする。
    """
    _thread_local.room_id = room_id
    _cli_debug(f"Thread started for room {room_id}")
    turn_id = str(uuid.uuid4())

    claude_cmd, cli_js = _resolve_claude_cli()
    if not claude_cmd:
        event_queue.put({"type": "error", "message": "claude CLI が見つかりません。npm i -g @anthropic-ai/claude-code でインストールしてください。"})
        event_queue.put(_SENTINEL)
        return

    # CLAUDECODE: Claude Code の再帰起動を防止
    # ANTHROPIC_API_KEY: CLIがMax planサブスク（定額）ではなくAPI従量課金を使うのを防止
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "ANTHROPIC_API_KEY")}
    env["DAN_SESSION_ID"] = room_id
    env["DAN_ROOM_ID"] = room_id
    env["CLAUDE_CODE_ENABLE_TASKS"] = "true"
    if project_id:
        env["DAN_PROJECT_ID"] = project_id

    # Hang 防止: 子プロセス (git, npm, gcloud 等) が GUI/対話入力を要求すると subprocess は永久 hang する。
    # 全部「対話無効化」して即時失敗させる。
    env["GIT_TERMINAL_PROMPT"] = "0"            # git: credential GUI を出さない
    env["GIT_ASKPASS"] = "echo"                 # git: パスワード入力を空文字で即返す
    env["GCM_INTERACTIVE"] = "Never"            # git-credential-manager: GUI 完全抑止
    env["GH_PROMPT_DISABLED"] = "1"             # gh CLI: 確認 prompt を出さない
    env["NPM_CONFIG_YES"] = "true"              # npm: 確認を all-yes
    env["CI"] = "1"                             # 大半のツールが CI モードで非対話化される
    env["DEBIAN_FRONTEND"] = "noninteractive"   # apt 系 (WSL 経由など)
    env["NO_COLOR"] = "1"                       # 出力ノイズ削減 (パイプ詰まり緩和)

    # .env にしか定義されていない変数を settings から補完
    # （os.environ には入らないため、CLIやMCPサーバーに渡らず Supabase アクセスが失敗する）
    from app.config import settings
    for key, val in [
        ("SUPABASE_URL", settings.SUPABASE_URL),
        ("SUPABASE_KEY", settings.SUPABASE_KEY),
        ("SUPABASE_SERVICE_ROLE_KEY", settings.SUPABASE_SERVICE_ROLE_KEY),
    ]:
        if val and key not in env:
            env[key] = val

    result_data = None
    done_saved = False
    try:
        # 履歴肥大ガード: --resume するトランスクリプトが大きすぎると、最初のトークンまで
        # 数分かかる（巨大プロンプトの再prefill）。閾値を超えたらセッションを手放し、
        # DB の直近会話を要約して文脈を引き継いだ上で新規セッションとして開始する。
        # 会話本体は chat_messages に残るので文脈は失われない。
        if resume_session_id and _transcript_exceeds_limit(resume_session_id):
            _tx_path = _session_transcript_path(resume_session_id)
            try:
                _tx_size = _tx_path.stat().st_size if _tx_path else -1
            except Exception:
                _tx_size = -1
            _cli_debug(
                f"Transcript for session {resume_session_id} is {_tx_size} bytes "
                f"(>= {_TRANSCRIPT_RESET_BYTES}); dropping session and reseeding from DB"
            )
            _clear_cli_session(room_id)
            resume_session_id = None
            reseed = _build_reseed_context(room_id, project_id=project_id)
            if reseed:
                content = _wrap_latest_user_message(reseed, content)

        # 1回目: セッション再開を試みる（中断後はfork-sessionで新規セッション分岐）
        need_fork = room_id in _interrupted_rooms
        if need_fork:
            _interrupted_rooms.discard(room_id)
        launch_system_prompt, launch_content = _prepare_cli_launch_payload(system_prompt, content)
        cmd = _build_cli_cmd(claude_cmd, cli_js, mcp_config_path, launch_system_prompt, resume_session_id, fork_session=need_fork)
        _cli_debug(f"CLI attempt 1 (resume={resume_session_id is not None}, fork={need_fork}, prompt len={len(content)})")

        result_data = _run_cli_process(
            cmd,
            launch_content,
            env,
            room_id,
            event_queue,
            user_id=user_id,
            project_id=project_id,
            run_id=run_id,
            turn_id=turn_id,
            cwd=cwd,
        )

        # セッション再開失敗 → セッションをクリアしてリトライ
        if _should_retry_without_resume(result_data, used_resume=resume_session_id is not None):
            errors = result_data.get("errors", []) if result_data else []
            _cli_debug(f"Resume failed (result_data={'None' if result_data is None else 'error'}): {errors}. Clearing session and retrying without resume.")

            # 古いセッションIDをクリア
            _cli_sessions.pop(room_id, None)
            try:
                from app.services.supabase_client import get_supabase_client
                sb = get_supabase_client().client
                sb.table("cli_sessions").delete().eq("room_id", room_id).execute()
            except Exception as e:
                _cli_debug(f"Failed to clear session from DB: {e}")

            # 2回目: 新規会話として実行
            retry_content = content
            if "<conversation_so_far>" not in retry_content:
                reseed = _build_reseed_context(room_id, project_id=project_id)
                if reseed:
                    retry_content = _wrap_latest_user_message(reseed, content)
            retry_system_prompt, retry_launch_content = _prepare_cli_launch_payload(system_prompt, retry_content)
            cmd = _build_cli_cmd(claude_cmd, cli_js, mcp_config_path, retry_system_prompt, resume_session_id=None)
            _cli_debug(f"CLI attempt 2 (fresh session, prompt len={len(retry_content)})")

            result_data = _run_cli_process(
                cmd,
                retry_launch_content,
                env,
                room_id,
                event_queue,
                user_id=user_id,
                project_id=project_id,
                cwd=cwd,
                run_id=run_id,
                turn_id=turn_id,
            )

        # 最終結果をキューに送る
        if result_data:
            session_id = result_data.get("session_id")
            is_error = result_data.get("is_error", False)
            result_text = result_data.get("result_text", "")
            final_text_parts = result_data.get("final_text_parts", [])
            errors = result_data.get("errors", [])

            # 成功時のみセッションIDを保存
            if session_id and not is_error:
                _save_session(room_id, session_id)
                _update_run_sync(run_id, claude_session_id=session_id)

            # エラー時はerrorsの内容をテキストに含める
            text = result_text or "\n".join(final_text_parts)
            # parse-error poison / thinking-desync: replace the CLI's cryptic
            # English with a localized recovery notice AND drop the poisoned
            # session so the NEXT turn starts fresh (reseeded from the DB),
            # mirroring the streaming path. Without the clear, --resume would
            # replay the contaminated transcript and loop on the same error.
            if is_error and _is_parse_error_text(result_text):
                text = _recovery_message("parse_error", _detect_user_lang(content))
                _clear_cli_session(room_id)
            elif is_error and _is_thinking_desync_error(result_text):
                text = _recovery_message("thinking_desync", _detect_user_lang(content))
                _clear_cli_session(room_id)
            if is_error and not text and errors:
                text = f"CLIエラー: {'; '.join(errors)}"

            # CLIが思考ブロックのみで終わった場合(text空)もフォールバックを必ず保存する。
            # ここでスキップするとSSEハンドラ側のフォールバック保存パスに依存することになり、
            # ちょうどSupabaseがdisconnectedのときにメッセージが完全に失われ、
            # ユーザーは「終わった？」と催促するまで応答を受け取れなくなる。
            if not text.strip():
                text = "（内部思考のみで応答テキストが生成されませんでした。もう一度お試しください。）"

            # DB-first: CLIスレッドからAI応答を保存（SSE断線対策）
            # SSEハンドラに依存せず、ここで確実にDBに書き込む
            cli_saved = False
            if not skip_save:
                reasoning = result_data.get("reasoning_steps", [])
                reasoning_full_list = result_data.get("reasoning_full", [])
                blocks = result_data.get("turn_blocks", [])
                cli_saved = _save_ai_message_sync(
                    room_id, text, reasoning, reasoning_full_list, blocks=blocks, turn_id=turn_id
                )
                _cli_debug(f"AI message DB save: cli_saved={cli_saved}, text_len={len(text)}")

            written_paths = result_data.get("written_file_paths", [])
            if user_id and project_id and written_paths:
                try:
                    from app.services.chat_artifact_registration import (
                        register_written_chat_artifacts_sync,
                    )

                    created = register_written_chat_artifacts_sync(
                        written_paths,
                        room_id,
                        project_id,
                        user_id,
                    )
                    if created:
                        _cli_debug(
                            "Registered chat artifacts from CLI thread: "
                            + ",".join(row.get("slug", "?") for row in created)
                        )
                except Exception as e:
                    _cli_debug(f"CLI artifact registration failed: {e}")

            # Queue-first: フロントエンドを即座にアンブロックする。
            # cli_saved=True の場合、SSEハンドラはDB保存をスキップしてクライアント送信のみ行う。
            event_queue.put({
                "type": "result",
                "text": text,
                "session_id": session_id,
                "cost": result_data.get("cost", 0),
                "turns": result_data.get("num_turns", 0),
                "duration_ms": result_data.get("duration_ms", 0),
                "is_error": is_error,
                "cli_saved": cli_saved,
                "turn_id": turn_id,
            })
            if project_id:
                _save_execution_event_sync(
                    room_id,
                    "done",
                    project_id=project_id,
                    run_id=run_id,
                    turn_id=turn_id,
                    content="completed",
                )
            _update_run_sync(run_id, state="failed" if is_error else "completed")

    except Exception as e:
        import traceback
        from app.services.cancellation import CancellationRegistry
        error_detail = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        _cli_debug(f"ERROR: {error_detail}")
        event_queue.put({"type": "error", "message": error_detail})
        done_saved = True  # finallyで二重保存しないためのフラグ
        if project_id:
            _save_ai_message_sync(
                room_id,
                f"処理中にエラーが発生しました。もう一度お試しください。\n（{type(e).__name__}）",
                turn_id=turn_id,
            )
            _save_execution_event_sync(
                room_id,
                "done",
                project_id=project_id,
                run_id=run_id,
                turn_id=turn_id,
                content="error",
            )
        _update_run_sync(
            run_id,
            state="paused" if CancellationRegistry.is_cancelled(room_id) else "failed",
        )
    finally:
        # セーフティネット: 正常パス(result_data)もexceptパス(done_saved)も通らなかった場合
        # = CLIがresultを出す前に静かに終了した場合
        if project_id and not result_data and not done_saved:
            from app.services.cancellation import CancellationRegistry
            was_cancelled = CancellationRegistry.is_cancelled(room_id)
            _cli_debug(f"Safety net: CLI exited without result (cancelled={was_cancelled})")
            # キャンセル時はSSE側(chat_routes.py)が「（中断されました）」を保存するので重複しない
            if not was_cancelled:
                _save_ai_message_sync(
                    room_id,
                    "処理が中断されました。もう一度お試しください。",
                    turn_id=turn_id,
                )
            done_content = "cancelled" if was_cancelled else "interrupted"
            _save_execution_event_sync(
                room_id,
                "done",
                project_id=project_id,
                run_id=run_id,
                turn_id=turn_id,
                content=done_content,
            )
            _update_run_sync(
                run_id,
                state="paused" if was_cancelled else "failed",
            )
        _cleanup_mcp_config(room_id)
        # コンパクションサマリーをdaily memoryにミラーリング
        try:
            from app.services.compaction_sync import sync_compaction_summaries
            synced = sync_compaction_summaries()
            if synced:
                _cli_debug(f"Compaction sync: mirrored {synced} summary(ies)")
        except Exception as e:
            _cli_debug(f"Compaction sync error (non-fatal): {e}")
        _cli_debug("Sending sentinel")
        event_queue.put(_SENTINEL)
        # CLIスレッド終了時にCancellationRegistryを確実に解除
        # cancel_eventが渡されている場合は自分のEventだけ解除（新スレッドのEventを消さない）
        try:
            from app.services.cancellation import CancellationRegistry
            if cancel_event is not None:
                CancellationRegistry.unregister_if_match(room_id, cancel_event)
            else:
                CancellationRegistry.unregister(room_id)
        except Exception:
            pass


async def _process_via_streaming_session(
    room_id: str,
    user_id: str,
    content: str,
    system_prompt: str,
    mcp_config_path: str,
    project_id: Optional[str],
    run_id: Optional[str],
    skip_save: bool,
    cwd: Optional[str],
    resume_session_id: Optional[str] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """DAN_STREAMING_INPUT path (flag-gated). Runs the turn through a
    persistent stream-json session so follow-ups can be injected at the next
    step boundary. Reuses the SAME classify/save helpers as the one-shot path;
    the one-shot path itself is untouched.

    When `resume_session_id` is set, a freshly (re)started session resumes that
    saved Claude conversation with `--resume`, so dan-core restarts (and the
    idle-hang teardown) no longer wipe the room's context. The streaming path
    keeps no other history, so this is what makes it survive a restart the way
    the one-shot path always has.
    """
    from app.agent.streaming_session import get_or_create_session

    claude_cmd, cli_js = _resolve_claude_cli()
    if not claude_cmd:
        yield {"type": "error", "message": "claude CLI が見つかりません"}
        return

    def build_cmd() -> list:
        c = [claude_cmd, cli_js] if cli_js else [claude_cmd]
        c += [
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
            "--model", "opus",
            "--max-turns", "200",
            "--mcp-config", mcp_config_path,
            "--append-system-prompt", system_prompt,
            "--disallowedTools", "ExitPlanMode,AskUserQuestion",
        ]
        # Resume the saved conversation so context survives a process restart.
        # Only applied at session creation (a live session is reused as-is).
        if resume_session_id:
            c += ["--resume", resume_session_id]
        return c

    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "ANTHROPIC_API_KEY")}
    env["NO_COLOR"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    run_cwd = cwd or str(CLI_WORKSPACE)

    from app.agent.streaming_session import get_session
    existing = get_session(room_id)
    session_is_fresh = existing is None or not existing.is_alive()
    session = get_or_create_session(room_id, build_cmd, env, run_cwd)

    # Context-preserving reseed: when we start a BRAND-NEW session with no
    # transcript to --resume (e.g. right after a poisoned session was cleared),
    # rebuild the room's context from the DB instead of resuming a possibly
    # contaminated transcript. The conversation lives in chat_messages, so a
    # reset drops only the CLI session — not the context — and the user never
    # has to re-explain. Contaminated lines (leaked <invoke> text / parse-error
    # results) are filtered out so the reseed can't re-poison the new session.
    send_content = content
    if session_is_fresh and not resume_session_id and "<conversation_so_far>" not in send_content:
        reseed = _build_reseed_context(room_id, project_id=project_id)
        if reseed:
            send_content = _wrap_latest_user_message(reseed, content)

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    _SENTINEL: Dict[str, Any] = {"__turn_done__": True}

    # Per-turn accumulators live in the SINK's thread context. They reset on each
    # `result` so a follow-up turn saves its own ai_message/blocks independently.
    state: Dict[str, Any] = {
        "turn_blocks": [],
        "final_text_parts": [],
        "reasoning_steps_acc": [],
        "reasoning_full_acc": [],
        "written_file_paths": [],
        "session_id": None,
        "turn_id": None,
        # ターン開始時刻（最初の assistant イベント時）。保存する ai_message の
        # created_at に使い、追い連絡で割り込まれたターンの回答が時系列で正しく並ぶ
        # ようにする（保存=ターン終了時刻だと追い連絡より後ろにずれる）。
        "turn_start": None,
        # True once any `result` was seen this call. Used to tell a normal turn
        # apart from a session that died on start (e.g. a stale --resume id).
        "any_result": False,
    }

    def _emit(display_ev: Dict[str, Any]) -> None:
        # Best-effort forward to the SSE generator. Safe even if the consumer
        # (the SSE request) is already gone — saving does NOT depend on this.
        try:
            loop.call_soon_threadsafe(q.put_nowait, display_ev)
        except Exception:
            pass

    def _register_streaming_artifacts() -> None:
        written_paths = state.get("written_file_paths") or []
        if not (user_id and project_id and written_paths):
            return
        try:
            from app.services.chat_artifact_registration import (
                register_written_chat_artifacts_sync,
            )

            created = register_written_chat_artifacts_sync(
                written_paths,
                room_id,
                project_id,
                user_id,
            )
            if created:
                _cli_debug(
                    "[STREAMING] Registered chat artifacts: "
                    + ",".join(row.get("slug", "?") for row in created)
                )
        except Exception as e:
            _cli_debug(f"[STREAMING] artifact registration failed: {e}")

    def sink(raw_ev: Dict[str, Any]) -> None:
        # Runs in the session reader thread. Does classification + DB-first
        # persistence (execution_events / ai_message / done) here, INDEPENDENT of
        # SSE liveness — matching the one-shot path's _run_cli_in_thread. If the
        # phone backgrounds and the SSE drops mid-turn, Dan keeps working and the
        # result is still saved. Display events are forwarded best-effort.
        try:
            rtype = raw_ev.get("type")
            if rtype == "assistant":
                if state["turn_start"] is None:
                    # 最初の assistant イベント = このターンの開始（ユーザー/追い連絡
                    # メッセージより確実に後の時刻になる）。
                    state["turn_start"] = datetime.now(timezone.utc).isoformat()
                    state["turn_id"] = str(uuid.uuid4())
                blocks = (raw_ev.get("message") or {}).get("content") or []
                for ev in _classify_content_blocks(blocks):
                    if ev["type"] == "text":
                        txt = ev.get("text", "")
                        if txt.strip():
                            state["final_text_parts"].append(txt)
                            state["turn_blocks"].append({"type": "text", "text": txt})
                        _emit(ev)
                        # Save EVERY non-empty intermediate text as a reasoning
                        # event (no length filter), so the live block interleaves
                        # text+tool exactly like the saved message's blocks → the
                        # live view renders per-step (text → 「1件の作業 を表示」),
                        # not all tools lumped into one collapsed monitor.
                        if project_id and txt.strip():
                            _save_execution_event_sync(room_id, "reasoning", project_id=project_id, run_id=run_id, turn_id=state["turn_id"], content=txt.strip())
                            state["reasoning_steps_acc"].append(txt.strip())
                            state["reasoning_full_acc"].append(txt.strip())
                    elif ev["type"] == "tool_use":
                        from app.api.project_routes import _format_tool_label
                        tool_label = _format_tool_label(ev.get("name", ""), ev.get("input", {}))
                        try:
                            from app.services.chat_artifact_registration import (
                                add_written_path,
                                written_path_from_tool,
                            )
                            add_written_path(
                                state["written_file_paths"],
                                written_path_from_tool(ev.get("name", ""), ev.get("input", {})),
                            )
                        except Exception as e:
                            _cli_debug(f"[STREAMING] artifact path tracking failed: {e}")
                        _emit(ev)
                        if project_id:
                            _save_execution_event_sync(room_id, "tool_use", project_id=project_id, run_id=run_id, turn_id=state["turn_id"], tool_name=ev.get("name", ""), tool_label=tool_label)
                            state["reasoning_steps_acc"].append(f"🔧 {tool_label}")
                            state["turn_blocks"].append({"type": "tool", "name": ev.get("name", ""), "label": tool_label, "detail": _tool_detail(ev.get("input", {}))})
                    elif ev["type"] == "reasoning":
                        _emit(ev)
                        if ev.get("text", "").strip():
                            state["reasoning_full_acc"].append(ev["text"])

            elif rtype == "system":
                sid = raw_ev.get("session_id")
                if sid:
                    state["session_id"] = sid
                    _save_session(room_id, sid)
                    _update_run_sync(run_id, claude_session_id=sid)

            elif rtype == "result":
                state["any_result"] = True
                result_text = raw_ev.get("result", "") or ""
                is_error = bool(raw_ev.get("is_error"))
                # このターンが追い連絡の割り込み（interrupt）で終了したか = 後続ターンあり。
                # _interrupt_sent はこの sink と同じリーダースレッドで同期的にセットされる
                # ので result 到達時点で信頼できる。継続中は done を出さずライブ表示を維持。
                continuation = bool(getattr(session, "_interrupt_sent", False))
                text = result_text or "\n".join(state["final_text_parts"])
                if not text.strip():
                    text = "（応答テキストが空でした。もう一度お試しください。）"
                # Replace the CLI's cryptic parse-error result with a friendly
                # note. The session is dropped + reseeded afterwards (see run()),
                # so the user can just resend and continue with full context.
                if is_error and _is_parse_error_text(result_text):
                    text = _recovery_message("parse_error", _detect_user_lang(content))
                elif is_error and _is_thinking_desync_error(result_text):
                    text = _recovery_message("thinking_desync", _detect_user_lang(content))
                turn_start = state["turn_start"] or datetime.now(timezone.utc).isoformat()
                turn_id = state["turn_id"] or str(uuid.uuid4())
                cli_saved = False
                if not skip_save:
                    cli_saved = _save_ai_message_sync(room_id, text, state["reasoning_steps_acc"], state["reasoning_full_acc"], blocks=state["turn_blocks"], created_at=turn_start, turn_id=turn_id)
                _register_streaming_artifacts()
                if project_id and not continuation:
                    _save_execution_event_sync(room_id, "done", project_id=project_id, run_id=run_id, turn_id=turn_id, content="completed")
                    _update_run_sync(run_id, state="failed" if is_error else "completed")
                _emit({"type": "result", "text": text, "session_id": state["session_id"], "is_error": is_error, "cli_saved": cli_saved, "created_at": turn_start, "continuation": continuation, "turn_id": turn_id})
                # Reset per-turn accumulators for any follow-up turn.
                state["turn_blocks"] = []
                state["final_text_parts"] = []
                state["reasoning_steps_acc"] = []
                state["reasoning_full_acc"] = []
                state["written_file_paths"] = []
                state["turn_start"] = None
                state["turn_id"] = None

            elif rtype == "error":
                _emit({"type": "error", "message": raw_ev.get("message") or "error"})
        except Exception as e:  # noqa: BLE001
            _cli_debug(f"[STREAMING] sink error: {e}")

    def run() -> None:
        t0 = time.time()
        try:
            res = session.run_turn(send_content, sink, timeout=_STREAMING_IDLE_TIMEOUT)
            elapsed = time.time() - t0
            # Idle hang: the turn produced no `result`, so the sink never saved
            # or emitted one. Instead of silently closing the SSE on silence
            # (which is what made long tasks "lose" their reply), persist what
            # streamed so far and tell the user it was cut at a quiet point. The
            # session was already torn down inside run_turn; also forget the
            # saved session id so the next turn starts a FRESH conversation
            # rather than --resume-ing a half-finished (desynced) transcript.
            if getattr(session, "last_turn_hung", False):
                _clear_cli_session(room_id)
                partial = "\n".join(state["final_text_parts"]).strip()
                note = _recovery_message("idle_hang", _detect_user_lang(content))
                text = (partial + "\n\n" + note) if partial else note
                t_start = state["turn_start"] or datetime.now(timezone.utc).isoformat()
                t_id = state["turn_id"] or str(uuid.uuid4())
                if not skip_save:
                    _save_ai_message_sync(
                        room_id, text, state["reasoning_steps_acc"], state["reasoning_full_acc"],
                        blocks=state["turn_blocks"], created_at=t_start, turn_id=t_id,
                    )
                _register_streaming_artifacts()
                if project_id:
                    _save_execution_event_sync(
                        room_id, "done", project_id=project_id, run_id=run_id,
                        turn_id=t_id, content="timeout",
                    )
                    _update_run_sync(run_id, state="failed")
                _emit({
                    "type": "result", "text": text, "session_id": state["session_id"],
                    "is_error": True, "cli_saved": not skip_save, "created_at": t_start,
                    "continuation": False, "turn_id": t_id,
                })
                state["written_file_paths"] = []
            elif res and res.get("is_error") and _is_parse_error_text(res.get("result") or ""):
                # Poisoned turn: the model emitted an unparseable tool call (the
                # `<invoke>`-as-text leak). The sink already saved a result, so
                # we don't save again — we just drop the session + saved id so
                # the NEXT turn starts FRESH and gets re-seeded from the DB
                # (context preserved) instead of resuming the contaminated
                # transcript and looping on the same parse error every turn.
                _clear_cli_session(room_id)
                try:
                    session.stop()
                except Exception:
                    pass
                _cli_debug(f"[STREAMING] parse-error poisoned session cleared for room {room_id[:8]}")
            elif res and res.get("is_error") and _is_thinking_desync_error(res.get("result") or ""):
                # The resumed transcript had a split/desynced thinking turn, so
                # Anthropic rejected the replay with the "thinking blocks cannot
                # be modified" 400. The sink already saved a friendly result; we
                # just drop the session + saved id so the NEXT turn starts FRESH
                # and is re-seeded from the DB (context preserved) instead of
                # resuming the broken transcript and looping on the same 400.
                _clear_cli_session(room_id)
                try:
                    session.stop()
                except Exception:
                    pass
                _cli_debug(f"[STREAMING] thinking-desync session cleared for room {room_id[:8]}")
            elif resume_session_id and not state["any_result"] and elapsed < 15:
                # We asked the process to --resume <id> and it produced nothing
                # and exited almost immediately → the saved transcript was
                # probably stale/gone ("No conversation found"). Forget it and
                # ask the user to resend; the next turn starts fresh and works,
                # instead of failing on every retry.
                _clear_cli_session(room_id)
                try:
                    session.stop()
                except Exception:
                    pass
                text = (
                    "前回の会話の復元に失敗したため、セッションを作り直しました。"
                    "お手数ですが、もう一度同じ内容を送ってください。"
                )
                if not skip_save:
                    _save_ai_message_sync(room_id, text, turn_id=str(uuid.uuid4()))
                _emit({
                    "type": "result", "text": text, "session_id": None,
                    "is_error": True, "cli_saved": not skip_save, "continuation": False,
                })
        except Exception as e:  # noqa: BLE001
            _emit({"type": "error", "message": str(e)})
        finally:
            _emit(_SENTINEL)

    threading.Thread(target=run, daemon=True).start()

    # The generator is now a thin display forwarder. If the SSE consumer goes
    # away, the sink (in the reader thread) keeps classifying + saving, so DB
    # persistence is decoupled from SSE liveness. A keepalive is emitted during
    # silent stretches so the SSE connection (and the live view) survive a
    # long-but-quiet step instead of going dark.
    while True:
        try:
            raw = await asyncio.wait_for(q.get(), timeout=_STREAMING_KEEPALIVE_SECONDS)
        except asyncio.TimeoutError:
            yield {"type": "keepalive"}
            continue
        if raw is _SENTINEL:
            break
        yield raw


async def process_message_cli(
    room_id: str,
    user_id: str,
    content: str,
    project_title: str = "",
    project_description: str = "",
    project_status: str = "in_progress",
    credentials: Optional[Dict] = None,
    system_prompt: Optional[str] = None,
    user_messages: str = "",
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
    skill_injection: Optional[str] = None,
    skip_save: bool = False,
    skip_resume: bool = False,
    cwd: Optional[str] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """
    Claude CLI経由でメッセージを処理し、分類済みイベントを返す。

    イベントタイプ:
    - "text": ユーザー向けメッセージ（チャットに表示）
    - "tool_use": ツール実行（execution_eventsに記録）
    - "reasoning": 内部思考（execution_eventsに記録）
    - "result": 最終結果
    - "error": エラー

    CLIは別スレッドで実行（Windows の SelectorEventLoop 制約を回避）。
    イベントはスレッドセーフなキュー経由で受け取る。

    Args:
        system_prompt: カスタムシステムプロンプト。指定時は _build_system_prompt() をスキップ。
        user_messages: ユーザーの依頼文原文（planning プロンプト用）。
    """
    setup_start = time.perf_counter()
    if system_prompt is None:
        system_prompt = _build_system_prompt(
            project_title, project_description, project_status,
            user_messages=user_messages,
            latest_user_message=content,
            room_id=room_id,
            user_id=user_id,
        )
    if skill_injection:
        system_prompt += f"\n\n{skill_injection}"
    mcp_config_path = _build_mcp_config(room_id, user_id, credentials)
    resume_session_id = None if skip_resume else _load_session(room_id)

    # Dead-transcript guard: if the saved session's transcript .jsonl is gone
    # (manually cleaned, disk loss, a renamed/corrupt file …), `--resume <id>`
    # does NOT error — the CLI silently starts a FRESH, context-less
    # conversation, so the room loses its history and Dan answers from global
    # memory only. Detect the missing transcript here and drop the dead id so
    # the reseed-from-DB path (session_is_fresh and not resume_session_id) fires
    # instead. _clear_cli_session also evicts the stale in-memory cache entry.
    if resume_session_id and _session_transcript_path(resume_session_id) is None:
        _cli_debug(
            f"resume transcript missing for {resume_session_id[:8]}; "
            f"dropping session and reseeding from DB for room {room_id[:8]}"
        )
        _clear_cli_session(room_id)
        resume_session_id = None

    content_for_cli = content
    if room_id and not skip_save:
        try:
            if _is_underspecified_continuation(content) or (resume_session_id is None and not skip_resume):
                context = _build_reseed_context(
                    room_id,
                    project_id=project_id,
                    max_chars=int(os.getenv("DAN_RECOVERY_CONTEXT_MAX_CHARS", "12000")),
                )
            else:
                context = _build_room_state_context(
                    room_id,
                    project_id=project_id,
                    max_chars=int(os.getenv("DAN_ROOM_STATE_MAX_CHARS", "2500")),
                )
            if context:
                content_for_cli = _wrap_latest_user_message(context, content)
        except Exception as e:
            _cli_debug(f"Failed to build DB room context for {room_id[:8]}: {e}")

    # --- DAN_STREAMING_INPUT: 常駐ストリーミングセッション経路（フラグ制御） ---
    # 有効時のみ、ターンを常駐 stream-json セッションに流す（後段で「次の境界」
    # への追い連絡注入を可能にするため）。フラグOFF時は下の1ターン1プロセス経路を
    # そのまま使用する（=従来挙動と完全一致、無改変）。
    try:
        from app.agent.streaming_session import streaming_enabled
        _use_streaming = streaming_enabled()
    except Exception:
        _use_streaming = False
    if _use_streaming:
        _cli_debug(f"[STREAMING] routing room={room_id} via persistent session")
        from app.services.artifact_url_guard import sanitize_artifact_public_urls
        async for ev in _process_via_streaming_session(
            room_id, user_id, content_for_cli, system_prompt, mcp_config_path,
            project_id, run_id, skip_save, cwd,
            resume_session_id=resume_session_id,
        ):
            if isinstance(ev, dict) and ev.get("type") in {"text", "result"}:
                key = "text" if "text" in ev else "content"
                if isinstance(ev.get(key), str):
                    ev = {**ev, key: sanitize_artifact_public_urls(ev[key])}
            yield ev
        return

    latency_message = (
        "[DAN_LATENCY] room=%s cli_setup=%.3fs system_prompt_chars=%s content_chars=%s resume=%s"
        % (
            room_id,
            time.perf_counter() - setup_start,
            len(system_prompt),
            len(content_for_cli),
            bool(resume_session_id),
        )
    )
    logger.info("%s", latency_message)
    _latency_debug(latency_message)

    # cancel_eventの参照を取得（旧スレッドが新スレッドのEventを消さないようにする）
    from app.services.cancellation import CancellationRegistry
    cancel_event = CancellationRegistry.get_event(room_id)

    # CLI を別スレッドで実行
    event_q = thread_queue.Queue()
    cli_thread = threading.Thread(
        target=_run_cli_in_thread,
        args=(
            content_for_cli,
            system_prompt,
            mcp_config_path,
            room_id,
            event_q,
            user_id,
            resume_session_id,
            project_id,
            run_id,
            cancel_event,
            skip_save,
            cwd,
        ),
        daemon=True,
    )
    cli_thread.start()

    # キューからイベントを非同期に読み出してyield
    # タイムアウトを2秒に短縮してキャンセル検出の応答性を向上
    from app.services.cancellation import CancellationRegistry
    loop = asyncio.get_running_loop()
    idle_seconds = 0
    while True:
        # キャンセル検出
        if CancellationRegistry.is_cancelled(room_id):
            kill_cli_process(room_id)
            yield {"type": "cancelled"}
            break

        try:
            event = await loop.run_in_executor(
                None, lambda: event_q.get(timeout=2)
            )
        except Exception:
            # queue.Empty (timeout)
            idle_seconds += 2
            if not cli_thread.is_alive():
                _cli_debug(f"CLI thread died unexpectedly after {idle_seconds}s idle")
                yield {"type": "error", "message": "CLI process terminated unexpectedly"}
                break
            if idle_seconds >= 3600:  # 60 minute safety net
                _cli_debug(f"CLI timeout after {idle_seconds}s")
                yield {"type": "error", "message": f"CLI timeout after {idle_seconds}s"}
                break
            # SSE接続を維持するためキープアライブを送出
            yield {"type": "keepalive"}
            continue

        idle_seconds = 0
        if event is _SENTINEL:
            break
        if isinstance(event, dict):
            from app.services.artifact_url_guard import sanitize_artifact_public_urls
            if event.get("type") in {"text", "result"}:
                key = "text" if "text" in event else "content"
                if isinstance(event.get(key), str):
                    event = {**event, key: sanitize_artifact_public_urls(event[key])}
        yield event
