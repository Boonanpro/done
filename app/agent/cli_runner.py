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
import sys
import threading
import queue as thread_queue
from pathlib import Path
from typing import AsyncIterator, Optional, Dict, Any

logger = logging.getLogger(__name__)

# セッション管理: インメモリキャッシュ + DB永続化
_cli_sessions: Dict[str, str] = {}

PROJECT_ROOT = Path(__file__).parent.parent.parent  # app/agent/ → app/ → D:\done\

_SENTINEL = object()  # キュー終了シグナル


def _load_session(room_id: str) -> Optional[str]:
    """DBからCLIセッションIDを読み込む（インメモリキャッシュ優先）"""
    if room_id in _cli_sessions:
        return _cli_sessions[room_id]
    try:
        from app.services.supabase_client import get_supabase_client
        sb = get_supabase_client().client
        result = sb.table("projects").select("metadata").eq("room_id", room_id).execute()
        if result.data and result.data[0].get("metadata"):
            session_id = result.data[0]["metadata"].get("cli_session_id")
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
        sb = get_supabase_client().client
        result = sb.table("projects").select("metadata").eq("room_id", room_id).execute()
        metadata = (result.data[0].get("metadata") or {}) if result.data else {}
        metadata["cli_session_id"] = session_id
        sb.table("projects").update({"metadata": metadata}).eq("room_id", room_id).execute()
    except Exception as e:
        logger.warning(f"Failed to save CLI session for {room_id}: {e}")


def _build_system_prompt(title: str, description: str, status: str) -> str:
    """事業部（CLIエージェント）のシステムプロンプトを組み立てる

    秘書部のRULES.md等は読み込まない。
    CLIは元々高品質な判断力を持つので、最小限の指示だけ追加する。
    """
    from app.agent.v2.runner import load_bootstrap_file

    parts = ["You are Dan's business division. You plan, research, and execute projects."]

    # ユーザー情報のみ読み込む（個人情報の判断に必要）
    user = load_bootstrap_file("USER.md")
    if user:
        parts.append(f"## ユーザー情報\n\n{user}")

    # ペルソナ（2行のみ）
    soul = load_bootstrap_file("SOUL.md")
    if soul:
        parts.append(f"## ペルソナ\n\n{soul}")

    # 事業部向けの最小限プロジェクトコンテキスト
    parts.append(_CLI_PROJECT_TEMPLATE.format(
        title=title,
        description=description or "(なし)",
        status=status,
    ))

    return "\n\n".join(parts)


# 事業部向けプロジェクトコンテキスト（最小限）
_CLI_PROJECT_TEMPLATE = """## プロジェクト

- タイトル: {title}
- 説明: {description}
- ステータス: {status}

### 安全確認（実行前にユーザーに確認が必要な操作）
- お金が動く操作（購入、送金、契約）
- 個人情報の入力（知らなければ必ず聞く。推測禁止）
- 外部への送信（メール、メッセージ、SNS投稿）
- アカウント削除・パスワード変更

### ブラウザ操作
- @e参照は直前の操作結果でのみ有効。ページ遷移後は使わない
- 操作後はURL・タイトル・見出しの変化で結果を確認する
- 証拠なく「完了しました」と報告しない
- ローディング中ならbrowser_screenshotで再確認

### 認証情報
- ログインが必要 → まず get_credentials で保存済みか確認
- なければユーザーに聞く → save_credentials で保存"""


def _build_mcp_config(room_id: str, user_id: str, credentials: Optional[Dict] = None) -> str:
    """MCP設定ファイルを書き出してパスを返す"""
    mcp_json = {
        "mcpServers": {
            "dan-tools": {
                "command": "python",
                "args": [str(PROJECT_ROOT / "app" / "mcp_server.py")],
                "env": {
                    "DAN_USER_ID": user_id,
                    "DAN_SESSION_ID": room_id,
                    "DAN_CREDENTIALS": json.dumps(credentials or {}),
                },
            }
        }
    }
    mcp_config_dir = PROJECT_ROOT / ".claude"
    mcp_config_dir.mkdir(parents=True, exist_ok=True)
    mcp_config_path = mcp_config_dir / "mcp_sdk.json"
    mcp_config_path.write_text(json.dumps(mcp_json, indent=2), encoding="utf-8")
    return str(mcp_config_path)


def _cli_debug(msg: str):
    """CLI thread用ファイルデバッグログ"""
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    with open(PROJECT_ROOT / "cli_runner_debug.log", "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
        f.flush()


def _classify_content_blocks(blocks: list) -> list[Dict[str, Any]]:
    """
    assistantメッセージのcontent blocksを分類する。

    Returns:
        list of events: {"type": "tool_use"|"reasoning"|"text", ...}
    """
    events = []
    has_tool_use = False

    for block in blocks:
        block_type = block.get("type", "")

        if block_type == "tool_use":
            has_tool_use = True
            events.append({
                "type": "tool_use",
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
                events.append({
                    "type": "text",
                    "text": text,
                    "_pending": True,  # tool_useと組の場合は reasoning扱い
                })
        elif block_type == "server_tool_use":
            # web_search等のサーバー側ツール
            events.append({
                "type": "tool_use",
                "name": block.get("name", "server_tool"),
                "input": block.get("input", {}),
            })

    # text + tool_use が同じメッセージにある場合、textは内部思考扱い
    if has_tool_use:
        for ev in events:
            if ev.get("_pending"):
                ev["type"] = "reasoning"
                del ev["_pending"]
    else:
        for ev in events:
            if "_pending" in ev:
                del ev["_pending"]

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


def _run_cli_in_thread(
    content: str,
    system_prompt: str,
    mcp_config_path: str,
    room_id: str,
    event_queue: thread_queue.Queue,
    resume_session_id: Optional[str] = None,
):
    """
    別スレッドでCLI subprocessを実行する。
    JSON streamを1行ずつ読み、イベントをキューに入れる。
    """
    _cli_debug(f"Thread started for room {room_id}")

    # CLIコマンド構築
    # Windows では claude.CMD (バッチファイル) 経由だと日本語や特殊文字が壊れるため、
    # node + cli.js を直接呼び出す
    claude_cmd, cli_js = _resolve_claude_cli()
    if not claude_cmd:
        event_queue.put({"type": "error", "message": "claude CLI が見つかりません。npm i -g @anthropic-ai/claude-code でインストールしてください。"})
        event_queue.put(_SENTINEL)
        return

    if cli_js:
        # node で直接実行 (.CMD を経由しない)
        cmd = [claude_cmd, cli_js]
    else:
        # claude.exe など .CMD 以外ならそのまま使う
        cmd = [claude_cmd]

    cmd.extend([
        "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
        "--model", "opus",
        "--max-turns", "200",
        "--mcp-config", mcp_config_path,
    ])

    # システムプロンプト
    cmd.extend(["--system-prompt", system_prompt])

    # セッション再開
    if resume_session_id:
        cmd.extend(["--resume", resume_session_id])

    # ユーザーのメッセージは stdin 経由で渡す（コマンドライン文字数制限を回避）

    # 環境変数: CLAUDECODE を除外
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["DAN_SESSION_ID"] = room_id

    _cli_debug(f"CLI command: {cmd[0]}{'...' + os.path.basename(cmd[1]) if cli_js else ''} (prompt len={len(content)})")

    session_id_captured = None
    final_text_parts = []

    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(PROJECT_ROOT),
            env=env,
            encoding="utf-8",
            errors="replace",
        )

        _cli_debug(f"CLI process started: PID={process.pid}")

        # ユーザーのメッセージを stdin 経由で送信して閉じる
        try:
            process.stdin.write(content)
            process.stdin.close()
        except Exception as e:
            _cli_debug(f"stdin write error: {e}")

        # stdoutを1行ずつ読む
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                _cli_debug(f"Non-JSON line: {line[:100]}")
                continue

            msg_type = data.get("type", "")

            if msg_type == "assistant":
                # assistantメッセージ: content blocksを分類
                message_data = data.get("message", {})
                blocks = message_data.get("content", [])
                classified = _classify_content_blocks(blocks)

                for ev in classified:
                    if ev["type"] == "text":
                        final_text_parts.append(ev["text"])
                    event_queue.put(ev)

            elif msg_type == "result":
                # 最終結果
                session_id_captured = data.get("session_id")
                cost_usd = data.get("cost_usd", 0)
                duration_ms = data.get("duration_ms", 0)
                num_turns = data.get("num_turns", 0)
                is_error = data.get("is_error", False)
                result_text = data.get("result", "")

                if session_id_captured:
                    _save_session(room_id, session_id_captured)

                event_queue.put({
                    "type": "result",
                    "text": result_text or "\n".join(final_text_parts),
                    "session_id": session_id_captured,
                    "cost": cost_usd,
                    "turns": num_turns,
                    "duration_ms": duration_ms,
                    "is_error": is_error,
                })

                _cli_debug(
                    f"ResultMessage: cost={cost_usd}, turns={num_turns}, "
                    f"error={is_error}, text_len={len(result_text or '')}"
                )

            elif msg_type == "error":
                error_msg = data.get("error", {})
                error_text = error_msg.get("message", str(error_msg)) if isinstance(error_msg, dict) else str(error_msg)
                _cli_debug(f"CLI error event: {error_text[:200]}")
                event_queue.put({"type": "error", "message": error_text})

            elif msg_type == "system":
                # システムメッセージ（セッションID等）
                session_id_captured = data.get("session_id", session_id_captured)
                _cli_debug(f"System message: session_id={session_id_captured}")

            # その他 (tool_result, content_block_delta等) はスキップ

        # プロセス終了を待つ
        return_code = process.wait(timeout=30)
        _cli_debug(f"CLI process exited with code {return_code}")

        if return_code != 0:
            stderr_output = process.stderr.read() if process.stderr else ""
            if stderr_output:
                _cli_debug(f"CLI stderr: {stderr_output[:500]}")
                # resultイベントがまだ送られていない場合のみエラーを出す
                event_queue.put({"type": "error", "message": f"CLI exited with code {return_code}: {stderr_output[:300]}"})

    except Exception as e:
        import traceback
        error_detail = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        _cli_debug(f"ERROR: {error_detail}")
        event_queue.put({"type": "error", "message": error_detail})
    finally:
        _cli_debug("Sending sentinel")
        event_queue.put(_SENTINEL)


async def process_message_cli(
    room_id: str,
    user_id: str,
    content: str,
    project_title: str = "",
    project_description: str = "",
    project_status: str = "in_progress",
    credentials: Optional[Dict] = None,
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
    """
    system_prompt = _build_system_prompt(
        project_title, project_description, project_status,
    )
    mcp_config_path = _build_mcp_config(room_id, user_id, credentials)
    resume_session_id = _load_session(room_id)

    event_q: thread_queue.Queue = thread_queue.Queue()

    # CLI を別スレッドで実行
    cli_thread = threading.Thread(
        target=_run_cli_in_thread,
        args=(content, system_prompt, mcp_config_path, room_id, event_q, resume_session_id),
        daemon=True,
    )
    cli_thread.start()

    # キューからイベントを非同期に読み出してyield
    loop = asyncio.get_running_loop()
    idle_seconds = 0
    while True:
        try:
            event = await loop.run_in_executor(
                None, lambda: event_q.get(timeout=10)
            )
        except Exception:
            # queue.Empty (timeout)
            idle_seconds += 10
            if not cli_thread.is_alive():
                _cli_debug(f"CLI thread died unexpectedly after {idle_seconds}s idle")
                yield {"type": "error", "message": "CLI process terminated unexpectedly"}
                break
            if idle_seconds >= 3600:  # 60 minute safety net
                _cli_debug(f"CLI timeout after {idle_seconds}s")
                yield {"type": "error", "message": f"CLI timeout after {idle_seconds}s"}
                break
            continue

        idle_seconds = 0
        if event is _SENTINEL:
            break
        yield event
