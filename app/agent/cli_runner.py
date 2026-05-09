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
import threading
import time
import queue as thread_queue
import unicodedata
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

_SENTINEL = object()  # キュー終了シグナル

# アクティブなCLIプロセスを追跡（room_id → Popen）
_active_processes: Dict[str, subprocess.Popen] = {}
_process_lock = threading.Lock()

# 停止されたroom_idを記録（次回起動時に--fork-sessionを付けるため）
_interrupted_rooms: set = set()

# スレッドローカル: 現在のroom_idを自動追跡（_cli_debugで使用）
_thread_local = threading.local()


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
    row = {
        "room_id": room_id,
        "run_id": run_id,
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


def _save_ai_message_sync(
    room_id: str,
    content: str,
    reasoning_steps: Optional[list] = None,
    reasoning_full: Optional[list] = None,
) -> bool:
    """CLIスレッドからAI応答をchat_messagesに直接保存（sync）。成功=True。disconnect時は1度だけリトライ。"""
    from app.services.supabase_client import get_supabase_client

    ai_context = None
    if reasoning_steps:
        ai_context = {"reasoning_steps": reasoning_steps}
        if reasoning_full:
            ai_context["reasoning_full"] = reasoning_full
    insert_data = {
        "room_id": room_id,
        "sender_id": None,
        "sender_type": "ai",
        "content": content,
    }
    if ai_context:
        insert_data["ai_context"] = ai_context

    for attempt in (1, 2):
        try:
            sb = get_supabase_client().client if attempt == 1 else _fresh_supabase_client()
            result = sb.table("chat_messages").insert(insert_data).execute()
            if result.data:
                _cli_debug(
                    f"_save_ai_message_sync OK (attempt {attempt}): msg_id={result.data[0].get('id', '?')}"
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
    skill_entries = sorted(
        [f"{skill.name}: {skill.description}" for skill in SkillRegistry.list_all()],
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

    # Runtime contract: tool/skill visibility and behavior policy.
    parts.append(_build_runtime_contract_section())
    parts.append(_build_language_alignment_section(latest_user_message, user_messages))

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

    # Approved plan — injected near the end for recency bias.
    active_plan = load_active_plan(room_id=room_id)
    if active_plan:
        parts.append(active_plan)

    # Absolute rules — placed LAST for maximum attention.
    parts.append(
        "## Deliverable Placement Rules\n\n"
        "- Production websites, dashboards, tools, and client-facing deliverables "
        "must be created under `frontend/src/app/artifacts/<slug>/`.\n"
        "- Do not create or edit production deliverables under `frontend/src/app/demo/`. "
        "`/demo` is deprecated and reserved only for explicitly approved proposal-video prototypes.\n"
        "- When creating a deliverable, make sure it has a `page.tsx` entry so it can be "
        "registered as a chat artifact and opened from the chat header."
    )
    parts.append(_ABSOLUTE_RULES)

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
4. browserツールで実現できない操作（ダウンロード等）はBashでPythonスクリプトを書いて直接Playwrightを使え。persistent contextのパス: ~/.ai_secretary/browser_data
5. 長期記憶が必要なら `read_file` で `~/.dan/workspace/MEMORY.md` を読め。"""


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
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
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
    reasoning_steps_acc = []  # DB-first: reasoning短縮ラベル蓄積
    reasoning_full_acc = []   # DB-first: reasoning全文蓄積

    # --include-partial-messages による重複を防ぐ
    # メッセージIDごとに「処理済みブロックのスナップショット」を記録
    # ブロック数だけでなく内容変更も検出するため、各ブロックのハッシュを保持する
    processed_block_snapshots: Dict[str, list] = {}
    # tool_use は ID 単位で一度だけ送信（partial でハッシュが揺れても重複しない）
    emitted_tool_use_ids: set = set()

    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd or str(CLI_WORKSPACE),
        env=env,
        encoding="utf-8",
        errors="replace",
    )

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
    # Bash の長時間コマンド (例: npm install) を許容するためデフォルト 5 分。
    # tool_result が来ない間 (= 実際に hang) に発火する。
    #
    # 特例: Task (サブエージェント) 呼び出し中は別 Claude Code インスタンスが
    # 裏で 10〜20 分走りうる。その間 dan 本体は沈黙するので通常閾値だと誤発火する。
    # → Task in-flight 中は閾値を 30 分に延長。
    WATCHDOG_TIMEOUT_NORMAL = 300         # seconds
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
                event_queue.put(ev)

                # DB-first: CLIスレッドから直接DB保存（SSE断線対策）
                if project_id:
                    if ev["type"] == "tool_use":
                        from app.api.project_routes import _format_tool_label
                        _save_execution_event_sync(
                            room_id, "tool_use", project_id=project_id, run_id=run_id,
                            tool_name=ev.get("name", ""),
                            tool_label=_format_tool_label(ev.get("name", ""), ev.get("input", {})),
                        )
                        reasoning_steps_acc.append(f"🔧 {_format_tool_label(ev.get('name', ''), ev.get('input', {}))}")
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
        # その他のエラー（ツール失敗、APIエラー等）→ セッションは消さない
        return False
    return False


def _run_cli_in_thread(
    content: str,
    system_prompt: str,
    mcp_config_path: str,
    room_id: str,
    event_queue: thread_queue.Queue,
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

    claude_cmd, cli_js = _resolve_claude_cli()
    if not claude_cmd:
        event_queue.put({"type": "error", "message": "claude CLI が見つかりません。npm i -g @anthropic-ai/claude-code でインストールしてください。"})
        event_queue.put(_SENTINEL)
        return

    # CLAUDECODE: Claude Code の再帰起動を防止
    # ANTHROPIC_API_KEY: CLIがMax planサブスク（定額）ではなくAPI従量課金を使うのを防止
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "ANTHROPIC_API_KEY")}
    env["DAN_SESSION_ID"] = room_id
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
            project_id=project_id,
            run_id=run_id,
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
            cmd = _build_cli_cmd(claude_cmd, cli_js, mcp_config_path, launch_system_prompt, resume_session_id=None)
            _cli_debug(f"CLI attempt 2 (fresh session, prompt len={len(content)})")

            result_data = _run_cli_process(
                cmd,
                launch_content,
                env,
                room_id,
                event_queue,
                project_id=project_id,
                cwd=cwd,
                run_id=run_id,
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
                cli_saved = _save_ai_message_sync(
                    room_id, text, reasoning, reasoning_full_list
                )
                _cli_debug(f"AI message DB save: cli_saved={cli_saved}, text_len={len(text)}")

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
            })
            if project_id:
                _save_execution_event_sync(
                    room_id,
                    "done",
                    project_id=project_id,
                    run_id=run_id,
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
            )
            _save_execution_event_sync(
                room_id,
                "done",
                project_id=project_id,
                run_id=run_id,
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
                )
            done_content = "cancelled" if was_cancelled else "interrupted"
            _save_execution_event_sync(
                room_id,
                "done",
                project_id=project_id,
                run_id=run_id,
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
    if system_prompt is None:
        system_prompt = _build_system_prompt(
            project_title, project_description, project_status,
            user_messages=user_messages,
            latest_user_message=content,
            room_id=room_id,
        )
    if skill_injection:
        system_prompt += f"\n\n{skill_injection}"
    mcp_config_path = _build_mcp_config(room_id, user_id, credentials)
    resume_session_id = None if skip_resume else _load_session(room_id)

    # cancel_eventの参照を取得（旧スレッドが新スレッドのEventを消さないようにする）
    from app.services.cancellation import CancellationRegistry
    cancel_event = CancellationRegistry.get_event(room_id)

    # CLI を別スレッドで実行
    event_q = thread_queue.Queue()
    cli_thread = threading.Thread(
        target=_run_cli_in_thread,
        args=(
            content,
            system_prompt,
            mcp_config_path,
            room_id,
            event_q,
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
        yield event
