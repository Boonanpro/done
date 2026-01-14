"""
AgentRunner - 会話ループのメインロジック

Messages配列を維持しながらLLMと対話する。
状態遷移はLLMの出力から検出し、コードは追従するだけ。
ツール呼び出しはB方式（キーワード検出）で実行。
"""

import re
import logging
from typing import Optional, Dict, Any, Callable, Awaitable, List
from pathlib import Path

import anthropic

from app.agent.v2.session import Session, State, get_session_store
from app.agent.v2.tools import parse_tool_call, execute_tool, format_tool_result, SkillRegistry
from app.config import settings

logger = logging.getLogger(__name__)

# プロンプトディレクトリ
PROMPTS_DIR = Path(__file__).parent / "prompts"

# ツール実行の最大ループ回数（無限ループ防止）
MAX_TOOL_LOOPS = 3


def load_prompt(filename: str) -> str:
    """プロンプトファイルを読み込む"""
    filepath = PROMPTS_DIR / filename
    if filepath.exists():
        return filepath.read_text(encoding="utf-8")
    logger.warning(f"Prompt file not found: {filepath}")
    return ""


def load_system_prompt() -> str:
    """システムプロンプトを読み込む"""
    return load_prompt("system.md")


def load_state_prompt(state: State) -> str:
    """状態プロンプトを読み込む"""
    return load_prompt(f"states/{state.value}.md")


class AgentRunner:
    """
    会話ループを実行するクラス

    使い方:
        runner = AgentRunner(session)
        result = await runner.process_message("新幹線を予約したい")
    """

    def __init__(
        self,
        session: Session,
        on_reasoning_step: Optional[Callable[[str], Awaitable[None]]] = None,
    ):
        self.session = session
        self._on_reasoning_step = on_reasoning_step

        # LLMクライアント
        if settings.ANTHROPIC_API_KEY:
            self.llm_client = anthropic.AsyncAnthropic(
                api_key=settings.ANTHROPIC_API_KEY
            )
        else:
            self.llm_client = None
            logger.warning("ANTHROPIC_API_KEY not set")

    async def process_message(
        self,
        user_message: str,
        credentials: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        ユーザーメッセージを処理

        Args:
            user_message: ユーザーのメッセージ
            credentials: 認証情報（オプション）

        Returns:
            {
                "response": ユーザーへの応答,
                "state": 現在の状態,
                "reasoning_steps": 推論過程,
                "tool_results": ツール実行結果（あれば）,
            }
        """
        try:
            # 1. 推論ステップをクリア（新しいターン）
            self.session.clear_reasoning_steps()

            # 2. ユーザーメッセージを追加
            self.session.add_user_message(user_message)

            # 3. LLM呼び出し→ツール実行ループ
            tool_results = []
            for loop_count in range(MAX_TOOL_LOOPS + 1):
                # LLMを呼び出し
                llm_response = await self._call_llm()

                # レスポンスを解析
                parsed = self._parse_response(llm_response)

                # 状態遷移を検出・適用
                if parsed["new_state"]:
                    self.session.transition_to(parsed["new_state"])

                # アシスタントメッセージを追加
                self.session.add_assistant_message(llm_response)

                # ツール呼び出しを検出
                tool_call = parse_tool_call(llm_response)

                if not tool_call or loop_count >= MAX_TOOL_LOOPS:
                    # ツール呼び出しなし、または最大ループに達した
                    break

                # ツールを実行
                logger.info(f"Executing tool: {tool_call}")
                if self._on_reasoning_step:
                    await self._on_reasoning_step(
                        f"🔧 {tool_call['skill']} {tool_call['action']}..."
                    )

                result = await execute_tool(
                    tool_call=tool_call,
                    user_id=self.session.user_id,
                    credentials=credentials,
                )
                tool_results.append({
                    "tool": tool_call,
                    "result": result,
                })

                # 結果をMessagesに追加（userロールで追加してLLMに伝える）
                result_text = format_tool_result(
                    result, tool_call["skill"], tool_call["action"]
                )
                self.session.add_user_message(result_text)

                if self._on_reasoning_step:
                    status = "✅" if result.get("success") else "❌"
                    await self._on_reasoning_step(f"{status} ツール実行完了")

            # 4. セッションを保存
            store = get_session_store()
            await store.save(self.session)

            return {
                "response": parsed["user_response"],
                "state": self.session.current_state.value,
                "reasoning_steps": self.session.reasoning_steps,
                "tool_results": tool_results,
                "raw_response": llm_response,
            }

        except Exception as e:
            logger.exception(f"Error in process_message: {e}")
            return {
                "response": "申し訳ありません。エラーが発生しました。",
                "state": self.session.current_state.value,
                "reasoning_steps": self.session.reasoning_steps,
                "error": str(e),
            }

    def _build_system_prompt(self) -> str:
        """システムプロンプトを構築（Progressive Disclosure）"""
        # ベースのシステムプロンプト
        system = load_system_prompt()

        # 現在の状態のプロンプトを追加
        state_prompt = load_state_prompt(self.session.current_state)
        if state_prompt:
            system += f"\n\n---\n\n## 現在の状態: {self.session.current_state.value.upper()}\n\n{state_prompt}"

        # 利用可能なスキル情報を追加
        system += self._build_skills_prompt()

        return system

    def _build_skills_prompt(self) -> str:
        """利用可能なスキルのプロンプトを構築"""
        skills = SkillRegistry.list_all()
        if not skills:
            return ""

        lines = ["\n\n---\n\n## 利用可能なツール\n"]
        lines.append("ツールを使う時は以下の形式で宣言してください:\n")
        lines.append("```")
        lines.append("[TOOL: skill-name action]")
        lines.append("param1: value1")
        lines.append("param2: value2")
        lines.append("```\n")

        for skill in skills:
            lines.append(f"### {skill.display_name}")
            lines.append(f"- スキル名: `{skill.name}`")
            lines.append(f"- 説明: {skill.description[:100]}...")
            lines.append("")

        return "\n".join(lines)

    async def _call_llm(self) -> str:
        """LLMを呼び出す（ストリーミング）"""
        if not self.llm_client:
            return "[STATE: CHAT]\nLLMクライアントが設定されていません。"

        messages = self.session.get_messages_for_llm()
        system_prompt = self._build_system_prompt()

        full_response = ""
        current_line = ""

        try:
            async with self.llm_client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                system=system_prompt,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    full_response += text
                    current_line += text

                    # 改行で行を処理
                    while "\n" in current_line:
                        line, current_line = current_line.split("\n", 1)
                        line = line.strip()

                        # [STEP] を検出してリアルタイム通知
                        if line.startswith("[STEP]"):
                            step_text = line[6:].strip()
                            if step_text:
                                self.session.add_reasoning_step(step_text)
                                if self._on_reasoning_step:
                                    await self._on_reasoning_step(step_text)

                        # [STATE: XXX] を検出
                        state_match = re.match(r'\[STATE:\s*(\w+)\]', line)
                        if state_match:
                            state_name = state_match.group(1).upper()
                            self.session.add_reasoning_step(f"→ {state_name}")
                            if self._on_reasoning_step:
                                await self._on_reasoning_step(f"→ {state_name}")

            return full_response

        except Exception as e:
            logger.exception(f"LLM call failed: {e}")
            return f"[STATE: CHAT]\nエラーが発生しました: {e}"

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """
        LLMのレスポンスを解析

        Returns:
            {
                "new_state": 新しい状態（あれば）,
                "steps": [STEP]の内容リスト,
                "user_response": ユーザーに見せる部分,
            }
        """
        new_state = None
        steps = []
        user_response_lines = []

        for line in response.split("\n"):
            line_stripped = line.strip()

            # [STATE: XXX] を検出
            state_match = re.match(r'\[STATE:\s*(\w+)\]', line_stripped)
            if state_match:
                state_name = state_match.group(1).lower()
                try:
                    new_state = State(state_name)
                except ValueError:
                    pass
                continue

            # [STEP] を検出
            if line_stripped.startswith("[STEP]"):
                step_text = line_stripped[6:].strip()
                if step_text:
                    steps.append(step_text)
                continue

            # それ以外はユーザー向け応答
            user_response_lines.append(line)

        # ユーザー向け応答を整形
        user_response = "\n".join(user_response_lines).strip()

        return {
            "new_state": new_state,
            "steps": steps,
            "user_response": user_response,
        }

async def create_runner(
    session_id: str,
    user_id: str,
    on_reasoning_step: Optional[Callable[[str], Awaitable[None]]] = None,
) -> AgentRunner:
    """
    AgentRunnerを作成（セッションを自動取得）

    使い方:
        runner = await create_runner(room_id, user_id, on_step_callback)
        result = await runner.process_message("新幹線を予約したい")
    """
    store = get_session_store()
    session = await store.get_or_create(session_id, user_id)

    return AgentRunner(
        session=session,
        on_reasoning_step=on_reasoning_step,
    )
