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
import queue as thread_queue
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


def _build_system_prompt(title: str, description: str, status: str, user_messages: str = "") -> str:
    """事業部（CLIエージェント）のシステムプロンプトを組み立てる

    秘書部のRULES.md等は読み込まない。
    CLIは元々高品質な判断力を持つので、最小限の指示だけ追加する。

    status が "planning" の場合はリーダー常駐プロンプトを使用する。
    """
    from app.agent.v2.runner import load_bootstrap_file

    # planning ステータス → リーダー常駐プロンプトを使用
    if status == "planning":
        from app.agent.v2.team.prompts import get_leader_resident_prompt
        leader_prompt = get_leader_resident_prompt(title, description, user_messages)

        parts = [leader_prompt]

        # ユーザー情報のみ読み込む（個人情報の判断に必要）
        user = load_bootstrap_file("USER.md")
        if user:
            parts.append(f"## ユーザー情報\n\n{user}")

        # ペルソナ（2行のみ）
        soul = load_bootstrap_file("SOUL.md")
        if soul:
            parts.append(f"## ペルソナ\n\n{soul}")

        return "\n\n".join(parts)

    # 通常の事業部プロンプト
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
- コードベース: D:/done（ファイル操作は絶対パスで指定すること）

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
- なければユーザーに聞く → save_credentials で保存

### チャットAPI テスト
- 接続テストには `POST /api/v1/chat/rooms/{{room_id}}/dry-run` を使うこと
- dry-run は認証・ルーム検証のみ行い、DBに書き込まない
- 本番の送信エンドポイント (`/messages`, `/dan/messages/stream`) をテスト目的で使わないこと"""


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

    for block in blocks:
        block_type = block.get("type", "")

        if block_type == "tool_use":
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
    is_planning: bool = False,
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
    ])

    # planning モード: リーダーが自分で作業せず MCP call_researcher/call_critic に委譲するよう
    # CLI 内蔵の作業ツールを禁止する（公式 Agent Team の最小権限原則）
    if is_planning:
        cmd.extend([
            "--disallowedTools", "WebSearch,WebFetch,Task,TodoWrite,TodoRead",
        ])

    if resume_session_id:
        cmd.extend(["--resume", resume_session_id])

    return cmd


def _run_cli_process(
    cmd: list[str],
    content: str,
    env: dict,
    room_id: str,
    event_queue: thread_queue.Queue,
) -> Optional[dict]:
    """
    CLIプロセスを1回実行し、イベントをキューに送る。

    Returns:
        result データ（リトライ判定用）。プロセスが結果を返さなかった場合は None。
    """
    session_id_captured = None
    final_text_parts = []
    result_data = None

    # --include-partial-messages による重複を防ぐ
    # メッセージIDごとに「処理済みブロックのスナップショット」を記録
    # ブロック数だけでなく内容変更も検出するため、各ブロックのハッシュを保持する
    processed_block_snapshots: Dict[str, list] = {}

    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(CLI_WORKSPACE),
        env=env,
        encoding="utf-8",
        errors="replace",
    )

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

    for line in process.stdout:
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
                _cli_debug(f"  Event: type={ev['type']}, text_len={len(ev.get('text', ''))}")
                if ev["type"] == "text":
                    final_text_parts.append(ev["text"])
                event_queue.put(ev)

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
            }

            _cli_debug(
                f"ResultMessage: cost={cost_usd}, turns={num_turns}, "
                f"error={is_error}, text_len={len(result_text or '')}, "
                f"errors={errors}"
            )

        elif msg_type == "error":
            error_msg = data.get("error", {})
            error_text = error_msg.get("message", str(error_msg)) if isinstance(error_msg, dict) else str(error_msg)
            _cli_debug(f"CLI error event: {error_text[:200]}")
            event_queue.put({"type": "error", "message": error_text})

        elif msg_type == "system":
            session_id_captured = data.get("session_id", session_id_captured)
            _cli_debug(f"System message: session_id={session_id_captured}")

    return_code = process.wait(timeout=30)
    _cli_debug(f"CLI process exited with code {return_code}")

    if return_code != 0 and result_data is None:
        # stderrはドレインスレッドが読んでいるので、ここではログのみ
        event_queue.put({"type": "error", "message": f"CLI exited with code {return_code}"})

    return result_data


def _is_resume_error(result_data: Optional[dict]) -> bool:
    """resultがセッション再開失敗かどうかを判定する"""
    if not result_data:
        return False
    if not result_data.get("is_error"):
        return False
    errors = result_data.get("errors", [])
    return any("No conversation found" in e for e in errors)


def _run_cli_in_thread(
    content: str,
    system_prompt: str,
    mcp_config_path: str,
    room_id: str,
    event_queue: thread_queue.Queue,
    resume_session_id: Optional[str] = None,
    is_planning: bool = False,
):
    """
    別スレッドでCLI subprocessを実行する。
    JSON streamを1行ずつ読み、イベントをキューに入れる。

    セッション再開が失敗した場合（セッションが見つからない等）、
    保存済みセッションIDをクリアして新規会話として自動リトライする。
    """
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

    try:
        # 1回目: セッション再開を試みる
        cmd = _build_cli_cmd(claude_cmd, cli_js, mcp_config_path, system_prompt, resume_session_id, is_planning=is_planning)
        _cli_debug(f"CLI attempt 1 (resume={resume_session_id is not None}, prompt len={len(content)})")

        result_data = _run_cli_process(cmd, content, env, room_id, event_queue)

        # セッション再開失敗 → セッションをクリアしてリトライ
        if _is_resume_error(result_data) and resume_session_id:
            errors = result_data.get("errors", [])
            _cli_debug(f"Resume failed: {errors}. Clearing session and retrying without resume.")

            # 古いセッションIDをクリア
            _cli_sessions.pop(room_id, None)
            try:
                from app.services.supabase_client import get_supabase_client
                sb = get_supabase_client().client
                proj = sb.table("projects").select("id, metadata").eq("room_id", room_id).execute()
                if proj.data:
                    meta = proj.data[0].get("metadata") or {}
                    meta.pop("cli_session_id", None)
                    sb.table("projects").update({"metadata": meta}).eq("id", proj.data[0]["id"]).execute()
            except Exception as e:
                _cli_debug(f"Failed to clear session from DB: {e}")

            # 2回目: 新規会話として実行
            cmd = _build_cli_cmd(claude_cmd, cli_js, mcp_config_path, system_prompt, resume_session_id=None, is_planning=is_planning)
            _cli_debug(f"CLI attempt 2 (fresh session, prompt len={len(content)})")

            result_data = _run_cli_process(cmd, content, env, room_id, event_queue)

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

            # エラー時はerrorsの内容をテキストに含める
            text = result_text or "\n".join(final_text_parts)
            if is_error and not text and errors:
                text = f"CLIエラー: {'; '.join(errors)}"

            event_queue.put({
                "type": "result",
                "text": text,
                "session_id": session_id,
                "cost": result_data.get("cost", 0),
                "turns": result_data.get("num_turns", 0),
                "duration_ms": result_data.get("duration_ms", 0),
                "is_error": is_error,
            })

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
    system_prompt: Optional[str] = None,
    user_messages: str = "",
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
        )
    mcp_config_path = _build_mcp_config(room_id, user_id, credentials)
    resume_session_id = _load_session(room_id)

    event_q: thread_queue.Queue = thread_queue.Queue()

    is_planning = project_status == "planning"

    # CLI を別スレッドで実行
    cli_thread = threading.Thread(
        target=_run_cli_in_thread,
        args=(content, system_prompt, mcp_config_path, room_id, event_q, resume_session_id, is_planning),
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
