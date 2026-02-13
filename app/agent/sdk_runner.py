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

# SDKセッション管理: room_id → SDK session_id
_sdk_sessions: Dict[str, str] = {}

PROJECT_ROOT = Path(__file__).parent.parent.parent  # app/agent/ → app/ → D:\done\

_SENTINEL = object()  # キュー終了シグナル


def _build_system_prompt(title: str, description: str, status: str) -> str:
    """SDKエージェントのシステムプロンプトを組み立てる"""
    from app.agent.v2.runner import (
        get_core_prompt,
        load_all_bootstrap_files,
        PROJECT_CONTEXT_TEMPLATE,
    )

    parts = [get_core_prompt()]

    # ブートストラップ（ペルソナ、ルール、記憶、ユーザー情報）
    bootstrap = load_all_bootstrap_files()
    if bootstrap:
        parts.append(bootstrap)

    # プロジェクトコンテキスト
    project_ctx = PROJECT_CONTEXT_TEMPLATE.format(
        title=title,
        description=description or "(なし)",
        status=status,
    )
    parts.append(project_ctx)

    return "\n\n".join(parts)


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

    # 既存SDKセッションがあれば再開
    resume_id = _sdk_sessions.get(room_id)

    return ClaudeAgentOptions(
        model="opus",
        system_prompt=system_prompt,
        mcp_servers=str(mcp_config_path),
        permission_mode="bypassPermissions",
        max_turns=30,
        cwd=str(PROJECT_ROOT),
        env=env,
        include_partial_messages=True,
        resume=resume_id,
    )


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
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _query():
        final_text_parts = []
        try:
            async for message in query(prompt=content, options=options):
                if isinstance(message, StreamEvent):
                    event_data = message.event
                    if event_data.get("type") == "content_block_delta":
                        delta = event_data.get("delta", {})
                        if delta.get("type") == "text_delta":
                            event_queue.put({"type": "text_delta", "text": delta.get("text", "")})
                        elif delta.get("type") == "thinking_delta":
                            event_queue.put({"type": "reasoning", "text": delta.get("thinking", "")})

                elif isinstance(message, AssistantMessage):
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
                    if message.session_id:
                        _sdk_sessions[room_id] = message.session_id

                    event_queue.put({
                        "type": "result",
                        "text": message.result or "\n".join(final_text_parts),
                        "session_id": message.session_id,
                        "cost": message.total_cost_usd,
                        "turns": message.num_turns,
                        "duration_ms": message.duration_ms,
                        "is_error": message.is_error,
                    })

        except Exception as e:
            import traceback
            error_detail = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            logger.exception(f"[SDKRunner] Error for room {room_id}: {error_detail}")
            event_queue.put({"type": "error", "message": error_detail})
        finally:
            event_queue.put(_SENTINEL)

    try:
        loop.run_until_complete(_query())
    finally:
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
    while True:
        # ブロッキングの queue.get() を run_in_executor で非同期化
        event = await loop.run_in_executor(None, event_q.get)
        if event is _SENTINEL:
            break
        yield event
