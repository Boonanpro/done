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
from typing import AsyncIterator, List, Optional, Dict, Any

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


def kill_cli_process(room_id: str, allow_arm_pending: bool = True) -> bool:
    """ユーザーのキャンセル要求を実行中ターンへ届ける。

    常駐ストリーミングセッションのターンには interrupt（Escキー相当の丁寧な
    中断）を送る。従来はこの関数が one-shot 経路のプロセス表しか見ておらず、
    常駐経路のターンには何も起きなかった（キャンセルボタンが実質無効・
    「キャンセルしたのに走り出す」の正体）。プロセス kill はしない——途中で
    殺すとストリームが同期ズレし `<invoke>` テキストリークが再発する。

    allow_arm_pending: ターンがまだ始まっていない時に「直後に始まるターンを
    殺す予約」を武装してよいか。実際に送信を取り消している場合（フロントが
    取消対象メッセージIDを添えてきた場合）だけ True にすること。何も走って
    いない時のキャンセル連打で武装すると、直後の正当な送信を闇討ちする地雷に
    なる（2026-07-24 実測）。"""
    try:
        from app.agent.streaming_session import get_session
        s = get_session(room_id)
        if s and s.is_alive():
            if s.is_turn_active():
                if s.interrupt():
                    _interrupted_rooms.add(room_id)
                    # sinkが「ユーザー中断による空ターン」を見分けるための印。
                    # 空のまま終わったターンはゴミ吹き出しを保存しない（Escパリティ）
                    s._user_cancelled = True
                    _cli_debug(f"[STREAMING] user cancel → interrupt sent (room {room_id[:8]})")
                    return True
            elif allow_arm_pending:
                # 送信取消の意思が明確な場合のみ: 直後に始まるターンを即中止させる
                # （後追いで走り出す事故の根絶）
                s.cancel_next_turn()
                s._user_cancelled = True
                _cli_debug(f"[STREAMING] user cancel armed for next turn (room {room_id[:8]})")
                return True
            else:
                _cli_debug(f"[STREAMING] user cancel no-op (nothing running, room {room_id[:8]})")
                return False
    except Exception as e:
        _cli_debug(f"[STREAMING] cancel wiring failed (room {room_id[:8]}): {e}")
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


# Claude CLI 自身のログイン切れ（~/.claude の OAuth 失効・/logout・revoke）の
# シグネチャ。Max 定額で動かすため ANTHROPIC_API_KEY を外して起動しているので、
# CLI のログインが切れると全部屋が一斉に「Not logged in · Please run /login」
# 相当のエラーで返るようになる（2026-09-19 実発生）。セッション自体は無事。
_AUTH_ERROR_MARKERS = (
    "please run /login",
    "not logged in",
    "oauth token has expired",
    "oauth token revoked",
    "oauth token is invalid",
    "invalid api key",
    "invalid authentication",
    "authentication_error",
    "authentication failed",
    "api error: 401",
)


def _is_auth_error_text(text: Optional[str]) -> bool:
    """True when a turn failed because the Claude CLI itself is logged out."""
    low = (text or "").lower()
    return any(marker in low for marker in _AUTH_ERROR_MARKERS)


def _read_dotenv_value(key: str) -> str:
    """D:/done/.env から key を毎回読み直す（settings は起動時に固定されるため）。

    認証復旧はダンコア（再起動しないプロセス）の中で起きるので、.env に
    トークンを書いた直後の次ターンから効かせるには生ファイルを見る必要がある。
    """
    try:
        for line in (PROJECT_ROOT / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _resolve_claude_oauth_token() -> str:
    """CLI に渡す長期 OAuth トークン（`claude setup-token` の出力）を解決する。

    優先順: プロセス環境変数 → settings（起動時の .env） → 生 .env 再読込。
    """
    token = (os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or "").strip()
    if token:
        return token
    try:
        from app.config import settings
        token = (getattr(settings, "CLAUDE_CODE_OAUTH_TOKEN", "") or "").strip()
    except Exception:
        token = ""
    if token:
        return token
    return _read_dotenv_value("CLAUDE_CODE_OAUTH_TOKEN")


def _inject_claude_cli_auth(env: dict) -> dict:
    """ログイン切れ復旧経路: .env のトークンを CLI 起動 env に注入する。

    トークン未設定なら何もしない（従来通り ~/.claude のログイン状態を使う）。
    """
    if not env.get("CLAUDE_CODE_OAUTH_TOKEN"):
        token = _resolve_claude_oauth_token()
        if token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return env


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
    "auth_expired": {
        "ja": "Claude CLI のログインが切れているため応答できません（ダンコアを動かしている"
        "PC側の認証が失効しました。会話の文脈は保持されています）。復旧方法はどちらか:\n"
        "1. そのPCのターミナルで `claude login` を実行してブラウザでログインし直す\n"
        "2. `claude setup-token` で長期トークンを発行し、D:/done/.env に "
        "`CLAUDE_CODE_OAUTH_TOKEN=<token>` を追記する（以後ログイン切れの影響を受けない）\n"
        "どちらもダンコアの再起動は不要で、次のメッセージから復旧します。",
        "en": "The Claude CLI is logged out, so I can't respond (the login on the PC running "
        "Dan Core expired; the conversation context is preserved). To recover, either:\n"
        "1. run `claude login` in a terminal on that PC and sign in via the browser, or\n"
        "2. run `claude setup-token` and add `CLAUDE_CODE_OAUTH_TOKEN=<token>` to D:/done/.env "
        "(then future logouts no longer affect Dan).\n"
        "No Dan Core restart is needed; the next message will work.",
    },
    "loop_detected": {
        "ja": "同じ操作を何度も繰り返して先に進めなくなっていたため、いったん区切りました。"
        "文脈は保持したままセッションを立て直したので、別のやり方で進めるか、"
        "状況（うまくいかない画面など）を教えてもらえれば続けます。",
        "en": "I was repeating the same action over and over without making progress, so I "
        "stopped here. I rebuilt the session with the context preserved — tell me how "
        "you'd like to proceed (or what's stuck) and I'll continue with a different approach.",
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


# Image-eviction guard (root fix for screenshot-driven bloat & collapse).
# Browser screenshots dominate transcript size — each is ~125KB of base64 and a
# single browsing turn can add a dozen. Re-prefilling every old screenshot on
# each --resume both slows the first token AND degrades the model into
# repetition collapse ("court" spam). Unlike text, a stale screenshot carries
# almost no value: the model only needs the most RECENT views to keep acting.
# Before each resume we rewrite the transcript jsonl in place, keeping the last
# DAN_IMAGE_EVICT_KEEP screenshots intact and replacing older image blocks with
# a tiny text placeholder. The conversation thread — and every
# tool_use/tool_result pairing — stays intact, so unlike the size-triggered
# drop+reseed this loses NO conversational context. Set DAN_IMAGE_EVICT_KEEP=0
# to disable.
_IMAGE_EVICT_KEEP = int(os.getenv("DAN_IMAGE_EVICT_KEEP", "3"))


def _iter_image_blocks(blocks):
    """Yield (list, index) for every image block in a content list, recursing
    into tool_result content (where browser screenshots actually live)."""
    if not isinstance(blocks, list):
        return
    for i, b in enumerate(blocks):
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt == "image":
            yield (blocks, i)
        elif bt == "tool_result":
            inner = b.get("content")
            if isinstance(inner, list):
                yield from _iter_image_blocks(inner)


def _compact_transcript_images(session_id: str, keep_recent: Optional[int] = None) -> bool:
    """Strip stale screenshots from a CLI transcript, keeping the last N intact.

    Returns True if the transcript was rewritten (images evicted). Best-effort:
    any failure leaves the transcript untouched and returns False, so the caller
    falls back to the existing size-triggered drop+reseed.
    """
    keep = _IMAGE_EVICT_KEEP if keep_recent is None else keep_recent
    if keep <= 0:
        return False
    path = _session_transcript_path(session_id)
    if path is None:
        return False
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        _cli_debug(f"_compact_transcript_images read failed: {e}")
        return False

    parsed: list = []          # per line: dict (json) | str (verbatim) | None (blank)
    image_refs: list = []      # (container_list, index) for every image block, in file order
    for line in raw_lines:
        if not line.strip():
            parsed.append(None)
            continue
        try:
            obj = json.loads(line)
        except Exception:
            parsed.append(line)  # un-parseable: preserve verbatim
            continue
        parsed.append(obj)
        msg = obj.get("message") if isinstance(obj, dict) else None
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, list):
            image_refs.extend(_iter_image_blocks(content))

    if len(image_refs) <= keep:
        return False  # nothing stale to evict

    for blocks, idx in image_refs[:-keep]:
        try:
            media = (blocks[idx].get("source") or {}).get("media_type", "") or ""
        except Exception:
            media = ""
        suffix = f" ({media})" if media else ""
        blocks[idx] = {
            "type": "text",
            "text": f"[古いスクリーンショットは文脈節約のため省略{suffix}]",
        }

    try:
        out_lines = []
        for item in parsed:
            if item is None:
                out_lines.append("")
            elif isinstance(item, str):
                out_lines.append(item)
            else:
                out_lines.append(json.dumps(item, ensure_ascii=False))
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        _cli_debug(f"_compact_transcript_images write failed: {e}")
        return False
    _cli_debug(
        f"_compact_transcript_images: evicted {len(image_refs) - keep} stale "
        f"screenshots (kept {keep}) from session {session_id}"
    )
    return True


# Behavioral-loop guard. A bloated browser context can degrade the model into
# re-issuing the SAME tool call (e.g. "open manager.line.biz") many times in a
# row. The CLI keeps "succeeding" on each step, so is_error never fires and the
# error-driven recovery (parse-error / thinking-desync) cannot catch it — the
# turn just loops for minutes. We detect N consecutive identical tool calls and
# route the turn through the same recovery as a poison (stop + reseed from DB,
# which sheds the heavy screenshot transcript that drove the loop).
# Set DAN_LOOP_GUARD_THRESHOLD=0 to disable.
_LOOP_GUARD_THRESHOLD = int(os.getenv("DAN_LOOP_GUARD_THRESHOLD", "8"))

# Text-repetition guard. A bloated/degraded context can also collapse the model
# into emitting the SAME output LINE over and over ("court — proceeding:" x500),
# leaking English and bleeding unrelated context. Unlike a tool-call loop this
# never raises is_error and the tool-loop guard above does not see it (no tool
# call), so it streams garbage to the UI until the idle timeout — and because the
# turn never finalizes, the spam is never persisted (only ever lives in the
# stream). We detect N consecutive identical non-blank output lines and route the
# turn through the SAME recovery as a behavioral loop (interrupt → friendly
# result → stop + reseed from DB). The detected sample is logged so the otherwise
# unpersistable repetition is finally captured. Set 0 to disable.
_TEXT_LOOP_GUARD_THRESHOLD = int(os.getenv("DAN_TEXT_LOOP_GUARD_THRESHOLD", "12"))

# 閲覧系（読み取り専用）のブラウザ操作。長いLPを順に確認するときに同じ
# screenshot / scroll を何度も繰り返すのは正当な作業なので、ループ判定から除外する。
# 状態を変える操作（open / click / type / select / back）は引き続き監視対象。
_LOOP_EXEMPT_BROWSER_ACTIONS = {
    "screenshot",
    "scroll",
    "get_interactive_elements",
    "get_state",
    "get_elements",
}


def _is_loop_exempt(name: str, tool_input: Optional[Dict[str, Any]]) -> bool:
    """確認用の繰り返しが正当なツール呼び出しか（=ループ判定から外すべきか）。

    実際のツール名は `mcp__dan-tools__browser` のように MCP 接頭辞が付くため、
    完全一致ではなく部分一致（"browser" in name）で判定する。
    （`_format_tool_label` も同じ規約を使っている）
    """
    n = (name or "").lower()
    # browser 系（mcp__dan-tools__browser / browser / browser_screenshot 等）。
    # action（screenshot / scroll …）で閲覧系かどうかを判定する。
    if "browser" in n:
        action = ""
        if isinstance(tool_input, dict):
            action = str(tool_input.get("action", "")).lower()
        if action:
            return action in _LOOP_EXEMPT_BROWSER_ACTIONS
        # action が取れないレガシー browser_screenshot 等は名前で判定
        return any(a in n for a in _LOOP_EXEMPT_BROWSER_ACTIONS)
    return False


def _tool_call_signature(name: str, tool_input: Optional[Dict[str, Any]]) -> str:
    """Stable signature for a tool call, used to spot consecutive repeats.

    Same tool name + same input → same signature, so a verbatim-repeated
    "open <url>" / "click @e5" collapses to one repeating signature.
    """
    try:
        payload = json.dumps(tool_input or {}, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        payload = str(tool_input)
    return f"{name}|{payload}"


class _LoopGuard:
    """Counts consecutive identical tool-call signatures within a turn.

    ``record(sig)`` returns True once the same signature has been seen
    ``threshold`` times in a row. A threshold <= 0 disables the guard (record
    always returns False). ``reset()`` clears the run at each new turn.
    """

    def __init__(self, threshold: int):
        self.threshold = threshold
        self._last_sig: Optional[str] = None
        self._count = 0

    def reset(self) -> None:
        self._last_sig = None
        self._count = 0

    def record(self, sig: str) -> bool:
        if self.threshold <= 0:
            return False
        if sig == self._last_sig:
            self._count += 1
        else:
            self._last_sig = sig
            self._count = 1
        return self._count >= self.threshold


class _TextLoopGuard:
    """Detects degenerate repetition in streamed output text within a turn.

    Streamed assistant text arrives in fragments; ``record(text)`` accumulates
    them, splits on newlines, and tracks the last ``window`` substantive lines.
    It returns True once ANY single line has appeared ``threshold`` times within
    that window. Counting over a window (not just strictly consecutive) catches
    BOTH a line repeated back-to-back AND a small set of lines cycling — e.g.
    ``court 停止。`` interleaved with ``court — proceeding:`` / ``ok run:`` /
    ``Now executing:`` — which a consecutive-only check misses.

    Blank lines and trivial/separator-only lines (< 3 chars or no alphanumeric,
    e.g. '---', '| --- |') are ignored so legit rules don't trip it. CJK counts
    as alphanumeric, so Japanese repeated lines are still caught. ``threshold``
    <= 0 disables. ``sample`` holds the offending line for logging. The sink also
    calls ``reset()`` on every tool_use (a real action = genuine progress), so
    only tool-less text spam accumulates. ``reset()`` also clears the run at each
    new turn.
    """

    def __init__(self, threshold: int, window: int = 40):
        self.threshold = threshold
        self.window = max(window, threshold)
        self._buf = ""
        self._win: list = []
        self._counts: Dict[str, int] = {}
        self._sample = ""

    def reset(self) -> None:
        self._buf = ""
        self._win = []
        self._counts = {}
        self._sample = ""

    def record(self, text: str) -> bool:
        if self.threshold <= 0 or not text:
            return False
        self._buf += text
        # Bound the buffer: only the trailing incomplete line matters.
        if len(self._buf) > 8192:
            self._buf = self._buf[-8192:]
        fired = False
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            s = line.strip()
            if not s or len(s) < 3 or not any(ch.isalnum() for ch in s):
                # blank / trivial / separator-only line: ignore (don't count) so
                # legit horizontal rules / table rules never trip the guard.
                continue
            self._win.append(s)
            self._counts[s] = self._counts.get(s, 0) + 1
            if len(self._win) > self.window:
                old = self._win.pop(0)
                self._counts[old] -= 1
                if self._counts[old] <= 0:
                    del self._counts[old]
            if self._counts[s] >= self.threshold:
                self._sample = s
                fired = True
                break
        return fired

    @property
    def sample(self) -> str:
        return self._sample


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

    # Heartbeat the run so an active turn never looks stale to the sweeper.
    _heartbeat_run_sync(run_id)

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


_RUN_HEARTBEAT_AT: dict[str, float] = {}
_RUN_HEARTBEAT_INTERVAL = 15.0  # seconds; must stay well under run_service.STALE_RUN_SECONDS


def _heartbeat_run_sync(run_id: Optional[str]) -> None:
    """Bump the run's updated_at so an active turn isn't mistaken for a zombie.

    Called on every execution event (throttled). A long, genuinely-active turn
    keeps updated_at fresh; if the turn dies without writing its final state, the
    heartbeat stops and run_service.get_current_run sweeps it after
    STALE_RUN_SECONDS so the mobile live bubble stops spinning. Best-effort.
    """
    if not run_id:
        return
    now = time.monotonic()
    if now - _RUN_HEARTBEAT_AT.get(run_id, 0.0) < _RUN_HEARTBEAT_INTERVAL:
        return
    _RUN_HEARTBEAT_AT[run_id] = now
    try:
        from app.services.supabase_client import get_supabase_client

        sb = get_supabase_client().client
        sb.table("agent_runs").update(
            {"updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", run_id).execute()
    except Exception as e:  # noqa: BLE001 - heartbeat must never break the turn
        _cli_debug(f"_heartbeat_run_sync failed: {e}")


def _start_run_heartbeat(run_id: Optional[str]) -> threading.Event:
    """ターン実行中、発話が無くても run の updated_at を打ち続ける心拍スレッド。

    心拍は従来 execution_events の保存時にしか打たれず、発話のない長いツール実行
    （90秒超のスクリプト等）の間に run_service.get_current_run の stale sweep が
    実行中の run を failed に誤判定し、ライブ表示が消えていた（current-run は
    フロントから2秒間隔でポーリングされるので必ず踏む）。イベントの有無に
    依存しない心拍で「本当に死んだ run」だけが掃除されるようにする。

    Returns: stop用 Event（set() で停止）。run_id が無ければ何もしない。
    """
    stop = threading.Event()
    if not run_id:
        return stop

    def _beat() -> None:
        while not stop.wait(_RUN_HEARTBEAT_INTERVAL):
            _heartbeat_run_sync(run_id)

    threading.Thread(target=_beat, daemon=True).start()
    return stop


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
        load_artifact_descriptions, load_artifact_publish_state,
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

    # Publish state of this room's artifacts so Dan knows what is already live
    # (and stops asking "shall I publish?" for already-published sites).
    artifact_state = load_artifact_publish_state(room_id=room_id)
    if artifact_state:
        parts.append(artifact_state)

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
        "- ONE site = ONE slug = ONE card. A multi-page site MUST live under a single "
        "`frontend/src/app/artifacts/<slug>/` directory as nested routes "
        "(`<slug>/page.tsx`, `<slug>/about/page.tsx`, `<slug>/contact/page.tsx`). NEVER "
        "split the pages of one site into sibling directories (e.g. `<slug>-about/`, "
        "`<slug>-contact/`) — that registers the same site as multiple cards. Sub-pages "
        "are sub-routes of the same slug.\n"
        "- For navigation inside an artifact, do not import `next/link` directly for "
        "`/artifacts/<slug>` links. Import `ArtifactLink` from "
        "`@/components/artifacts/artifact-link` and alias it as `Link`, or use helpers "
        "from `@/lib/artifact-paths` when storing URLs. This preserves `/preview/<slug>` "
        "and custom-domain clean paths while the source stays under `/artifacts/<slug>`.\n"
        "- An artifact's public delivery URL is `<host>/preview/<slug>` (the DB "
        "`share_url`). Use that when telling the user where their site is. Vercel "
        "deployment URLs (`frontend-xxxxx.vercel.app`) and any `<slug>-done.vercel.app` "
        "alias are internal or retired — never give them as the delivery URL.\n"
        "- Publishing is automatic: registering an artifact commits it to the production "
        "branch so it goes live at `<host>/preview/<slug>` within a couple of minutes. "
        "You do NOT need to run any deploy script (`deploy_frontend_artifacts.py` is "
        "retired). Editing an existing artifact re-runs the same auto-publish; do not "
        "solve delivery by handing out a new URL.\n"
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
6. Claude Code自身が起動した背景作業の完了は、常駐セッションが完了イベントを受けて続報する。`schedule_followup(note, delay_seconds)` は、デプロイ・DNS反映など**外部サービスの状態を後で再確認する必要があり、確認対象を具体的に示せる時だけ**使え。単に「報告します」「お待ちください」と書いただけで予約してはならない。ユーザーの返答待ちでは絶対に使わない。
7. ユーザーが個人情報（電話番号・クレジットカード・住所・誕生日・メール等）を口にしたら、その場で即座に `remember_personal_info` で保存しろ。一度教われば二度と聞き返すな。システムプロンプトの「保存済み個人情報」一覧にある情報は既に保有済みなので、実値が要る操作の直前にだけ `get_personal_info` で取り出して使え。ログインID/パスワードは従来通り `save_credentials`。"""


_BROWSER_AUTH_RULES = """## Browser authentication handoff rules

- For interactive browser work that may require user input later, use the `browser` MCP tool. Do not launch a one-shot Playwright script from Bash.
- Start authenticated browser tasks with `browser(action="open_target", url="<actual destination>")`. Never open a login page first. Reuse the existing authenticated session when the destination opens successfully; log in only after the destination redirects to an unauthenticated page.
- When an OTP / verification code is required, preserve the current browser page. Do not close the browser, navigate away, or resend a code unless the current page has been checked and the code is expired or the user explicitly asks for a resend.
- **SMS code** → `browser(action="wait_for_otp_from_app", ref="...", press_enter=true)` (default source=sms; the Android app forwards and enters it without exposing it). Forwarding only works for codes sent to the phone that runs the Dan app with SMS forwarding ON — a code sent to anyone else's phone number can never be auto-forwarded, so confirm the destination number is the registered device's before relying on it.
- **Email code** (a code mailed to an inbox, e.g. a Gmail address) → you CAN read email inboxes directly via IMAP. Call `browser(action="wait_for_otp_from_app", source="email", email_address="<the inbox the code was sent to>", ref="...")` FIRST, before deciding the auth method — if the inbox is enabled it auto-reads the code; if not, the tool itself returns one-time setup guidance (`needs_app_password`) to relay to the user, then retry. NEVER claim you cannot read email codes, and NEVER switch to phone/SMS auth just to avoid email verification. Asking the user to read a code manually is a last resort (tool unusable, or no code within the timeout).
- When the user sends an OTP manually, inspect the still-open page first and enter it into the existing challenge. If the page is no longer usable, explain that before requesting a new code.
- **CAPTCHA** (reCAPTCHA v2/v3/Enterprise, hCaptcha, Cloudflare Turnstile, or a distorted-text image captcha on a form / login page) → you CAN solve these yourself. Call `browser(action="solve_captcha")` BEFORE clicking submit/login — it detects every widget on the page, solves it via 2captcha, and injects the token (then click submit/login). The 2captcha API key is already configured server-side: NEVER ask the user for a 2captcha API key, and NEVER claim captcha solving is unavailable or unconfigured. Asking the user to click or solve a captcha for you is a last resort, allowed only after `solve_captcha` has actually been called and returned an error.
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


def _commit_mentioned_timeline_draft(room_id: str, draft: Optional[Dict[str, Any]]) -> Optional[str]:
    """Commit the timeline draft attached to one normal chat turn, if changed."""
    if not draft:
        return None
    try:
        from app.services import timeline_commands as _timeline_commands
        from app.services import timeline_draft as _timeline_draft
        from app.services.timeline_agent import _read_assets_file

        latest = _timeline_draft.load_draft(room_id, draft["draft_id"])
        if not latest.get("log"):
            return None
        assets = {str(a.get("id")): a for a in _read_assets_file(_timeline_draft._room_dir(room_id))}
        baseline = set(latest.get("baseline_problems") or [])

        def validate(sequence: Dict[str, Any], _unused_room: str) -> List[str]:
            return [p for p in _timeline_commands.validate_sequence(
                sequence, assets, asset_dir=str(_timeline_draft._room_dir(room_id))
            ) if p not in baseline]

        result = _timeline_draft.commit_draft(room_id, draft["draft_id"], validate)
        if result.get("ok"):
            return "タイムラインの変更を検証して反映しました。"
        if result.get("conflict"):
            return "タイムラインは作業中に更新されたため、今回の変更は反映しませんでした。"
        return "タイムラインの変更は検証に通らなかったため、反映しませんでした: " + "; ".join(result.get("problems") or [])
    except Exception as exc:  # noqa: BLE001
        logger.exception("mentioned timeline draft finalization failed")
        return f"タイムライン変更の確定に失敗しました: {exc}"


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
    _inject_claude_cli_auth(env)

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


_ALLOWED_CLI_MODELS = {"opus", "sonnet", "haiku", "fable"}
# room_id → 解決済みモデル。作成時に固定され以後不変なので恒久キャッシュでよい。
_room_model_cache: Dict[str, str] = {}


def _resolve_cli_model(room_id: Optional[str] = None) -> str:
    """CLI を起動するモデル名を解決する。

    解決順（上が優先）:
      1. ルーム単位の選択（projects.metadata.model を room_id で引く）
      2. `DAN_CLI_MODEL` 環境変数（全ルーム一括切替用）
      3. "opus"（デフォルト）

    許可リスト外の値は無視して次の手段にフォールバックする（--model への
    不正な引数混入を防ぐ安全弁）。
    """
    # 1. ルーム単位の選択（新チャット作成時に保存された値）
    if room_id:
        cached = _room_model_cache.get(room_id)
        if cached:
            return cached
        try:
            from app.services.supabase_client import get_supabase_client
            sb = get_supabase_client().client
            res = (
                sb.table("projects").select("metadata")
                .eq("room_id", room_id).limit(1).execute()
            )
            if res.data:
                meta = res.data[0].get("metadata") or {}
                if isinstance(meta, dict):
                    m = (meta.get("model") or "").strip().lower()
                    if m in _ALLOWED_CLI_MODELS:
                        _room_model_cache[room_id] = m
                        return m
        except Exception as e:
            logger.debug("resolve model failed for room %s: %s", room_id, e)

    # 2. 環境変数による全ルーム一括切替
    env = (os.environ.get("DAN_CLI_MODEL") or "").strip().lower()
    if env in _ALLOWED_CLI_MODELS:
        return env

    # 3. デフォルト
    return "opus"


def _build_cli_cmd(
    claude_cmd: str,
    cli_js: Optional[str],
    mcp_config_path: str,
    system_prompt: str,
    resume_session_id: Optional[str] = None,
    fork_session: bool = False,
    model: str = "opus",
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
        "--model", model,
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
    stderr_tail: list = []

    def _drain_stderr():
        try:
            for line in process.stderr:
                line = line.strip()
                if line:
                    _cli_debug(f"CLI stderr: {line[:200]}")
                    stderr_tail.append(line[:300])
                    if len(stderr_tail) > 20:
                        del stderr_tail[0]
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
    # プロセス終了後、stdout が EOF に達するまでの猶予。これを超えても EOF が来ない
    # 場合、孫プロセスが書き込み端を握って EOF が来ないと判断し、ブロック中の
    # reader スレッドを見捨ててメインループを抜ける。
    STDOUT_EOF_GRACE = 20   # seconds

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

    # stdout は専用 daemon スレッドで読み、行をキューに流す。プロセスが終了しても
    # 孫プロセス (ffmpeg / MCP / ツールのヘルパー) が stdout の書き込み端を継承した
    # まま生き残ると EOF が来ず readline() が永久ブロックする。Windows ではこの
    # 同期 read を別スレッドからキャンセルできない (fd を閉じても保留中の ReadFile は
    # 解除されない) ため、読み取り自体を隔離する。メインはキューから timeout 付きで
    # 取り出し、プロセス終了後 STDOUT_EOF_GRACE 秒新着が無ければ、ブロック中の reader を
    # 見捨てて先へ進む (reader は daemon なのでプロセス終了時に道連れで消える)。
    # これにより、本番で観測した「動画は完成したのにジョブが running のままハングする」
    # 事象を根絶する。
    _stdout_queue: "thread_queue.Queue" = thread_queue.Queue()

    def _stdout_reader():
        try:
            while True:
                raw = process.stdout.readline()
                if not raw:
                    break  # EOF
                _stdout_queue.put(raw)
        except (ValueError, OSError):
            pass
        finally:
            _stdout_queue.put(None)  # 番兵: ストリーム終了 or reader 死亡

    stdout_thread = threading.Thread(target=_stdout_reader, daemon=True)
    stdout_thread.start()

    _proc_exited_at: list = [None]
    while True:
        try:
            line = _stdout_queue.get(timeout=1.0)
        except thread_queue.Empty:
            # 新着なし。プロセスが生きている間は既存の idle watchdog が長時間ハングを
            # 監視するのでここでは抜けない。プロセスが終了済みで、終了後
            # STDOUT_EOF_GRACE 秒経っても新たな行が来ない場合のみ、孫がパイプを握って
            # EOF が来ないと判断し、ブロック中の reader を見捨ててループを抜ける。
            if process.poll() is not None:
                if _proc_exited_at[0] is None:
                    _proc_exited_at[0] = time.time()
                elif time.time() - _proc_exited_at[0] > STDOUT_EOF_GRACE:
                    _cli_debug(
                        f"stdout: PID={process.pid} exited (code={process.returncode}) but no "
                        f"EOF within {STDOUT_EOF_GRACE}s; abandoning blocked reader thread."
                    )
                    break
            continue
        if line is None:
            break  # EOF 番兵 — ストリーム正常終了
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
        stderr_thread.join(timeout=2)
        if _is_auth_error_text("\n".join(stderr_tail)):
            # CLI ログイン切れで result を出さずに落ちた。復旧手順を返す。
            event_queue.put({"type": "error", "message": _recovery_message("auth_expired")})
        else:
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
    _inject_claude_cli_auth(env)

    result_data = None
    done_saved = False
    # 無音ツール実行中も run を stale sweep から守る心拍（finallyで停止）
    _hb_stop = _start_run_heartbeat(run_id)
    try:
        # 履歴肥大ガード: --resume するトランスクリプトが大きすぎると、最初のトークンまで
        # 数分かかる（巨大プロンプトの再prefill）。閾値を超えたらセッションを手放し、
        # DB の直近会話を要約して文脈を引き継いだ上で新規セッションとして開始する。
        # 会話本体は chat_messages に残るので文脈は失われない。
        # 根本対策: --resume の前に古いスクリーンショットを退避する。画像はトランスクリプト
        # 肥大の主因（1枚 ~125KB）で、古い画像は文脈価値がほぼ無いのに毎ターン再prefillされ、
        # 初動の遅延とモデルの反復崩壊（"court" 連発）を招く。直近 N 枚だけ残して古い画像を
        # テキストプレースホルダに置換する。会話スレッドは保たれるので文脈は失われない。
        if resume_session_id:
            _compact_transcript_images(resume_session_id)

        # 退避してもなお巨大なら（画像以外のテキストで肥大）、従来どおりセッションを手放して
        # DB から reseed する保険に乗せる。
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
        cli_model = _resolve_cli_model(room_id)
        launch_system_prompt, launch_content = _prepare_cli_launch_payload(system_prompt, content)
        cmd = _build_cli_cmd(claude_cmd, cli_js, mcp_config_path, launch_system_prompt, resume_session_id, fork_session=need_fork, model=cli_model)
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
            cmd = _build_cli_cmd(claude_cmd, cli_js, mcp_config_path, retry_system_prompt, resume_session_id=None, model=cli_model)
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
            elif is_error and _is_auth_error_text(result_text):
                # CLI ログイン切れ: セッションは無事なので消さない。復旧手順だけ出す。
                text = _recovery_message("auth_expired", _detect_user_lang(content))
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
        _hb_stop.set()
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


def _make_autonomous_sink(room_id: str, user_id: str, project_id: Optional[str], session) -> Any:
    """Receiver for CLI-INITIATED turns (background task finished while the room
    was idle). Runs in the session reader thread. Mirrors the essentials of the
    per-call streaming sink: classify → persist execution events under a fresh
    `background_wake` run (so the live UI shows the work) → save the ai_message
    on result. No SSE consumer exists; the frontend picks the turn up through
    the same run/event polling that renders poller-fired turns."""
    state: Dict[str, Any] = {
        "turn_blocks": [], "final_text_parts": [], "reasoning_steps_acc": [],
        "reasoning_full_acc": [], "turn_start": None, "turn_id": None, "run_id": None,
    }

    def _ensure_run() -> None:
        if state["run_id"] or not project_id:
            return
        try:
            import asyncio as _a
            from app.services.run_service import RunService
            run = _a.run(RunService().create_run(
                project_id=project_id, room_id=room_id,
                metadata={"started_by": "background_wake"},
            ))
            state["run_id"] = run["id"]
            _cli_debug(f"[AUTOWAKE] run {run['id'][:8]} created for CLI-initiated turn (room {room_id[:8]})")
        except Exception as e:  # noqa: BLE001
            _cli_debug(f"[AUTOWAKE] run creation failed (room {room_id[:8]}): {e}")

    def sink(raw_ev: Dict[str, Any]) -> None:
        try:
            rtype = raw_ev.get("type")
            if rtype == "assistant":
                if state["turn_start"] is None:
                    state["turn_start"] = datetime.now(timezone.utc).isoformat()
                    state["turn_id"] = str(uuid.uuid4())
                    _ensure_run()
                blocks = (raw_ev.get("message") or {}).get("content") or []
                for ev in _classify_content_blocks(blocks):
                    if ev["type"] == "text":
                        txt = ev.get("text", "")
                        if txt.strip():
                            state["final_text_parts"].append(txt)
                            state["turn_blocks"].append({"type": "text", "text": txt})
                            state["reasoning_steps_acc"].append(txt.strip())
                            state["reasoning_full_acc"].append(txt.strip())
                            if project_id:
                                _save_execution_event_sync(room_id, "reasoning", project_id=project_id, run_id=state["run_id"], turn_id=state["turn_id"], content=txt.strip())
                    elif ev["type"] == "tool_use":
                        from app.api.project_routes import _format_tool_label
                        tool_label = _format_tool_label(ev.get("name", ""), ev.get("input", {}))
                        state["turn_blocks"].append({"type": "tool", "name": ev.get("name", ""), "label": tool_label, "detail": _tool_detail(ev.get("input", {}))})
                        state["reasoning_steps_acc"].append(f"🔧 {tool_label}")
                        if project_id:
                            _save_execution_event_sync(room_id, "tool_use", project_id=project_id, run_id=state["run_id"], turn_id=state["turn_id"], tool_name=ev.get("name", ""), tool_label=tool_label)
            elif rtype == "system":
                sid = raw_ev.get("session_id")
                if sid:
                    _save_session(room_id, sid)
            elif rtype == "result":
                text = (raw_ev.get("result") or "") or "\n".join(state["final_text_parts"])
                # ghost-bubble guard: an empty autonomous turn saves nothing
                if text.strip() or state["turn_blocks"]:
                    _save_ai_message_sync(
                        room_id,
                        text.strip() or "（バックグラウンド作業の続きを実行しました）",
                        state["reasoning_steps_acc"],
                        state["reasoning_full_acc"],
                        blocks=state["turn_blocks"],
                        created_at=state["turn_start"] or datetime.now(timezone.utc).isoformat(),
                        turn_id=state["turn_id"] or str(uuid.uuid4()),
                    )
                if project_id and state["run_id"]:
                    _save_execution_event_sync(room_id, "done", project_id=project_id, run_id=state["run_id"], turn_id=state["turn_id"], content="completed")
                    _update_run_sync(state["run_id"], state="failed" if raw_ev.get("is_error") else "completed")
                state.update({
                    "turn_blocks": [], "final_text_parts": [], "reasoning_steps_acc": [],
                    "reasoning_full_acc": [], "turn_start": None, "turn_id": None, "run_id": None,
                })
        except Exception as e:  # noqa: BLE001
            _cli_debug(f"[AUTOWAKE] sink error (room {room_id[:8]}): {e}")

    return sink


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

    The session also gets a room-scoped BACKGROUND SINK: when the CLI wakes
    itself between turns (a background task finished while the room was idle —
    the same native wake interactive Claude Code has, empirically confirmed
    2026-07-24), those CLI-initiated turns are classified and saved through it
    instead of being dropped. That is what lets Dan continue work the moment a
    long job finishes, with no poller and no user poke.

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

    cli_model = _resolve_cli_model(room_id)

    # Windows CreateProcess の約32,000文字制限対策（one-shot 経路の
    # _prepare_cli_launch_payload と同じ）。文脈が肥大した部屋では
    # system_prompt を argv に載せるとセッション起動自体が WinError 206 で
    # 失敗する（2026-07-24 吉川ルームで実測）。長い場合は argv には短い
    # 指示だけを渡し、全文は初回ターンの stdin メッセージに載せる。
    needs_stdin_context = len(system_prompt or "") > _CLI_ARG_SYSTEM_PROMPT_LIMIT
    launch_system_prompt = (
        _prepare_cli_launch_payload(system_prompt, "")[0]
        if needs_stdin_context
        else system_prompt
    )

    def build_cmd() -> list:
        c = [claude_cmd, cli_js] if cli_js else [claude_cmd]
        c += [
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
            "--model", cli_model,
            "--max-turns", "200",
            "--mcp-config", mcp_config_path,
            "--append-system-prompt", launch_system_prompt,
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
    _inject_claude_cli_auth(env)
    run_cwd = cwd or str(CLI_WORKSPACE)

    from app.agent.streaming_session import get_session
    existing = get_session(room_id)
    session_is_fresh = existing is None or not existing.is_alive()
    session = get_or_create_session(room_id, build_cmd, env, run_cwd)
    # (Re)install the autonomous-turn receiver with this call's freshest
    # project/user context. Cheap to refresh on every turn.
    session.background_sink = _make_autonomous_sink(room_id, user_id, project_id, session)

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
    if needs_stdin_context and session_is_fresh:
        # argv に載せられなかった runtime context を初回ターンの stdin で渡す
        _, send_content = _prepare_cli_launch_payload(system_prompt, send_content)
        _cli_debug(
            f"[STREAMING] system prompt too long for argv "
            f"({len(system_prompt)} chars) → moved to stdin (room {room_id[:8]})"
        )

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
        # 振る舞いループ検知（同一ツール呼び出しの連続）。is_error が立たない
        # ループを parse-error poison と同じ復旧経路へ乗せるためのフラグ。
        "loop_guard": _LoopGuard(_LOOP_GUARD_THRESHOLD),
        "text_loop_guard": _TextLoopGuard(_TEXT_LOOP_GUARD_THRESHOLD),
        "loop_detected": False,
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
                    # 新ターン開始でループ検知をリセット（追い連絡の次ターンが
                    # 前ターンのカウントを引きずらないように）。
                    state["loop_guard"].reset()
                    state["text_loop_guard"].reset()
                    state["loop_detected"] = False
                blocks = (raw_ev.get("message") or {}).get("content") or []
                for ev in _classify_content_blocks(blocks):
                    if ev["type"] == "text":
                        txt = ev.get("text", "")
                        if txt.strip():
                            state["final_text_parts"].append(txt)
                            state["turn_blocks"].append({"type": "text", "text": txt})
                        _emit(ev)
                        # テキスト反復崩壊の検知。同一出力行が連続 N 回出たら割り込み、
                        # 後段の result / run() が loop_detected を見て friendly result +
                        # stop + reseed（ツールループと同じ復旧）に乗せる。崩壊テキストは
                        # ターンが完了しない限りどこにも永続化されないため、検知サンプルを
                        # ログに残して初めて事後解析できるようにする。
                        if not state["loop_detected"] and state["text_loop_guard"].record(txt):
                            state["loop_detected"] = True
                            _txt_sample = state["text_loop_guard"].sample
                            _cli_debug(
                                f"[STREAMING] TEXT loop detected "
                                f"(line x{_TEXT_LOOP_GUARD_THRESHOLD}) room {room_id[:8]}; "
                                f"interrupting turn; sample={_txt_sample[:200]!r}"
                            )
                            try:
                                session._send_interrupt()
                            except Exception as e:
                                _cli_debug(f"[STREAMING] text-loop interrupt failed: {e}")
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
                        # A real tool call = genuine progress, not a text-only
                        # degeneration. Reset the text-repetition streak so a
                        # legitimate "narrate the same line → act → repeat" loop
                        # (e.g. the same caption before each of 12 screenshots)
                        # never trips the text-loop guard; only tool-less text
                        # spam accumulates. (Repeated tool calls are caught
                        # separately by the tool loop_guard below.)
                        state["text_loop_guard"].reset()
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
                        # 振る舞いループ検知: 同一ツール呼び出しが連続したら割り込んで
                        # ターンを畳む。is_error が立たないループは error 駆動の復旧では
                        # 捕まらず数分回り続けるので、ここで能動的に止める。後段の result /
                        # run() が loop_detected を見て poison と同じ復旧（stop + reseed）に乗せる。
                        # ただし screenshot/scroll 等の閲覧系は確認作業で正当に繰り返すため
                        # 判定対象から外し、カウンタもリセットして誤検知を防ぐ。
                        _ev_name = ev.get("name", "")
                        _ev_input = ev.get("input", {})
                        if _is_loop_exempt(_ev_name, _ev_input):
                            state["loop_guard"].reset()
                        elif not state["loop_detected"] and state["loop_guard"].record(
                            _tool_call_signature(_ev_name, _ev_input)
                        ):
                            state["loop_detected"] = True
                            _loop_action = ""
                            if isinstance(_ev_input, dict):
                                _loop_action = str(_ev_input.get("action", ""))
                            _cli_debug(
                                f"[STREAMING] behavioral loop detected "
                                f"(tool={_ev_name} action={_loop_action} x{_LOOP_GUARD_THRESHOLD}) "
                                f"room {room_id[:8]}; interrupting turn"
                            )
                            try:
                                session._send_interrupt()
                            except Exception as e:
                                _cli_debug(f"[STREAMING] loop interrupt failed: {e}")
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
                if not continuation:
                    # 境界レース対策: 割り込み無しでターンが完了しても、キューに追い連絡が
                    # 残っていれば run_turn のループが直後に次ターンを始める。ここで run を
                    # 完了させると後続ターンが「完了済み run」の下で実行され、ライブ表示
                    # から消える（done も二重になる）。キュー残があれば継続扱いにする。
                    try:
                        continuation = not session._pending.empty()
                    except Exception:
                        pass
                text = result_text or "\n".join(state["final_text_parts"])
                user_cancelled = bool(getattr(session, "_user_cancelled", False))
                if user_cancelled:
                    try:
                        session._user_cancelled = False
                    except Exception:
                        pass
                if not text.strip():
                    if user_cancelled and not state["turn_blocks"]:
                        # Terminal-Esc parity: a user-cancelled turn that produced
                        # NOTHING leaves nothing — no「応答テキストが空でした」ghost
                        # bubble (the exact noise the user reported on 2026-07-24).
                        # Partial work (text/tools) still saves via the normal path.
                        if project_id and not continuation:
                            _save_execution_event_sync(room_id, "done", project_id=project_id, run_id=run_id, turn_id=state["turn_id"] or str(uuid.uuid4()), content="cancelled")
                            _update_run_sync(run_id, state="completed")
                        _emit({"type": "cancelled", "session_id": state["session_id"]})
                        state["turn_blocks"] = []
                        state["final_text_parts"] = []
                        state["reasoning_steps_acc"] = []
                        state["reasoning_full_acc"] = []
                        state["written_file_paths"] = []
                        state["turn_start"] = None
                        state["turn_id"] = None
                        return
                    text = "（応答テキストが空でした。もう一度お試しください。）"
                # Replace the CLI's cryptic parse-error result with a friendly
                # note. The session is dropped + reseeded afterwards (see run()),
                # so the user can just resend and continue with full context.
                if state.get("loop_detected"):
                    text = _recovery_message("loop_detected", _detect_user_lang(content))
                    is_error = True
                elif is_error and _is_parse_error_text(result_text):
                    text = _recovery_message("parse_error", _detect_user_lang(content))
                elif is_error and _is_thinking_desync_error(result_text):
                    text = _recovery_message("thinking_desync", _detect_user_lang(content))
                elif is_error and _is_auth_error_text(result_text):
                    # CLI ログイン切れ: 復旧手順を出す（セッションは無事、run() 側で
                    # プロセスだけ落として次ターンが新 env＝新トークンで立ち上がるようにする）。
                    text = _recovery_message("auth_expired", _detect_user_lang(content))
                    state["auth_expired"] = True
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
        nonlocal session, resume_session_id, send_content
        t0 = time.time()
        # 無音ツール実行中も run を stale sweep から守る心拍（finallyで停止）
        _hb_stop = _start_run_heartbeat(run_id)
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
            elif state.get("loop_detected"):
                # Behavioral loop: the model repeated the same tool call until the
                # loop guard interrupted the turn. The sink already saved a friendly
                # result; we drop + stop the session so the NEXT turn starts FRESH
                # and reseeds from the DB — shedding the bloated browser-screenshot
                # transcript that caused the degradation in the first place.
                _clear_cli_session(room_id)
                try:
                    session.stop()
                except Exception:
                    pass
                _cli_debug(f"[STREAMING] behavioral-loop session cleared for room {room_id[:8]}")
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
            elif res and res.get("subtype") == "cancelled_before_start":
                # ユーザーが送信直後にキャンセルし、ターンが始まる前に握りつぶした。
                # 正常なキャンセルであって「セッション即死」ではないので、下の
                # stale-resume リトライに落としてはならない（落とすとメッセージが
                # 再送されて、キャンセルしたはずの質問に回答が届く——実測で発生）。
                # このターン用に作られた run もここで即クローズする。SSE側の
                # cancelled 処理に任せると、クライアントが既に切断している場合に
                # 「実行中」の器だけが孤児として残り、空のThinkingが90秒回り続ける
                # （2026-07-24 実測）。
                if project_id and run_id and not skip_save:
                    _save_execution_event_sync(room_id, "done", project_id=project_id, run_id=run_id, turn_id=str(uuid.uuid4()), content="cancelled")
                    _update_run_sync(run_id, state="completed")
                _emit({"type": "cancelled", "session_id": None})
            elif state.get("auth_expired") or (
                res and res.get("is_error") and _is_auth_error_text(res.get("result") or "")
            ):
                # CLI ログイン切れ。トランスクリプトは無事なので保存済みセッション id は
                # 残す（--resume で文脈が戻る）。長寿命プロセスだけ落として、次ターンが
                # 新しい env（.env に追記された CLAUDE_CODE_OAUTH_TOKEN / 再ログイン後の
                # ~/.claude）で起動し直せるようにする。
                try:
                    session.stop()
                except Exception:
                    pass
                _cli_debug(f"[STREAMING] auth expired; process dropped for room {room_id[:8]}")
            elif not state["any_result"] and _is_auth_error_text(getattr(session, "raw_tail", lambda: "")()):
                # プロセスが result を出さずに死に、非JSON行にログイン切れの兆候がある。
                # 「復元に失敗」の誤案内にせず、復旧手順を返して終える。
                try:
                    session.stop()
                except Exception:
                    pass
                text = _recovery_message("auth_expired", _detect_user_lang(content))
                t_id = str(uuid.uuid4())
                if not skip_save:
                    _save_ai_message_sync(room_id, text, turn_id=t_id)
                if project_id and run_id:
                    _save_execution_event_sync(room_id, "done", project_id=project_id, run_id=run_id, turn_id=t_id, content="auth_expired")
                    _update_run_sync(run_id, state="failed")
                _emit({
                    "type": "result", "text": text, "session_id": state["session_id"],
                    "is_error": True, "cli_saved": not skip_save, "continuation": False, "turn_id": t_id,
                })
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
                resume_session_id = None
                send_content = content
                if "<conversation_so_far>" not in send_content:
                    reseed = _build_reseed_context(room_id, project_id=project_id)
                    if reseed:
                        send_content = _wrap_latest_user_message(reseed, content)
                try:
                    session = get_or_create_session(room_id, build_cmd, env, run_cwd)
                    session.run_turn(send_content, sink, timeout=_STREAMING_IDLE_TIMEOUT)
                except Exception as retry_error:  # noqa: BLE001
                    _emit({"type": "error", "message": str(retry_error)})
                return
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
            _hb_stop.set()
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
    timeline_refs: Optional[List[Dict[str, Any]]] = None,
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
    timeline_draft: Optional[Dict[str, Any]] = None
    timeline_turn_succeeded = False
    if timeline_refs:
        # A chat mention supplies an explicit creative artifact.  Give the same
        # normal Dan session a draft-only timeline MCP; its other capabilities
        # remain unchanged and the live sequence is still CAS-protected.
        ref = timeline_refs[0]
        content_id = str(ref.get("content_id") or "")
        if content_id:
            try:
                from app.services import timeline_draft as _timeline_draft
                timeline_draft = _timeline_draft.create_draft(
                    room_id, content_id, job_id=f"chat_{uuid.uuid4().hex[:12]}"
                )
                cfg = json.loads(Path(mcp_config_path).read_text(encoding="utf-8"))
                cfg.setdefault("mcpServers", {})["timeline"] = {
                    "command": "python",
                    "args": [str(PROJECT_ROOT / "app" / "timeline_mcp_server.py")],
                    "env": {
                        "DAN_ROOM_ID": room_id,
                        "DAN_DRAFT_ID": timeline_draft["draft_id"],
                        "DAN_JOB_ID": timeline_draft["job_id"],
                        "DAN_CONTENT_ID": content_id,
                        "PYTHONIOENCODING": "utf-8",
                    },
                }
                Path(mcp_config_path).write_text(json.dumps(cfg), encoding="utf-8")
                title = str(ref.get("title") or content_id)
                system_prompt += (
                    "\n\n## Mentioned timeline\n"
                    f"The user explicitly mentioned the production timeline '{title}' (content_id={content_id}). "
                    "Use mcp__timeline__* to inspect, edit, or export it. Timeline mutations are isolated "
                    "in a draft and are committed only after this chat turn validates successfully."
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("timeline mention setup failed: %s", exc)
                timeline_draft = None
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

    # --- run可視性の保証（runなしターンの根絶） ---
    # 内部トリガー（続報ポーラー等）は run_id=None で呼ぶため、ターンが「runなし」で
    # 走り、execution_events も run_id=None で保存される。フロント(PC/モバイル)は
    # 「state=running の run + その run のイベント」だけをライブ描画するので、
    # runなしターンは作業中の表示が一切出ない。さらにその間に届いたユーザーの
    # メッセージは追い連絡として同じ呼び出しに合流し、run_id=None を継承して
    # 連鎖的に不可視になる（2026-06-11「thinkingがすぐ消えて止まって見える」の
    # 根本原因）。project のある部屋では必ず run を作ってから処理する。
    # 完了時の state 更新は streaming/one-shot 両経路の sink が既に行う。
    # skip_save のターン（タイトル生成等のユーザー非対面処理）は対象外。
    if run_id is None and project_id and not skip_save:
        try:
            from app.services.run_service import RunService
            _auto_run = await RunService().create_run(
                project_id=project_id,
                room_id=room_id,
                metadata={"started_by": "internal_auto"},
            )
            run_id = _auto_run["id"]
            _cli_debug(f"auto-created run {run_id[:8]} for internal turn (room {room_id[:8]})")
        except Exception as e:
            _cli_debug(f"auto run creation failed (room {room_id[:8]}): {e}")

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
            if isinstance(ev, dict) and ev.get("type") == "result" and not ev.get("is_error"):
                timeline_turn_succeeded = True
            yield ev
        timeline_status = _commit_mentioned_timeline_draft(room_id, timeline_draft) if timeline_turn_succeeded else None
        if timeline_status:
            yield {"type": "text", "text": timeline_status}
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
            # allow_arm_pending=False: ここは「実行中の one-shot ターンを止める」
            # だけの場所。registry のフラグは sticky なので、武装を許すと
            # 直後の正当な送信を殺す地雷になる（供給経路は違うが chat_routes の
            # supersede 自爆と同型）。
            kill_cli_process(room_id, allow_arm_pending=False)
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
            if event.get("type") == "result" and not event.get("is_error"):
                timeline_turn_succeeded = True
        yield event
    timeline_status = _commit_mentioned_timeline_draft(room_id, timeline_draft) if timeline_turn_succeeded else None
    if timeline_status:
        yield {"type": "text", "text": timeline_status}
