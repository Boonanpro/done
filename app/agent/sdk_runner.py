"""
SDK Runner - プロジェクト実行をClaude Agent SDK (Maxプラン) で行う

通常のAgentRunner (runner.py) は変更しない。
プロジェクトチャットでのみ、このSDKランナーを使う。

Windows + uvicorn の制約:
  uvicorn --reload は SelectorEventLoop を使うため、サブプロセス生成ができない。
  SDK は内部で asyncio.create_subprocess_exec を使うので ProactorEventLoop が必要。
  → SDK呼び出しを別スレッドで実行し、そのスレッド内で ProactorEventLoop を使う。
"""

import asyncio
import json
import logging
import sys
import threading
import warnings
import queue as thread_queue
from pathlib import Path
from typing import AsyncIterator, Optional, Dict, Any

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
)
from claude_agent_sdk.types import StreamEvent

logger = logging.getLogger(__name__)

# SDKセッション管理: インメモリキャッシュ + DB永続化
_sdk_sessions: Dict[str, str] = {}

PROJECT_ROOT = Path(__file__).parent.parent.parent  # app/agent/ → app/ → D:\done\


def _load_sdk_session(room_id: str) -> Optional[str]:
    """DBからSDKセッションIDを読み込む（インメモリキャッシュ優先）"""
    if room_id in _sdk_sessions:
        return _sdk_sessions[room_id]
    try:
        from app.services.supabase_client import get_supabase_client
        sb = get_supabase_client().client
        result = sb.table("projects").select("metadata").eq("room_id", room_id).execute()
        if result.data and result.data[0].get("metadata"):
            session_id = result.data[0]["metadata"].get("sdk_session_id")
            if session_id:
                _sdk_sessions[room_id] = session_id
                return session_id
    except Exception as e:
        logger.warning(f"Failed to load SDK session for {room_id}: {e}")
    return None


def _save_sdk_session(room_id: str, session_id: str):
    """SDKセッションIDをDBに永続化"""
    _sdk_sessions[room_id] = session_id
    try:
        from app.services.supabase_client import get_supabase_client
        sb = get_supabase_client().client
        # metadata に sdk_session_id をマージ
        result = sb.table("projects").select("metadata").eq("room_id", room_id).execute()
        metadata = (result.data[0].get("metadata") or {}) if result.data else {}
        metadata["sdk_session_id"] = session_id
        sb.table("projects").update({"metadata": metadata}).eq("room_id", room_id).execute()
    except Exception as e:
        logger.warning(f"Failed to save SDK session for {room_id}: {e}")

_SENTINEL = object()  # キュー終了シグナル


def _build_system_prompt(title: str, description: str, status: str) -> str:
    """SDKエージェントのシステムプロンプトを組み立てる"""
    from app.agent.bootstrap_context import (
        get_core_prompt,
        load_all_bootstrap_files,
    )

    parts = [get_core_prompt()]

    # ブートストラップ（ペルソナ、ルール、記憶、ユーザー情報）
    bootstrap = load_all_bootstrap_files()
    if bootstrap:
        parts.append(bootstrap)

    # プロジェクトコンテキスト
    project_ctx = _SDK_PROJECT_CONTEXT_TEMPLATE.format(
        title=title,
        description=description or "(なし)",
        status=status,
    )
    parts.append(project_ctx)

    return "\n\n".join(parts)


_SDK_PROJECT_CONTEXT_TEMPLATE = """## プロジェクトモード

これはプロジェクト専用チャットです。通常の雑談ではありません。

### プロジェクト情報
- タイトル: {title}
- 説明: {description}
- ステータス: {status}

### プロジェクトモードの行動指針
1. 仮説を立てて検証する
2. 実行可能な具体案を優先する
3. Green/Yellow/Red に従い自律実行する
4. 障害時はツールで自己解決を試みる
5. Red操作は必ず確認してから実行する
"""


def _build_sdk_options(
    room_id: str,
    user_id: str,
    system_prompt: str,
    credentials: Optional[Dict] = None,
) -> ClaudeAgentOptions:
    """SDK設定を構築する"""

    import os
    env = {**os.environ}
    env.update({
        "DAN_USER_ID": user_id,
        "DAN_SESSION_ID": room_id,
        "DAN_CREDENTIALS": json.dumps(credentials or {}),
        "ANTHROPIC_API_KEY": "",
        "CLAUDECODE": "",
    })

    # MCP Server設定をJSONファイルとして書き出す
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

    # 既存SDKセッションがあれば再開（DB永続化対応）
    resume_id = _load_sdk_session(room_id)

    return ClaudeAgentOptions(
        model="opus",
        system_prompt=system_prompt,
        mcp_servers=str(mcp_config_path),
        permission_mode="bypassPermissions",
        max_turns=200,
        cwd=str(PROJECT_ROOT),
        env=env,
        include_partial_messages=True,
        resume=resume_id,
        max_buffer_size=50 * 1024 * 1024,  # 50MB (default 1MB)
    )


def _sdk_debug(msg: str):
    """SDK thread用ファイルデバッグログ"""
    from datetime import datetime
    from pathlib import Path
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    with open(Path("D:/done/sdk_runner_debug.log"), "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
        f.flush()


def _run_sdk_in_thread(
    content: str,
    options: ClaudeAgentOptions,
    event_queue: thread_queue.Queue,
    room_id: str,
):
    """
    別スレッドでSDK queryを実行する。
    Windows の SelectorEventLoop ではサブプロセスが作れないため、
    このスレッド内で ProactorEventLoop を新たに作成して使う。
    """
    _sdk_debug(f"Thread started for room {room_id}")

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _query():
        final_text_parts = []
        msg_count = 0
        try:
            _sdk_debug("Starting query()...")
            async for message in query(prompt=content, options=options):
                msg_count += 1
                if isinstance(message, StreamEvent):
                    event_data = message.event
                    if event_data.get("type") == "content_block_delta":
                        delta = event_data.get("delta", {})
                        if delta.get("type") == "text_delta":
                            event_queue.put({"type": "text_delta", "text": delta.get("text", "")})
                        elif delta.get("type") == "thinking_delta":
                            event_queue.put({"type": "reasoning", "text": delta.get("thinking", "")})

                elif isinstance(message, AssistantMessage):
                    _sdk_debug(f"AssistantMessage: {len(message.content)} blocks")
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            final_text_parts.append(block.text)
                            event_queue.put({"type": "text", "text": block.text})
                        elif isinstance(block, ThinkingBlock):
                            event_queue.put({"type": "reasoning", "text": block.thinking})
                        elif isinstance(block, ToolUseBlock):
                            event_queue.put({
                                "type": "tool_use",
                                "name": block.name,
                                "input": block.input,
                            })

                elif isinstance(message, ResultMessage):
                    _sdk_debug(
                        f"ResultMessage: cost={message.total_cost_usd}, "
                        f"turns={message.num_turns}, error={message.is_error}, "
                        f"text_len={len(message.result or '')}"
                    )
                    if message.session_id:
                        _save_sdk_session(room_id, message.session_id)

                    event_queue.put({
                        "type": "result",
                        "text": message.result or "\n".join(final_text_parts),
                        "session_id": message.session_id,
                        "cost": message.total_cost_usd,
                        "turns": message.num_turns,
                        "duration_ms": message.duration_ms,
                        "is_error": message.is_error,
                    })
                else:
                    _sdk_debug(f"Unknown message type: {type(message).__name__}")

            _sdk_debug(f"query loop ended normally. msg_count={msg_count}")

        except Exception as e:
            import traceback
            error_detail = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            _sdk_debug(f"ERROR: {error_detail}")
            event_queue.put({"type": "error", "message": error_detail})
        finally:
            _sdk_debug(f"Sending sentinel. msg_count={msg_count}")
            event_queue.put(_SENTINEL)

    try:
        loop.run_until_complete(_query())
    except Exception as e:
        _sdk_debug(f"loop.run_until_complete EXCEPTION: {e}")
        event_queue.put({"type": "error", "message": str(e)})
        event_queue.put(_SENTINEL)
    finally:
        _sdk_debug("Thread ending, closing loop")
        loop.close()


async def process_message_sdk(
    room_id: str,
    user_id: str,
    content: str,
    project_title: str = "",
    project_description: str = "",
    project_status: str = "in_progress",
    credentials: Optional[Dict] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """
    Agent SDK経由でメッセージを処理し、SSE互換イベントを返す。

    SDK は別スレッドで実行（Windows の SelectorEventLoop 制約を回避）。
    イベントはスレッドセーフなキュー経由で受け取る。
    """
    warnings.warn(
        "app.agent.sdk_runner.process_message_sdk is deprecated. "
        "Use CLI runner entrypoints for active chat/runtime flows.",
        DeprecationWarning,
        stacklevel=2,
    )
    system_prompt = _build_system_prompt(
        project_title, project_description, project_status,
    )
    options = _build_sdk_options(room_id, user_id, system_prompt, credentials)

    event_q: thread_queue.Queue = thread_queue.Queue()

    # SDK を別スレッドで実行
    sdk_thread = threading.Thread(
        target=_run_sdk_in_thread,
        args=(content, options, event_q, room_id),
        daemon=True,
    )
    sdk_thread.start()

    # キューからイベントを非同期に読み出してyield
    loop = asyncio.get_running_loop()
    idle_seconds = 0
    while True:
        try:
            # タイムアウト付きでキューを読む（10秒ごとに活動チェック）
            event = await loop.run_in_executor(
                None, lambda: event_q.get(timeout=10)
            )
        except Exception:
            # queue.Empty (timeout) - check if thread is still alive
            idle_seconds += 10
            if not sdk_thread.is_alive():
                _sdk_debug(f"SDK thread died unexpectedly after {idle_seconds}s idle")
                yield {"type": "error", "message": "SDK thread terminated unexpectedly"}
                break
            if idle_seconds >= 3600:  # 60 minute safety net (max_turns handles normal termination)
                _sdk_debug(f"SDK timeout after {idle_seconds}s")
                yield {"type": "error", "message": f"SDK timeout after {idle_seconds}s"}
                break
            continue

        idle_seconds = 0
        if event is _SENTINEL:
            break
        yield event
