"""Codex CLI (OpenAI) backend for Dan turns.

Second CLI backend next to Claude Code. A room's model decides the backend:
``gpt-*`` models run through ``codex exec`` (ChatGPT sign-in, flat-rate), the
rest keep using the Claude CLI path in :mod:`app.agent.cli_runner`.

What is shared with the Claude path (and therefore survives a mid-room switch):

* persona / rules: the same system prompt text, injected via a per-room Codex
  profile (``$CODEX_HOME/dan_<room>.config.toml`` → ``developer_instructions``)
* tools: the same MCP servers (``app/mcp_server.py`` + optional timeline MCP),
  converted from the JSON config the Claude path writes
* history / memory: Supabase (``chat_messages`` / ``execution_events`` /
  ``agent_runs`` / room state). A switch always starts a fresh Codex thread and
  reseeds it from the DB, exactly like the existing poison/bloat recovery.
* event stream: Codex JSONL items are mapped onto the same Dan events
  (``text`` / ``tool_use`` / ``reasoning`` / ``result`` / ``error``) so the UI,
  execution_events and artifact registration need no changes.

Session ids are stored in ``cli_sessions.cli_session_id`` with a ``codex:``
prefix so the loader can tell which backend a saved session belongs to.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
import queue as thread_queue
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ChatGPT sign-in models exposed by the local Codex CLI (models_cache.json).
CODEX_MODELS = {
    "gpt-6-astra",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
}

SESSION_PREFIX = "codex:"

# Codex rollouts hold every tool output verbatim (one heavy turn was 13.5MB on
# 2026-09-06), and Codex compacts its own context on resume, so the Claude
# transcript threshold (1.5MB) must NOT be reused here. 0 disables the guard.
_ROLLOUT_RESET_BYTES = int(os.environ.get("DAN_CODEX_ROLLOUT_RESET_BYTES", str(400 * 1024 * 1024)))

_CODEX_HOME = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))


def is_codex_model(model: Optional[str]) -> bool:
    return (model or "").strip().lower() in CODEX_MODELS


def backend_for_model(model: Optional[str]) -> str:
    return "codex" if is_codex_model(model) else "claude"


def is_codex_session_id(session_id: Optional[str]) -> bool:
    return bool(session_id) and str(session_id).startswith(SESSION_PREFIX)


def backend_for_session(session_id: Optional[str]) -> str:
    return "codex" if is_codex_session_id(session_id) else "claude"


def thread_id_from_session(session_id: Optional[str]) -> Optional[str]:
    if not is_codex_session_id(session_id):
        return None
    tid = str(session_id)[len(SESSION_PREFIX):].strip()
    return tid or None


def resolve_codex_cli() -> Optional[str]:
    """Locate the ``codex`` executable (npm ``.cmd`` shim is fine: every
    argument we pass is plain ASCII, the prompt goes through stdin)."""
    return shutil.which("codex")


# ---------------------------------------------------------------------------
# Rollout (transcript) hygiene
# ---------------------------------------------------------------------------

def rollout_path(thread_id: str) -> Optional[Path]:
    """Codex stores each thread as ``sessions/YYYY/MM/DD/rollout-<ts>-<thread>.jsonl``."""
    if not thread_id:
        return None
    base = _CODEX_HOME / "sessions"
    if not base.exists():
        return None
    matches = glob.glob(str(base / "**" / f"rollout-*-{thread_id}.jsonl"), recursive=True)
    if not matches:
        return None
    return Path(sorted(matches)[-1])


def rollout_exceeds_limit(thread_id: str, limit_bytes: int) -> bool:
    if limit_bytes <= 0:
        return False
    p = rollout_path(thread_id)
    if p is None:
        return False
    try:
        return p.stat().st_size >= limit_bytes
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Profile (per-room config layered on ~/.codex/config.toml)
# ---------------------------------------------------------------------------

def _toml_basic_string(value: str) -> str:
    """Multi-line TOML basic string (escapes backslash, quotes, control chars)."""
    out = []
    for ch in value:
        code = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch in ("\n", "\t"):
            out.append(ch)
        elif ch == "\r":
            continue
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\u{code:04X}")
        else:
            out.append(ch)
    return '"""\n' + "".join(out) + '\n"""'


def _toml_inline_string(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _profile_name(room_id: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in room_id)
    return f"dan_{safe}"


def profile_path(room_id: str) -> Path:
    return _CODEX_HOME / f"{_profile_name(room_id)}.config.toml"


def build_codex_profile(
    room_id: str,
    mcp_config_path: str,
    system_prompt: str,
) -> str:
    """Write ``$CODEX_HOME/dan_<room>.config.toml`` and return the profile name.

    The MCP servers are taken from the JSON the Claude path already produced
    (``_build_mcp_config`` + optional timeline server) so both backends always
    see the same tools with the same env.
    """
    try:
        mcp_json = json.loads(Path(mcp_config_path).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning("codex profile: mcp config unreadable (%s); continuing without tools", e)
        mcp_json = {}

    effort = (os.environ.get("DAN_CODEX_REASONING") or "medium").strip().lower()
    if effort not in {"low", "medium", "high", "xhigh", "max"}:
        effort = "medium"
    startup_timeout = int(os.environ.get("DAN_CODEX_MCP_STARTUP_SEC", "120"))
    tool_timeout = int(os.environ.get("DAN_CODEX_MCP_TOOL_SEC", "3600"))

    lines = [
        "# Auto-generated per-room Codex profile (Dan). Safe to delete.",
        f"model_reasoning_effort = {_toml_inline_string(effort)}",
        # Dan's workspace rules live in CLAUDE.md; let Codex read the same file.
        'project_doc_fallback_filenames = ["CLAUDE.md"]',
        f"developer_instructions = {_toml_basic_string(system_prompt or '')}",
        "",
    ]
    for name, cfg in (mcp_json.get("mcpServers") or {}).items():
        if not isinstance(cfg, dict):
            continue
        lines.append(f"[mcp_servers.{_toml_inline_string(name)}]")
        lines.append(f"command = {_toml_inline_string(cfg.get('command', 'python'))}")
        args = cfg.get("args") or []
        lines.append("args = [" + ", ".join(_toml_inline_string(a) for a in args) + "]")
        lines.append(f"startup_timeout_sec = {startup_timeout}")
        lines.append(f"tool_timeout_sec = {tool_timeout}")
        env = cfg.get("env") or {}
        if env:
            lines.append("")
            lines.append(f"[mcp_servers.{_toml_inline_string(name)}.env]")
            for k, v in env.items():
                lines.append(f"{_toml_inline_string(k)} = {_toml_inline_string(v)}")
            if "PYTHONIOENCODING" not in env:
                lines.append('"PYTHONIOENCODING" = "utf-8"')
        lines.append("")

    path = profile_path(room_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return _profile_name(room_id)


def cleanup_codex_profile(room_id: str) -> None:
    try:
        profile_path(room_id).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def build_codex_cmd(
    codex_cmd: str,
    profile: str,
    model: str,
    resume_thread_id: Optional[str] = None,
) -> list[str]:
    cmd = [
        codex_cmd,
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--dangerously-bypass-approvals-and-sandbox",
        "-p", profile,
        "-m", model,
    ]
    if resume_thread_id:
        cmd += ["resume", resume_thread_id]
    # "-" = read the prompt from stdin (no Windows command-line length limit).
    cmd.append("-")
    return cmd


# ---------------------------------------------------------------------------
# JSONL → Dan events
# ---------------------------------------------------------------------------

def _item_to_events(item: Dict[str, Any]) -> list[Dict[str, Any]]:
    """Map one Codex item onto Dan events (tool names follow the Claude SDK
    names so ``_format_tool_label`` / artifact path tracking keep working)."""
    itype = item.get("type", "")
    iid = item.get("id", "")
    if itype == "agent_message":
        text = item.get("text") or ""
        return [{"type": "text", "text": text}] if text.strip() else []
    if itype == "reasoning":
        text = item.get("text") or item.get("summary") or ""
        if isinstance(text, list):
            text = "\n".join(str(t) for t in text)
        return [{"type": "reasoning", "text": text}] if str(text).strip() else []
    if itype == "command_execution":
        return [{
            "type": "tool_use",
            "id": iid,
            "name": "Bash",
            "input": {"command": item.get("command") or ""},
        }]
    if itype == "file_change":
        events = []
        for idx, ch in enumerate(item.get("changes") or []):
            kind = (ch.get("kind") or "update").lower()
            name = "Write" if kind == "add" else ("Edit" if kind == "update" else "Delete")
            events.append({
                "type": "tool_use",
                "id": f"{iid}:{idx}",
                "name": name,
                "input": {"file_path": ch.get("path") or ""},
            })
        return events
    if itype == "mcp_tool_call":
        server = item.get("server") or "mcp"
        tool = item.get("tool") or ""
        args = item.get("arguments")
        if not isinstance(args, dict):
            args = {"arguments": args} if args is not None else {}
        return [{
            "type": "tool_use",
            "id": iid,
            "name": f"mcp__{server}__{tool}",
            "input": args,
        }]
    if itype == "web_search":
        return [{
            "type": "tool_use",
            "id": iid,
            "name": "WebSearch",
            "input": {"query": item.get("query") or ""},
        }]
    if itype in ("todo_list", "plan"):
        return [{"type": "tool_use", "id": iid, "name": "TodoWrite", "input": {"items": item.get("items") or []}}]
    if itype == "error":
        msg = item.get("message") or item.get("text") or ""
        return [{"type": "error", "message": str(msg)}] if msg else []
    return []


def _error_text(data: Dict[str, Any]) -> str:
    err = data.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err)
    if err:
        return str(err)
    return str(data.get("message") or "")


def _is_resume_failure(text: str) -> bool:
    low = (text or "").lower()
    if not low:
        return False
    return (
        ("not found" in low and ("session" in low or "thread" in low or "rollout" in low))
        or "no session" in low
        or "failed to resume" in low
        or "could not resume" in low
    )


# ---------------------------------------------------------------------------
# Process runner (mirrors cli_runner._run_cli_process)
# ---------------------------------------------------------------------------

def run_codex_process(
    cmd: list[str],
    content: str,
    env: dict,
    room_id: str,
    event_queue: "thread_queue.Queue",
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    cwd: Optional[str] = None,
) -> Optional[dict]:
    from app.agent import cli_runner as cr

    turn_id = turn_id or str(uuid.uuid4())
    thread_id: Optional[str] = None
    final_text_parts: list[str] = []
    reasoning_steps_acc: list[str] = []
    reasoning_full_acc: list[str] = []
    turn_blocks: list = []
    written_file_paths: list[str] = []
    emitted_tool_ids: set = set()
    result_data: Optional[dict] = None
    errors: list[str] = []
    turn_failed = False
    usage: Dict[str, Any] = {}

    popen_start = time.perf_counter()
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd or str(cr.CLI_WORKSPACE),
        env=env,
        encoding="utf-8",
        errors="replace",
        creationflags=cr._NO_WINDOW,
    )
    logger.info(
        "[DAN_LATENCY] room=%s backend=codex popen_started=%.3fs cwd=%s",
        room_id, time.perf_counter() - popen_start, cwd or cr.CLI_WORKSPACE,
    )

    with cr._process_lock:
        old_process = cr._active_processes.get(room_id)
        cr._active_processes[room_id] = process
    if old_process is not None:
        cr._cli_debug(f"[CODEX] killing orphaned process PID={old_process.pid}")
        cr._terminate_process(old_process)
    cr._cli_debug(f"[CODEX] process started: PID={process.pid}")

    try:
        process.stdin.write(content)
        process.stdin.close()
    except Exception as e:  # noqa: BLE001
        cr._cli_debug(f"[CODEX] stdin write error: {e}")

    def _drain_stderr():
        try:
            for line in process.stderr:
                line = line.strip()
                if line and "Reading additional input from stdin" not in line:
                    cr._cli_debug(f"[CODEX] stderr: {line[:200]}")
                    errors.append(line[:500]) if line.lower().startswith("error") else None
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_drain_stderr, daemon=True).start()

    WATCHDOG_TIMEOUT = int(os.environ.get("DAN_CODEX_WATCHDOG_SEC", "600"))
    STDOUT_EOF_GRACE = 20
    _last_activity = [time.time()]

    def _watchdog():
        while process.poll() is None:
            time.sleep(15)
            elapsed = time.time() - _last_activity[0]
            if elapsed > WATCHDOG_TIMEOUT:
                cr._cli_debug(f"[CODEX] WATCHDOG: no stdout for {elapsed:.0f}s, killing PID={process.pid}")
                try:
                    event_queue.put({
                        "type": "error",
                        "message": (
                            f"dan (Codex) が {WATCHDOG_TIMEOUT // 60} 分応答停止したため強制終了しました。"
                            "もう一度メッセージを送ってください。"
                        ),
                    })
                except Exception:  # noqa: BLE001
                    pass
                cr._terminate_process(process)
                return

    threading.Thread(target=_watchdog, daemon=True).start()

    _stdout_queue: "thread_queue.Queue" = thread_queue.Queue()

    def _stdout_reader():
        try:
            while True:
                raw = process.stdout.readline()
                if not raw:
                    break
                _stdout_queue.put(raw)
        except (ValueError, OSError):
            pass
        finally:
            _stdout_queue.put(None)

    threading.Thread(target=_stdout_reader, daemon=True).start()

    def _emit_tool(ev: Dict[str, Any]) -> None:
        tid = ev.get("id", "")
        if tid and tid in emitted_tool_ids:
            return
        if tid:
            emitted_tool_ids.add(tid)
        try:
            from app.services.chat_artifact_registration import add_written_path, written_paths_from_tool
            for written in written_paths_from_tool(ev.get("name", ""), ev.get("input", {})):
                add_written_path(written_file_paths, written)
        except Exception as e:  # noqa: BLE001
            cr._cli_debug(f"[CODEX] artifact path tracking failed: {e}")
        event_queue.put(ev)
        if project_id:
            from app.api.project_routes import _format_tool_label
            tool_label = _format_tool_label(ev.get("name", ""), ev.get("input", {}))
            cr._save_execution_event_sync(
                room_id, "tool_use", project_id=project_id, run_id=run_id,
                turn_id=turn_id, tool_name=ev.get("name", ""), tool_label=tool_label,
            )
            reasoning_steps_acc.append(f"🔧 {tool_label}")
            turn_blocks.append({
                "type": "tool",
                "name": ev.get("name", ""),
                "label": tool_label,
                "detail": cr._tool_detail(ev.get("input", {})),
            })

    _proc_exited_at: list = [None]
    while True:
        try:
            line = _stdout_queue.get(timeout=1.0)
        except thread_queue.Empty:
            if process.poll() is not None:
                if _proc_exited_at[0] is None:
                    _proc_exited_at[0] = time.time()
                elif time.time() - _proc_exited_at[0] > STDOUT_EOF_GRACE:
                    cr._cli_debug(f"[CODEX] PID={process.pid} exited but no EOF; abandoning reader")
                    break
            continue
        if line is None:
            break
        _last_activity[0] = time.time()
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            cr._cli_debug(f"[CODEX] non-JSON line: {line[:120]}")
            continue

        etype = data.get("type", "")
        if etype == "thread.started":
            thread_id = data.get("thread_id") or thread_id
            if thread_id:
                sid = SESSION_PREFIX + thread_id
                cr._save_session(room_id, sid)
                cr._update_run_sync(run_id, claude_session_id=sid)
            cr._cli_debug(f"[CODEX] thread_id={thread_id}")
        elif etype in ("item.started", "item.updated", "item.completed"):
            item = data.get("item") or {}
            itype = item.get("type", "")
            # Tool-ish items are announced at start; text/reasoning only when complete.
            if itype in ("command_execution", "file_change", "mcp_tool_call", "web_search", "todo_list", "plan"):
                for ev in _item_to_events(item):
                    _emit_tool(ev)
                continue
            if etype != "item.completed":
                continue
            for ev in _item_to_events(item):
                if ev["type"] == "text":
                    final_text_parts.append(ev["text"])
                    turn_blocks.append({"type": "text", "text": ev["text"]})
                    event_queue.put(ev)
                    if project_id and len(ev["text"].strip()) > 10:
                        cr._save_execution_event_sync(
                            room_id, "reasoning", project_id=project_id, run_id=run_id,
                            turn_id=turn_id, content=ev["text"].strip(),
                        )
                        reasoning_steps_acc.append(ev["text"].strip())
                        reasoning_full_acc.append(ev["text"].strip())
                elif ev["type"] == "reasoning":
                    event_queue.put(ev)
                    reasoning_full_acc.append(ev["text"])
                elif ev["type"] == "error":
                    errors.append(ev["message"])
                    event_queue.put(ev)
        elif etype == "turn.completed":
            usage = data.get("usage") or {}
        elif etype == "turn.failed":
            turn_failed = True
            msg = _error_text(data)
            if msg:
                errors.append(msg)
                event_queue.put({"type": "error", "message": msg})
        elif etype == "error":
            msg = _error_text(data)
            if msg:
                errors.append(msg)
                event_queue.put({"type": "error", "message": msg})

    with cr._process_lock:
        if cr._active_processes.get(room_id) is process:
            cr._active_processes.pop(room_id, None)

    try:
        return_code = process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        return_code = -1
    cr._cli_debug(f"[CODEX] process exited with code {return_code}")

    if thread_id is None and return_code != 0 and not errors:
        event_queue.put({"type": "error", "message": f"Codex CLI exited with code {return_code}"})
        return None

    is_error = turn_failed or (return_code != 0 and not final_text_parts)
    result_data = {
        "session_id": (SESSION_PREFIX + thread_id) if thread_id else None,
        "is_error": is_error,
        "num_turns": 1,
        "errors": errors,
        "result_text": final_text_parts[-1] if final_text_parts else "",
        "final_text_parts": final_text_parts,
        "cost": 0,
        "duration_ms": int((time.perf_counter() - popen_start) * 1000),
        "usage": usage,
        "reasoning_steps": reasoning_steps_acc,
        "reasoning_full": reasoning_full_acc,
        "turn_blocks": turn_blocks,
        "written_file_paths": list(written_file_paths),
    }
    return result_data


# ---------------------------------------------------------------------------
# Turn runner (mirrors cli_runner._run_cli_in_thread)
# ---------------------------------------------------------------------------

def _codex_env(room_id: str, project_id: Optional[str]) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")}
    env["DAN_SESSION_ID"] = room_id
    env["DAN_ROOM_ID"] = room_id
    if project_id:
        env["DAN_PROJECT_ID"] = project_id
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    env["GCM_INTERACTIVE"] = "Never"
    env["GH_PROMPT_DISABLED"] = "1"
    env["NPM_CONFIG_YES"] = "true"
    env["CI"] = "1"
    env["DEBIAN_FRONTEND"] = "noninteractive"
    env["NO_COLOR"] = "1"
    from app.config import settings
    for key, val in [
        ("SUPABASE_URL", settings.SUPABASE_URL),
        ("SUPABASE_KEY", settings.SUPABASE_KEY),
        ("SUPABASE_SERVICE_ROLE_KEY", settings.SUPABASE_SERVICE_ROLE_KEY),
    ]:
        if val and key not in env:
            env[key] = val
    return env


def run_codex_turn_in_thread(
    content: str,
    system_prompt: str,
    mcp_config_path: str,
    room_id: str,
    event_queue: "thread_queue.Queue",
    user_id: Optional[str] = None,
    resume_session_id: Optional[str] = None,
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
    cancel_event: Optional[threading.Event] = None,
    skip_save: bool = False,
    cwd: Optional[str] = None,
    model: str = "gpt-6-astra",
):
    """Run one Dan turn through ``codex exec``. Same contract as
    ``cli_runner._run_cli_in_thread`` (events on ``event_queue``, sentinel at
    the end) so ``process_message_cli`` can drive either backend."""
    from app.agent import cli_runner as cr

    cr._thread_local.room_id = room_id
    turn_id = str(uuid.uuid4())
    cr._cli_debug(f"[CODEX] thread started for room {room_id} model={model}")

    codex_cmd = resolve_codex_cli()
    if not codex_cmd:
        event_queue.put({"type": "error", "message": "codex CLI が見つかりません。npm i -g @openai/codex でインストールしてください。"})
        event_queue.put(cr._SENTINEL)
        return

    env = _codex_env(room_id, project_id)
    result_data = None
    done_saved = False
    profile = None
    _hb_stop = cr._start_run_heartbeat(run_id)
    try:
        resume_thread_id = thread_id_from_session(resume_session_id)

        # Rollout bloat guard (same threshold as the Claude transcript guard):
        # drop the thread and reseed from the DB instead of re-prefilling a
        # huge history every turn.
        if resume_thread_id and rollout_exceeds_limit(resume_thread_id, _ROLLOUT_RESET_BYTES):
            cr._cli_debug(f"[CODEX] rollout for {resume_thread_id[:8]} over limit; dropping and reseeding")
            cr._clear_cli_session(room_id)
            resume_thread_id = None
            if "<conversation_so_far>" not in content:
                reseed = cr._build_reseed_context(room_id, project_id=project_id)
                if reseed:
                    content = cr._wrap_latest_user_message(reseed, content)

        profile = build_codex_profile(room_id, mcp_config_path, system_prompt)
        cmd = build_codex_cmd(codex_cmd, profile, model, resume_thread_id)
        cr._cli_debug(f"[CODEX] attempt 1 (resume={resume_thread_id is not None}, prompt len={len(content)})")
        result_data = run_codex_process(
            cmd, content, env, room_id, event_queue,
            user_id=user_id, project_id=project_id, run_id=run_id, turn_id=turn_id, cwd=cwd,
        )

        # Resume failure → clear the saved thread and retry fresh (DB reseed).
        if resume_thread_id and result_data is not None and result_data.get("is_error"):
            combined = " ".join(str(e) for e in result_data.get("errors", []))
            if _is_resume_failure(combined):
                cr._cli_debug(f"[CODEX] resume failed ({combined[:120]}); retrying fresh")
                cr._clear_cli_session(room_id)
                retry_content = content
                if "<conversation_so_far>" not in retry_content:
                    reseed = cr._build_reseed_context(room_id, project_id=project_id)
                    if reseed:
                        retry_content = cr._wrap_latest_user_message(reseed, content)
                cmd = build_codex_cmd(codex_cmd, profile, model, None)
                result_data = run_codex_process(
                    cmd, retry_content, env, room_id, event_queue,
                    user_id=user_id, project_id=project_id, run_id=run_id, turn_id=turn_id, cwd=cwd,
                )

        if result_data:
            session_id = result_data.get("session_id")
            is_error = result_data.get("is_error", False)
            final_text_parts = result_data.get("final_text_parts", [])
            errs = result_data.get("errors", [])
            if session_id and not is_error:
                cr._save_session(room_id, session_id)
                cr._update_run_sync(run_id, claude_session_id=session_id)

            # Codex emits intermediate narration as separate agent_message items
            # and the answer as the last one. The saved message body is the last
            # item (like Claude's `result` text); every item stays in the
            # timeline blocks so the UI still shows the running commentary.
            text = (result_data.get("result_text") or "").strip() or "\n\n".join(
                t for t in final_text_parts if t.strip()
            )
            if not is_error and cr._has_tool_call_leak(text):
                cr._clear_cli_session(room_id)
                cr._cli_debug(f"[CODEX] tool-call text leak; session cleared (room {room_id[:8]})")
            if is_error and not text.strip() and errs:
                text = f"Codex エラー: {'; '.join(str(e) for e in errs)}"
            if not text.strip():
                text = "（応答テキストが生成されませんでした。もう一度お試しください。）"

            cli_saved = False
            if not skip_save:
                cli_saved = cr._save_ai_message_sync(
                    room_id, text,
                    result_data.get("reasoning_steps", []),
                    result_data.get("reasoning_full", []),
                    blocks=result_data.get("turn_blocks", []),
                    turn_id=turn_id,
                )
                cr._cli_debug(f"[CODEX] AI message DB save: cli_saved={cli_saved}, text_len={len(text)}")

            written_paths = result_data.get("written_file_paths", [])
            if user_id and project_id and written_paths:
                try:
                    from app.services.chat_artifact_registration import register_written_chat_artifacts_sync
                    created = register_written_chat_artifacts_sync(written_paths, room_id, project_id, user_id)
                    if created:
                        cr._cli_debug("[CODEX] registered chat artifacts: " + ",".join(r.get("slug", "?") for r in created))
                except Exception as e:  # noqa: BLE001
                    cr._cli_debug(f"[CODEX] artifact registration failed: {e}")

            event_queue.put({
                "type": "result",
                "text": text,
                "session_id": session_id,
                "cost": 0,
                "turns": result_data.get("num_turns", 1),
                "duration_ms": result_data.get("duration_ms", 0),
                "is_error": is_error,
                "cli_saved": bool(cli_saved),
                "saved_message_id": cli_saved if isinstance(cli_saved, str) else None,
                "turn_id": turn_id,
                "backend": "codex",
                "model": model,
                "usage": result_data.get("usage") or {},
            })
            if project_id:
                cr._save_execution_event_sync(
                    room_id, "done", project_id=project_id, run_id=run_id, turn_id=turn_id, content="completed",
                )
            cr._update_run_sync(run_id, state="failed" if is_error else "completed")
    except Exception as e:  # noqa: BLE001
        import traceback
        from app.services.cancellation import CancellationRegistry
        detail = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        cr._cli_debug(f"[CODEX] ERROR: {detail}")
        event_queue.put({"type": "error", "message": detail})
        done_saved = True
        if project_id:
            cr._save_ai_message_sync(
                room_id,
                f"処理中にエラーが発生しました。もう一度お試しください。\n（{type(e).__name__}）",
                turn_id=turn_id,
            )
            cr._save_execution_event_sync(
                room_id, "done", project_id=project_id, run_id=run_id, turn_id=turn_id, content="error",
            )
        cr._update_run_sync(run_id, state="paused" if CancellationRegistry.is_cancelled(room_id) else "failed")
    finally:
        _hb_stop.set()
        if project_id and not result_data and not done_saved:
            from app.services.cancellation import CancellationRegistry
            was_cancelled = CancellationRegistry.is_cancelled(room_id)
            cr._cli_debug(f"[CODEX] safety net: exited without result (cancelled={was_cancelled})")
            if not was_cancelled:
                cr._save_ai_message_sync(room_id, "処理が中断されました。もう一度お試しください。", turn_id=turn_id)
            cr._save_execution_event_sync(
                room_id, "done", project_id=project_id, run_id=run_id, turn_id=turn_id,
                content="cancelled" if was_cancelled else "interrupted",
            )
            cr._update_run_sync(run_id, state="paused" if was_cancelled else "failed")
        cr._cleanup_mcp_config(room_id)
        cleanup_codex_profile(room_id)
        cr._cli_debug("[CODEX] sending sentinel")
        event_queue.put(cr._SENTINEL)
        try:
            from app.services.cancellation import CancellationRegistry
            if cancel_event is not None:
                CancellationRegistry.unregister_if_match(room_id, cancel_event)
            else:
                CancellationRegistry.unregister(room_id)
        except Exception:  # noqa: BLE001
            pass
