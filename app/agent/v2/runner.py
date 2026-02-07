"""
AgentRunner - 会話ループのメインロジック（Native Tool Use方式）

Messages配列を維持しながらLLMと対話する。
状態機械なし - LLMが自律的に判断する。

アーキテクチャ:
- ブートストラップファイル: ~/.dan/workspace/ からペルソナ・ルールを読み込み
- Native Tool Use: LLMがツールを呼び出して操作を実行
- テキスト出力がそのままユーザーへの返答になる
- 自己学習: ダンがワークスペースファイルを読み書きして学習
"""

import re
import logging
import asyncio
from typing import Optional, Dict, Any, Callable, Awaitable, List
from pathlib import Path

import anthropic

from app.agent.v2.session import Session, get_session_store
from app.agent.v2.tools import (
    execute_tool, format_tool_result, FormattedToolResult, SkillRegistry,
    get_all_skill_tools, parse_tool_name,
)
from app.config import settings

logger = logging.getLogger(__name__)


def safe_print(msg: str) -> None:
    """Windows cp932でも安全にprint（エンコードできない文字は置換）"""
    try:
        print(msg)
    except UnicodeEncodeError:
        # エンコードできない文字を ? に置換して出力
        safe_msg = msg.encode('cp932', errors='replace').decode('cp932')
        print(safe_msg)


# コアプロンプト（不変）
CORE_PROMPT = "You are Dan, a personal AI assistant."

# ツール実行の最大ループ回数（安全弁として100回を超えたら強制終了）
MAX_TOOL_LOOPS = 100

# コンパクション設定
COMPACTION_THRESHOLD = 80000  # この文字数を超えたらコンパクション発動
COMPACTION_KEEP_RECENT = 10   # コンパクション時に残す最新メッセージ数

# 使用するモデル
MODEL = "claude-sonnet-4-5-20250929"  # Sonnet 4.5

# ============================================
# Native Tool Use: ツール定義
# ============================================
# LLMのテキスト出力がそのままユーザーへの返答になる


def get_core_prompt() -> str:
    """コアプロンプトを返す"""
    return CORE_PROMPT


# ブートストラップファイルのディレクトリ
WORKSPACE_DIR = Path.home() / ".dan" / "workspace"


def load_bootstrap_file(filename: str) -> str:
    """ブートストラップファイルを読み込む（~/.dan/workspace/）"""
    filepath = WORKSPACE_DIR / filename
    if filepath.exists():
        try:
            return filepath.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to load bootstrap file {filename}: {e}")
    return ""


def load_all_bootstrap_files() -> str:
    """全ブートストラップファイルを読み込んで結合（順番重要: RULES.md を最後に）"""
    parts = []

    # 1. USER.md - ユーザー情報
    user = load_bootstrap_file("USER.md")
    if user:
        parts.append(f"## ユーザー情報\n\n{user}")

    # 2. MEMORY.md - 長期記憶
    memory = load_bootstrap_file("MEMORY.md")
    if memory:
        parts.append(f"## 長期記憶\n\n{memory}")

    # 3. 直近の日別メモリ（yesterday + today）
    from datetime import datetime, timedelta
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    for date_str in [yesterday, today]:
        daily = load_bootstrap_file(f"memory/{date_str}.md")
        if daily:
            # サイズ上限: 1ファイルあたり最大4000文字（末尾=最新部分を優先）
            if len(daily) > 4000:
                daily = daily[-4000:]
            parts.append(f"## 会話ログ ({date_str})\n\n{daily}")

    # 4. SOUL.md - ペルソナ
    soul = load_bootstrap_file("SOUL.md")
    if soul:
        parts.append(f"## ペルソナ\n\n{soul}")

    # 5. RULES.md - 運用ルール（最後に配置 = recency bias で効きやすい）
    rules = load_bootstrap_file("RULES.md")
    if rules:
        parts.append(rules)  # RULES.md は既にタイトル含むのでそのまま

    if parts:
        return "\n\n---\n\n".join(parts)
    return ""


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
        ユーザーメッセージを処理（Native Tool Use方式）

        Args:
            user_message: ユーザーのメッセージ
            credentials: 認証情報（オプション）

        Returns:
            {
                "response": ユーザーへの応答（テキストブロックから抽出）,
                "state": 現在の状態,
                "reasoning_steps": 推論過程,
                "tool_results": ツール実行結果（あれば）,
            }
        """
        try:
            print(f"[RUNNER_DEBUG] Starting process_message for user {self.session.user_id}")
            safe_print(f"[RUNNER_DEBUG] Message: {user_message[:50]}...")

            # 現在のセッションIDをコンテキストに設定（キャンセルチェック用）
            from app.services.cancellation import CancellationRegistry
            CancellationRegistry.set_current_session(self.session.session_id)

            # 0.5. Deterministic skill lookup routing (bypass LLM)
            skill_lookup_response = self._maybe_handle_skill_lookup(user_message)
            if skill_lookup_response:
                self.session.clear_reasoning_steps()
                self.session.add_user_message(user_message)
                self.session.add_assistant_message(skill_lookup_response)
                store = get_session_store()
                await store.save(self.session)
                return {
                    "response": skill_lookup_response,
                    "state": self.session.current_state.value,
                    "reasoning_steps": self.session.reasoning_steps,
                }

            # 1. 推論ステップをクリア（新しいターン）
            self.session.clear_reasoning_steps()

            # 2. ユーザーメッセージを追加
            self.session.add_user_message(user_message)

            # 3. LLM呼び出し→ツール実行ループ（Native Tool Use）
            tool_results = []
            user_response = None
            print(f"[RUNNER_DEBUG] Starting LLM loop, state: {self.session.current_state.value}")

            for loop_count in range(MAX_TOOL_LOOPS + 1):
                # キャンセルチェック
                from app.services.cancellation import CancellationRegistry
                if CancellationRegistry.is_cancelled(self.session.session_id):
                    logger.info(f"Session {self.session.session_id} cancelled at loop start")
                    return {
                        "response": "処理が中断されました。",
                        "state": self.session.current_state.value,
                        "reasoning_steps": self.session.reasoning_steps,
                        "cancelled": True,
                    }

                print(f"[RUNNER_DEBUG] Calling LLM with tools (loop {loop_count})...")

                # LLMをTool Use APIで呼び出し
                response = await self._call_llm_with_tools()

                # レスポンスを処理
                parsed = await self._process_llm_response(response)


                # アシスタントメッセージを追加
                self.session.add_assistant_message_from_response(response)

                # ユーザー回答を抽出
                if parsed["user_response"]:
                    user_response = parsed["user_response"]
                # ツール呼び出しがない、または最大ループに達した場合は終了
                if not parsed["tool_calls"] or loop_count >= MAX_TOOL_LOOPS:
                    print(f"[RUNNER_DEBUG] No more tool calls or max loops reached")
                    break

                # ツールを実行
                for tool_call in parsed["tool_calls"]:
                    # ツール実行前にもキャンセルチェック
                    if CancellationRegistry.is_cancelled(self.session.session_id):
                        logger.info(f"Session {self.session.session_id} cancelled before tool execution")
                        # 未実行の操作にダミー結果を挿入（ペア崩れ防止）
                        for remaining in parsed["tool_calls"]:
                            self.session.add_tool_result(
                                remaining["tool_use_id"],
                                "[操作が中断されました]",
                            )
                        return {
                            "response": "処理が中断されました。",
                            "state": self.session.current_state.value,
                            "reasoning_steps": self.session.reasoning_steps,
                            "cancelled": True,
                        }

                    tool_use_id = tool_call["tool_use_id"]
                    skill_name = tool_call["skill"]
                    action = tool_call["action"]
                    params = tool_call["params"]

                    # check_skillはスキル名もログに含める
                    if skill_name == "_check_skill":
                        log_msg = f"Executing tool: check_skill({params.get('skill_name', '?')})"
                    else:
                        log_msg = f"Executing tool: {skill_name} {action}"
                    logger.info(log_msg)
                    # ツール実行ログをファイルにも記録
                    try:
                        from datetime import datetime
                        from pathlib import Path
                        _log_path = Path(__file__).parent.parent.parent.parent / "logs" / "tool_calls.log"
                        with open(_log_path, "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.now().isoformat()}] {log_msg} params={params}\n")
                    except Exception:
                        pass
                    if self._on_reasoning_step:
                        await self._on_reasoning_step(f"🔧 {skill_name} {action}...")

                    result = await execute_tool(
                        tool_call=tool_call,
                        user_id=self.session.user_id,
                        credentials=credentials,
                        session_id=self.session.session_id,
                    )

                    # エラータイプに基づいて処理を分岐
                    error_type = result.get("error_type")

                    # 認証情報が必要な場合: tool_resultを追加してLLMに処理を任せる
                    # LLMが自然な言葉でユーザーに聞き、save_credentialsで保存する
                    if result.get("credentials_required") or error_type in (
                        "credentials_required",
                        "credentials_invalid",
                        "session_expired",
                    ):
                        service_name = result.get("service") or result.get("service_name") or skill_name or "unknown"
                        display_name = result.get("display_name") or result.get("service_display_name") or service_name
                        self.session.add_tool_result(
                            tool_use_id=tool_use_id,
                            content=f"認証情報が必要です: {display_name}。ユーザーにログイン情報を聞いて、教えてもらったら save_credentials ツールで保存してください。"
                        )
                        # returnせずに続行し、LLMに応答を生成させる

                    # エラーログ
                    if error_type and not result.get("success"):
                        logger.info(f"Tool error: type={error_type}, recoverable={result.get('recoverable', True)}")

                    tool_results.append({
                        "tool": tool_call,
                        "result": result,
                    })

                    # ブラウザ操作のログを記録（学習システム用）
                    if skill_name == "_browser":
                        try:
                            from app.services import learning_service
                            from urllib.parse import urlparse

                            # 結果テキストからページ情報と要素情報を抽出
                            url = params.get("url", "")
                            page_url = ""
                            page_title = ""
                            element_tag = ""
                            element_text = ""
                            ref = params.get("ref", "")

                            for block in result.get("content", []):
                                if not (isinstance(block, dict) and block.get("type") == "text"):
                                    continue
                                for line in block["text"].split("\n"):
                                    if line.startswith("URL: "):
                                        page_url = line[5:].strip()
                                    elif line.startswith("タイトル: "):
                                        page_title = line[len("タイトル: "):].strip()
                                    elif ref and line.strip().startswith(f"{ref}:"):
                                        # "@e3: [button] カートに入れる" から要素情報を抽出
                                        after_ref = line.split(":", 1)[1].strip()
                                        if after_ref.startswith("["):
                                            bracket_end = after_ref.find("]")
                                            if bracket_end > 0:
                                                element_tag = after_ref[1:bracket_end]
                                                element_text = after_ref[bracket_end + 1:].strip()[:100]
                                break

                            site = None
                            if page_url:
                                site = urlparse(page_url).netloc
                            elif url:
                                site = urlparse(url).netloc

                            await learning_service.record_action_event(
                                session_id=self.session.session_id,
                                action_name=f"browser_{action}",
                                technical_success=result.get("success", False),
                                context={
                                    "page_url": page_url,
                                    "page_title": page_title,
                                    "element_tag": element_tag,
                                    "element_text": element_text,
                                },
                                user_id=self.session.user_id,
                                site=site,
                                skill_name="_browser",
                                action_params=params,
                            )
                        except Exception as e:
                            logger.debug(f"Failed to record browser event: {e}")

                    # ツール結果をtool_result形式でメッセージに追加
                    # Progressive Disclosure: スキル情報を渡してマニュアルを注入
                    skill = SkillRegistry.get(skill_name)
                    formatted = format_tool_result(result, skill_name, action, skill=skill)
                    self.session.add_tool_result(
                        tool_use_id=tool_use_id,
                        content=formatted.text,
                        images=formatted.images if formatted.has_images() else None,
                    )

                    if self._on_reasoning_step:
                        status = "✅" if result.get("success") else "❌"
                        vision_indicator = " 👁️" if formatted.has_images() else ""
                        # 具体的な結果メッセージを表示
                        message = result.get("message", "")
                        if message and len(message) < 100:
                            await self._on_reasoning_step(f"{status} {message}{vision_indicator}")
                        else:
                            # 長いメッセージは要約
                            action_label = f"{skill_name} {action}"
                            await self._on_reasoning_step(f"{status} {action_label} 完了{vision_indicator}")

            # 4. セッションを保存
            store = get_session_store()
            await store.save(self.session)

            # 5. コンパクションチェック
            await self._check_and_compact()

            # 6. 自動分析をトリガー（バックグラウンドで実行）
            if tool_results:  # ツールを使った場合のみ分析
                asyncio.create_task(self._trigger_learning_analysis())

            # フォールバック: テキスト出力がなかった場合
            if not user_response:
                logger.warning("No text response from LLM, using fallback")
                user_response = "処理が完了しました。"

            # ブラウザセッションIDを抽出（スキル化用）
            # browser_* ツールが使われた場合、session_id をブラウザセッションIDとして返す
            browser_session_id = None
            for tool_result in tool_results:
                tool_call_data = tool_result.get("tool", {})
                if tool_call_data.get("skill") == "_browser":
                    browser_session_id = self.session.session_id
                    break

            return {
                "response": user_response,
                "state": self.session.current_state.value,
                "reasoning_steps": self.session.reasoning_steps,
                "tool_results": tool_results,
                "browser_session_id": browser_session_id,  # スキル化用
            }

        except Exception as e:
            import traceback
            from app.services.cancellation import CancelledError

            # キャンセルされた場合は正常終了として扱う
            if isinstance(e, CancelledError):
                logger.info(f"Session {self.session.session_id} cancelled")
                return {
                    "response": "処理がキャンセルされました。",
                    "state": self.session.current_state.value,
                    "reasoning_steps": self.session.reasoning_steps,
                    "cancelled": True,
                }

            error_details = traceback.format_exc()
            print(f"[RUNNER_ERROR] Exception in process_message:")
            print(f"[RUNNER_ERROR] {error_details}")
            logger.exception(f"Error in process_message: {e}")

            # ★★★ 重要: エラー発生時はキャッシュをクリア ★★★
            # メモリ上のセッションが不整合な状態（tool_useあり、tool_resultなし）に
            # なっている可能性があるため、キャッシュから削除して次回DBから再読み込み
            store = get_session_store()
            store.invalidate_cache(self.session.session_id, self.session.user_id)
            logger.info(f"Session cache invalidated due to error: {self.session.session_id}")

            return {
                "response": "申し訳ありません。エラーが発生しました。",
                "state": self.session.current_state.value,
                "reasoning_steps": self.session.reasoning_steps,
                "error": str(e),
            }
        finally:
            # セッションIDをクリア
            from app.services.cancellation import CancellationRegistry
            CancellationRegistry.set_current_session(None)

    def _build_system_prompt(self) -> str:
        """
        システムプロンプトを構築

        順番（recency bias 考慮: 重要なルールは最後）:
        1. コアID
        2. 現在の日時
        3. 利用可能なツール一覧
        4. 利用可能なスキル一覧
        5. ブートストラップファイル（USER → MEMORY → yesterday/today → SOUL → RULES）
        """
        print("[RUNNER_DEBUG] Building system prompt...")
        parts = []

        # 1. コアプロンプト
        parts.append(get_core_prompt())
        print(f"[RUNNER_DEBUG] Core prompt added")

        # 2. 現在日時
        from datetime import datetime
        now = datetime.now()
        weekdays = ['月', '火', '水', '木', '金', '土', '日']
        datetime_section = f"""## 現在の日時
- 今日: {now.strftime('%Y年%m月%d日')}（{weekdays[now.weekday()]}曜日）
- 現在時刻: {now.strftime('%H:%M')}"""
        parts.append(datetime_section)

        # 3. 利用可能なツール一覧
        tools_section = self._build_tools_list_section()
        if tools_section:
            parts.append(tools_section)

        # 4. 利用可能なスキル一覧
        skill_list = self._build_skill_list_section()
        if skill_list:
            parts.append(skill_list)

        # 5. ブートストラップファイル（RULES.md が最後に来る）
        bootstrap = load_all_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)
            print(f"[RUNNER_DEBUG] Bootstrap files loaded: {len(bootstrap)} chars")

        system = "\n\n---\n\n".join(parts)
        print(f"[RUNNER_DEBUG] Total system prompt: {len(system)} chars")
        return system

    def _build_tools_list_section(self) -> str:
        """利用可能なツール一覧を構築"""
        tools = self._get_tools()
        lines = ["## 利用可能なツール"]
        for tool in tools:
            name = tool.get("name", "")
            desc = tool.get("description", "").split("\n")[0]  # 1行目のみ
            lines.append(f"- `{name}`: {desc}")
        return "\n".join(lines)

    def _build_skill_list_section(self) -> str:
        """スキル一覧（description のみ）"""
        skills = SkillRegistry.list_all()
        if not skills:
            return ""

        lines = ["## 利用可能なスキル"]
        lines.append("")
        for skill in skills:
            lines.append(f"- `{skill.name}`: {skill.description}")
        lines.append("")
        lines.append("### スキル使用ルール（必須）")
        lines.append("")
        lines.append("1. ユーザーの依頼が上記スキルに該当する場合、**必ず最初に `check_skill` ツールで手順書を取得すること**。手順書なしで自己流で操作してはいけない。")
        lines.append("2. 手順書を取得したら、その手順に従って `browser_open`/`browser_click`/`browser_type` 等で操作する。")
        lines.append("3. 該当するスキルがない場合は、自分の判断でブラウザ操作して構わない。")
        return "\n".join(lines)


    def _normalize_skill_token(self, text: str) -> str:
        """Normalize skill tokens for lookup (ASCII-only, stable matching)."""
        import re
        normalized = re.sub(r"[^a-z0-9]+", "_", text.lower())
        normalized = normalized.strip("_")
        return normalized

    def _find_skill_for_lookup(self, message: str, allow_substring: bool) -> Optional["Skill"]:
        """Find a skill by exact/substring match against normalized aliases."""
        SkillRegistry.reload()
        skills = SkillRegistry.list_all()
        if not skills:
            return None

        alias_map: Dict[str, Any] = {}
        for skill in skills:
            variants = {
                skill.name,
                skill.name.replace("-", "_"),
                skill.name.replace("_", "-"),
                skill.display_name,
            }
            for variant in variants:
                key = self._normalize_skill_token(variant)
                if key:
                    alias_map.setdefault(key, skill)

        normalized_msg = self._normalize_skill_token(message)
        if normalized_msg in alias_map:
            return alias_map[normalized_msg]

        if allow_substring:
            for key, skill in sorted(alias_map.items(), key=lambda item: len(item[0]), reverse=True):
                if key and key in normalized_msg:
                    return skill

        return None

    def _build_skill_list_response(self, skills: List["Skill"]) -> str:
        limit = 30
        lines = [f"????????: {len(skills)}?"]
        lines.append("")
        for skill in skills[:limit]:
            lines.append(f"- {skill.display_name} (`{skill.name}`)")
        if len(skills) > limit:
            lines.append(f"... ?? {len(skills) - limit} ?")
        lines.append("")
        lines.append("????<skill_name>?????????????")
        return "\n".join(lines)

    def _build_skill_detail_response(self, skill: "Skill") -> str:
        actions = self._extract_actions_from_skill(skill.raw_content) or skill.list_available_actions()
        tools = []
        for action in actions:
            tools.append(f"`{skill.name.replace('-', '_')}_{action}`")

        lines = [f"{skill.display_name} (`{skill.name}`)"]
        if skill.description:
            lines.append(f"- ??: {skill.description}")
        if tools:
            lines.append(f"- ???: {', '.join(tools)}")
        return "\n".join(lines)


    def _maybe_handle_skill_lookup(self, user_message: str) -> Optional[str]:
        """Return a direct response when the user asks about skills or lists them."""
        message = (user_message or "").strip()
        if not message:
            return None

        lower = message.lower()

        list_triggers = [
            "skill list",
            "skills",
            "list skills",
            "available skills",
        ]
        if any(t in lower for t in list_triggers) or "?????" in message or "??????" in message:
            skills = SkillRegistry.list_all()
            return self._build_skill_list_response(skills)

        lookup_triggers = [
            "what is",
            "what's",
            "about",
            "help",
            "details",
        ]
        has_lookup_trigger = any(t in lower for t in lookup_triggers)
        if "??" in message or "???" in message or "????" in message or "???" in message or "??" in message:
            has_lookup_trigger = True

        ascii_short = (len(message) <= 40 and len(message) >= 4 and all(ord(c) < 128 for c in message) and ("_" in message or "-" in message or message.isalnum()))
        if not has_lookup_trigger and not ascii_short and "???" not in message and "skill" not in lower:
            return None

        skill = self._find_skill_for_lookup(message, allow_substring=has_lookup_trigger)
        if skill:
            return self._build_skill_detail_response(skill)

        if has_lookup_trigger and ("???" in message or "skill" in lower):
            skills = SkillRegistry.list_all()
            return self._build_skill_list_response(skills)

        return None

    def _get_model(self) -> str:
        """使用するモデルを返す"""
        return MODEL

    def _get_tools(self) -> List[Dict[str, Any]]:
        """
        LLMに渡すツール一覧を取得

        Returns:
            全スキルツール
        """
        return get_all_skill_tools()

    async def _call_llm_with_tools(self) -> "anthropic.types.Message":
        """
        LLMをTool Use APIで呼び出す

        Returns:
            Anthropic Message オブジェクト（content blocksを含む）
        """
        if not self.llm_client:
            raise RuntimeError("LLMクライアントが設定されていません")

        messages = self.session.get_messages_for_llm()
        system_prompt = self._build_system_prompt()
        model = self._get_model()
        tools = self._get_tools()

        print(f"[LLM_DEBUG] Calling LLM with {len(tools)} tools")
        print(f"[LLM_DEBUG] Tool names: {[t['name'] for t in tools]}")

        response = await self.llm_client.messages.create(
            model=model,
            max_tokens=4000,
            system=system_prompt,
            messages=messages,
            tools=tools,
        )

        print(f"[LLM_DEBUG] Response stop_reason: {response.stop_reason}")
        print(f"[LLM_DEBUG] Response content blocks: {len(response.content)}")

        return response

    async def _process_llm_response(
        self,
        response: "anthropic.types.Message",
    ) -> Dict[str, Any]:
        """
        LLMレスポンスのcontent blocksを処理

        - text blocks → ユーザーへの返答として収集
        - tool_use blocks → ツール実行

        Returns:
            {
                "user_response": ユーザー回答（テキストブロックから）,
                "tool_calls": 実行すべきスキルツール呼び出しリスト,
                "stop_reason": LLMの停止理由,
            }
        """
        text_parts = []
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                # テキストブロック → ユーザーへの返答
                text = block.text.strip()
                if text:
                    text_parts.append(text)
                    safe_print(f"[LLM_DEBUG] Text block: {text[:50]}...")

            elif block.type == "tool_use":
                # ツール呼び出しブロック
                tool_name = block.name
                tool_input = block.input
                tool_use_id = block.id

                print(f"[LLM_DEBUG] Tool use: {tool_name}")

                # スキルツール呼び出し
                parsed = parse_tool_name(tool_name)
                if parsed:
                    skill_name, action = parsed
                    tool_calls.append({
                        "tool_use_id": tool_use_id,
                        "skill": skill_name,
                        "action": action,
                        "params": tool_input,
                    })
                    print(f"[LLM_DEBUG] Skill tool: {skill_name} {action}")

        # テキストブロックを結合してユーザー返答とする
        user_response = "\n\n".join(text_parts) if text_parts else None

        return {
            "user_response": user_response,
            "tool_calls": tool_calls,
            "stop_reason": response.stop_reason,
        }

    async def _check_and_compact(self) -> None:
        """
        コンパクションが必要かチェックし、必要なら実行

        1. トークン数が閾値を超えたらメモリフラッシュを実行
        2. LLMに重要情報を memory/ に保存させる
        3. 古いメッセージを削除し、要約を残す
        """
        token_count = self.session.estimate_token_count()
        logger.debug(f"Token count: {token_count} / {COMPACTION_THRESHOLD}")

        if token_count < COMPACTION_THRESHOLD:
            return

        logger.info(f"Compaction triggered: {token_count} tokens")

        if self._on_reasoning_step:
            await self._on_reasoning_step("📝 会話が長くなったので記憶を整理中...")

        try:
            # メモリフラッシュ: LLMに重要情報を保存させる
            summary = await self._flush_to_memory()

            # 要約生成に失敗した場合はコンパクション中止（文脈喪失を防ぐ）
            if not summary or summary == "会話の要約が生成されませんでした。":
                logger.warning("Summary generation failed, aborting compaction to preserve context")
                if self._on_reasoning_step:
                    await self._on_reasoning_step("⚠️ 要約生成に失敗したため、記憶整理をスキップしました")
                return

            # 古いメッセージを削除し、要約を残す
            removed = self.session.compact(summary, keep_recent=COMPACTION_KEEP_RECENT)
            logger.info(f"Compacted: removed {removed} messages, kept {COMPACTION_KEEP_RECENT}")

            # セッションを再保存
            store = get_session_store()
            await store.save(self.session)

            if self._on_reasoning_step:
                await self._on_reasoning_step(f"✅ 記憶を整理しました（{removed}件のメッセージを要約）")

        except Exception as e:
            logger.exception(f"Compaction failed: {e}")
            # コンパクション失敗は致命的ではない、続行

    @staticmethod
    def _strip_images_for_summary(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        メッセージから画像を除外し、テキストのみのコピーを返す。

        要約生成にスクリーンショットは不要。画像を除外することで
        トークン消費を大幅に削減し、要約LLM呼び出しの成功率を上げる。
        """
        import copy
        stripped = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                stripped.append(msg)
            elif isinstance(content, list):
                new_blocks = []
                for block in content:
                    if not isinstance(block, dict):
                        new_blocks.append(block)
                        continue
                    btype = block.get("type", "")
                    # 画像ブロックをスキップ
                    if btype == "image":
                        continue
                    # tool_result内の画像もスキップ
                    if btype == "tool_result":
                        inner = block.get("content", "")
                        if isinstance(inner, list):
                            filtered = [b for b in inner if not (isinstance(b, dict) and b.get("type") == "image")]
                            if filtered:
                                new_block = copy.copy(block)
                                new_block["content"] = filtered
                                new_blocks.append(new_block)
                            else:
                                # テキストもない場合はプレースホルダー
                                new_block = copy.copy(block)
                                new_block["content"] = "[スクリーンショット]"
                                new_blocks.append(new_block)
                            continue
                        new_blocks.append(block)
                        continue
                    new_blocks.append(block)
                if new_blocks:
                    stripped.append({"role": msg["role"], "content": new_blocks})
            else:
                stripped.append(msg)
        return stripped

    async def _flush_to_memory(self) -> str:
        """
        メモリフラッシュ: LLMに重要情報を memory/ に保存させる

        Returns:
            会話の要約テキスト
        """
        from datetime import datetime

        # フラッシュ用のシステムプロンプト
        flush_system = """あなたはDan、パーソナルAIアシスタントです。

会話が長くなったので、重要な情報を保存する必要があります。

以下を行ってください:
1. これまでの会話から重要な情報（ユーザーの好み、決定事項、進行中のタスク等）を抽出
2. update_workspace ツールで memory/{date}.md に **追記（appendパラメータを使用）** する。contentではなくappendを使うこと。
3. 長期的に重要な情報（ユーザーの好みの変化、重要な決定事項、繰り返し参照される事実）があれば、MEMORY.md にも追記する
4. 会話の要約をテキストで出力（この要約は会話履歴に残ります）

要約は簡潔に、箇条書きで、重要なポイントのみ含めてください。
""".format(date=datetime.now().strftime("%Y-%m-%d"))

        # フラッシュ用のメッセージ（画像を除外してトークン節約）
        flush_messages = self._strip_images_for_summary(
            self.session.get_messages_for_llm()
        )
        flush_messages.append({
            "role": "user",
            "content": "【システム】会話が長くなりました。重要な情報を memory/ に保存し、会話の要約を作成してください。"
        })

        # LLM呼び出し
        tools = self._get_tools()
        response = await self.llm_client.messages.create(
            model=self._get_model(),
            max_tokens=2000,
            system=flush_system,
            messages=flush_messages,
            tools=tools,
        )

        # レスポンスを処理
        summary = "会話の要約が生成されませんでした。"
        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text.strip())
            elif block.type == "tool_use":
                if block.name == "update_workspace":
                    # update_workspaceを実行
                    from app.agent.v2.tools import execute_tool, parse_tool_name
                    parsed = parse_tool_name(block.name)
                    if parsed:
                        skill_name, action = parsed
                        await execute_tool(
                            tool_call={
                                "tool_use_id": block.id,
                                "skill": skill_name,
                                "action": action,
                                "params": block.input,
                            },
                            user_id=self.session.user_id,
                        )

        # テキスト出力を要約として使用
        if text_parts:
            summary = "\n\n".join(text_parts)

        return summary

    async def _trigger_learning_analysis(self) -> None:
        """
        学習分析をバックグラウンドで実行

        ツール実行後に非同期で呼び出される。
        エラーが発生してもユーザー体験に影響しない。
        """
        try:
            from app.services import learning_service
            result = await learning_service.trigger_auto_analysis(
                session_id=self.session.session_id,
                site=None,  # 全サイト対象
            )
            if result.get("skipped"):
                logger.debug(f"Learning analysis skipped: {result.get('reason')}")
            elif result.get("error"):
                logger.warning(f"Learning analysis error: {result.get('error')}")
            else:
                logger.info(
                    f"Learning analysis complete: "
                    f"{result.get('retry_patterns_detected', 0)} patterns, "
                    f"{result.get('rules_created', 0)} rules"
                )
        except Exception as e:
            # エラーはログに記録するだけ（ユーザー体験に影響しない）
            logger.warning(f"Learning analysis failed: {e}")

    # Legacy: 旧方式との互換性のため残す（将来削除予定）
    async def _call_llm(self) -> str:
        """LLMを呼び出す（レガシー：テキスト形式で返す）"""
        try:
            response = await self._call_llm_with_tools()
            # テキストブロックを結合して返す
            text_parts = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
            return "\n".join(text_parts)
        except Exception as e:
            logger.exception(f"LLM call failed: {e}")
            return f"エラーが発生しました: {e}"


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
