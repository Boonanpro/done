"""
SimpleRunner - OpenClaw-style Simple Agent Runner

シンプルなLLM + ツール実行ループ。
複雑なオーケストレーション層を排除。
"""

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Awaitable
from dataclasses import dataclass, field

import anthropic

from app.config import settings
from app.agent.v3.tools import ALL_TOOLS, execute_tool

logger = logging.getLogger(__name__)

# 最大ツール実行ループ回数（安全弁）
MAX_TOOL_LOOPS = 50

# セッションストア（メモリ内キャッシュ）
_session_store: Dict[str, "SimpleSession"] = {}


@dataclass
class Message:
    """メッセージ"""
    role: str  # "user" or "assistant"
    content: Any  # str or list of content blocks


@dataclass
class SimpleSession:
    """シンプルなセッション"""
    session_id: str
    user_id: str = ""
    messages: List[Dict[str, Any]] = field(default_factory=list)

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: Any):
        # content blockをシリアライズ可能な形式に変換
        if hasattr(content, '__iter__') and not isinstance(content, (str, dict)):
            serialized = []
            for block in content:
                if hasattr(block, 'type'):
                    if block.type == "text":
                        serialized.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        serialized.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })
                else:
                    serialized.append(block)
            content = serialized
        self.messages.append({"role": "assistant", "content": content})

    def add_tool_result(self, tool_use_id: str, result: str):
        self.messages.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result,
                }
            ]
        })


class SimpleRunner:
    """
    OpenClaw風シンプルランナー

    LLM呼び出し → ツール実行 → 結果返却 のシンプルなループ
    """

    def __init__(
        self,
        session: Optional[SimpleSession] = None,
        on_tool_start: Optional[Callable[[str, Dict], None]] = None,
        on_tool_end: Optional[Callable[[str, Dict], None]] = None,
        on_thinking: Optional[Callable[[str], None]] = None,
    ):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.session = session or SimpleSession(session_id="default")
        self.on_tool_start = on_tool_start
        self.on_tool_end = on_tool_end
        self.on_thinking = on_thinking

        # スキルシステムからの追加コンテキスト（後で統合）
        self.skill_context: Optional[str] = None

    def _build_system_prompt(self) -> str:
        """システムプロンプトを構築"""
        base_prompt = """あなたは「ダン」という名前のAIアシスタントです。
ユーザーのタスクを実行するために、利用可能なツールを使って作業を進めます。

## 行動原則

1. **まず行動**: 質問する前にツールを使って情報を集める
2. **シンプルに**: 最小限のステップでタスクを完了する
3. **自己解決**: エラーが出たら自分で対処を試みる

## ツールの使い方

- bash: あらゆるシェルコマンドを実行可能
- read_file / write_file / edit_file: ファイル操作
- browser: Webサイトの閲覧・操作
- tavily_search: Web検索
- respond_to_user: ユーザーへの回答（タスク完了時に必ず使用）

## 重要

- タスクが完了したら、必ず respond_to_user で結果を報告すること
- ツールの実行結果を確認してから次のアクションを決めること
- 不明な点があれば、まずツールで調べてから判断すること
"""

        if self.skill_context:
            base_prompt += f"\n\n## スキル情報\n\n{self.skill_context}"

        return base_prompt

    async def process_message(self, user_message: str) -> Dict[str, Any]:
        """
        ユーザーメッセージを処理してレスポンスを返す

        Returns:
            {"response": str, "error": str?, "cancelled": bool?}
        """
        # キャンセルチェック用
        from app.services.cancellation import CancellationRegistry

        # ユーザーメッセージを追加
        self.session.add_user_message(user_message)

        # ツール実行ループ
        loop_count = 0
        final_response = ""

        while loop_count < MAX_TOOL_LOOPS:
            # キャンセルチェック
            if CancellationRegistry.is_cancelled(self.session.session_id):
                logger.info(f"[Cancelled] Session {self.session.session_id}")
                return {"response": "", "cancelled": True}

            loop_count += 1
            logger.info(f"[Loop {loop_count}] Calling LLM...")

            # LLM呼び出し
            try:
                response = self._call_llm()
            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                return {"response": "", "error": str(e)}

            # レスポンスを処理
            tool_uses = []
            text_content = ""

            for block in response.content:
                if block.type == "text":
                    text_content += block.text
                    if self.on_thinking and block.text:
                        self.on_thinking(block.text)
                elif block.type == "tool_use":
                    tool_uses.append(block)

            # アシスタントメッセージを追加
            self.session.add_assistant_message(response.content)

            # ツール使用がない場合は終了
            if not tool_uses:
                final_response = text_content
                break

            # ツールを実行
            for tool_use in tool_uses:
                # キャンセルチェック
                if CancellationRegistry.is_cancelled(self.session.session_id):
                    return {"response": "", "cancelled": True}

                tool_name = tool_use.name
                tool_input = tool_use.input
                tool_use_id = tool_use.id

                logger.info(f"[Tool] {tool_name}: {json.dumps(tool_input, ensure_ascii=False)[:200]}")

                # コールバック
                if self.on_tool_start:
                    self.on_tool_start(tool_name, tool_input)

                # respond_to_userの場合は終了
                if tool_name == "respond_to_user":
                    final_response = tool_input.get("response", "")
                    # tool_resultを追加（APIの要件）
                    self.session.add_tool_result(tool_use_id, "Response delivered to user.")
                    if self.on_tool_end:
                        self.on_tool_end(tool_name, {"response": final_response})
                    return {"response": final_response}

                # ツール実行
                try:
                    result = await execute_tool(tool_name, tool_input)
                except Exception as e:
                    logger.error(f"Tool execution failed: {e}")
                    result = {"success": False, "error": str(e)}

                # コールバック
                if self.on_tool_end:
                    self.on_tool_end(tool_name, result)

                # 結果をセッションに追加
                result_str = json.dumps(result, ensure_ascii=False, default=str)
                self.session.add_tool_result(tool_use_id, result_str)

                logger.info(f"[Tool Result] {tool_name}: success={result.get('success')}")

        # ループ上限に達した場合
        if loop_count >= MAX_TOOL_LOOPS:
            logger.warning(f"Max tool loops reached: {MAX_TOOL_LOOPS}")
            final_response = "処理がタイムアウトしました。タスクが複雑すぎる可能性があります。"

        return {"response": final_response}

    def _call_llm(self) -> anthropic.types.Message:
        """LLMを呼び出す"""
        return self.client.messages.create(
            model="claude-haiku-4-5-20251001",  # Haiku 4.5: $1/$5 per MTok (67% cheaper than Sonnet)
            max_tokens=4096,
            system=self._build_system_prompt(),
            tools=ALL_TOOLS,
            messages=self.session.messages,
        )


# ============================================
# セッション管理
# ============================================

def get_or_create_session(session_id: str, user_id: str = "") -> SimpleSession:
    """セッションを取得または作成"""
    if session_id not in _session_store:
        _session_store[session_id] = SimpleSession(
            session_id=session_id,
            user_id=user_id,
        )
    return _session_store[session_id]


def clear_session(session_id: str):
    """セッションをクリア"""
    if session_id in _session_store:
        del _session_store[session_id]


# ============================================
# 便利関数
# ============================================

async def run_once(message: str) -> str:
    """単発でメッセージを処理"""
    runner = SimpleRunner()
    return await runner.process_message(message)


async def create_runner(
    session_id: str,
    user_id: str = "",
    on_reasoning_step: Optional[Callable[[str], Awaitable[None]]] = None,
) -> "SimpleRunner":
    """
    Runnerを作成する（chat_routes.pyとの互換性用）

    Args:
        session_id: セッションID
        user_id: ユーザーID
        on_reasoning_step: 推論ステップのコールバック（async）

    Returns:
        SimpleRunner インスタンス
    """
    session = get_or_create_session(session_id, user_id)

    # コールバックをラップ
    def on_thinking(text: str):
        if on_reasoning_step:
            import asyncio
            # 非同期コールバックを同期的に呼び出す
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(on_reasoning_step(text))
                else:
                    loop.run_until_complete(on_reasoning_step(text))
            except Exception:
                pass

    return SimpleRunner(
        session=session,
        on_thinking=on_thinking,
    )
