"""
AgentRunner - 会話ループのメインロジック（Native Tool Use方式）

Messages配列を維持しながらLLMと対話する。
状態遷移はLLMの出力から検出し、コードは追従するだけ。

Native Tool Use:
- respond_to_user ツールでユーザー回答を構造化
- テキストブロックは全てプロセスとして処理
- プロセス漏出を100%防止
"""

import re
import logging
import asyncio
from typing import Optional, Dict, Any, Callable, Awaitable, List
from pathlib import Path

import anthropic

from app.agent.v2.session import Session, State, get_session_store
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


# プロンプトディレクトリ
PROMPTS_DIR = Path(__file__).parent / "prompts"

# ツール実行の最大ループ回数（安全弁として100回を超えたら強制終了）
MAX_TOOL_LOOPS = 100

# セーフティネット: LLMがルール違反した場合に除外するパターン
# これらのパターンに一致する行はプロセスモニターに表示しない
INTERNAL_FILTER_PATTERNS = [
    r'^.*を確認します[。]?$',
    r'^.*を実行します[。]?$',
    r'^.*を探します[。]?$',
    r'^.*にスクロール.*$',
    r'^.*スクリーンショット.*$',
    r'^.*ページ構造.*$',
    r'^.*の検出に失敗.*$',
    r'^ツール実行[:：].*$',
    r'^回答を作成.*$',
]

# 使用するモデル
MODEL = "claude-sonnet-4-5-20250929"  # Sonnet 4.5

# ============================================
# Native Tool Use: ツール定義
# ============================================

# respond_to_user: ユーザーへの最終回答を構造化して出力するツール
# このツールを経由することで、プロセス（テキストブロック）と回答を100%分離できる
RESPOND_TO_USER_TOOL = {
    "name": "respond_to_user",
    "description": "ユーザーへの最終回答を出力する。内部処理が完了したら、必ずこのツールを使って回答すること。",
    "input_schema": {
        "type": "object",
        "properties": {
            "response": {
                "type": "string",
                "description": "ユーザーに表示する回答テキスト"
            }
        },
        "required": ["response"]
    }
}


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
        ユーザーメッセージを処理（Native Tool Use方式）

        Args:
            user_message: ユーザーのメッセージ
            credentials: 認証情報（オプション）

        Returns:
            {
                "response": ユーザーへの応答（respond_to_userツールから抽出）,
                "state": 現在の状態,
                "reasoning_steps": 推論過程（テキストブロックから抽出）,
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

                # 状態遷移を適用（無効化: experiment/no-state-machine）
                # if parsed["new_state"]:
                #     self.session.transition_to(parsed["new_state"])

                # アシスタントメッセージを追加
                self.session.add_assistant_message_from_response(response)

                # ユーザー回答を抽出
                if parsed["user_response"]:
                    user_response = parsed["user_response"]
                    # respond_to_userのtool_resultを追加（次のLLM呼び出しで必要）
                    if parsed.get("respond_to_user_id"):
                        self.session.add_tool_result(
                            tool_use_id=parsed["respond_to_user_id"],
                            content="回答を表示しました。",
                        )

                # ツール呼び出しがない、または最大ループに達した場合は終了
                if not parsed["tool_calls"] or loop_count >= MAX_TOOL_LOOPS:
                    print(f"[RUNNER_DEBUG] No more tool calls or max loops reached")
                    break

                # ツールを実行
                for tool_call in parsed["tool_calls"]:
                    # ツール実行前にもキャンセルチェック
                    if CancellationRegistry.is_cancelled(self.session.session_id):
                        logger.info(f"Session {self.session.session_id} cancelled before tool execution")
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

                    logger.info(f"Executing tool: {skill_name} {action}")
                    # visual_browseは独自の進捗通知を行うのでDan側は出力しない
                    if self._on_reasoning_step and skill_name != "_visual":
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

                    # ツール結果をtool_result形式でメッセージに追加
                    # Progressive Disclosure: スキル情報を渡してマニュアルを注入
                    skill = SkillRegistry.get(skill_name)
                    formatted = format_tool_result(result, skill_name, action, skill=skill)
                    self.session.add_tool_result(
                        tool_use_id=tool_use_id,
                        content=formatted.text,
                        images=formatted.images if formatted.has_images() else None,
                    )

                    # visual_browseは独自の進捗通知を行うのでDan側は出力しない
                    if self._on_reasoning_step and skill_name != "_visual":
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

            # 5. 自動分析をトリガー（バックグラウンドで実行）
            if tool_results:  # ツールを使った場合のみ分析
                asyncio.create_task(self._trigger_learning_analysis())

            # フォールバック: respond_to_userが呼ばれなかった場合
            if not user_response:
                logger.warning("respond_to_user was not called, using fallback")
                user_response = "処理が完了しました。"

            # ブラウザセッションIDを抽出（スキル化用）
            browser_session_id = None
            for tool_result in tool_results:
                result = tool_result.get("result", {})
                if result.get("browser_session_id"):
                    browser_session_id = result["browser_session_id"]
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
        """システムプロンプトを構築（Progressive Disclosure）"""
        print("[RUNNER_DEBUG] Building system prompt...")
        # ベースのシステムプロンプト
        system = load_system_prompt()
        print(f"[RUNNER_DEBUG] Base system prompt length: {len(system)}")

        # 現在日時を注入（LLMが正確な日時を把握するため）
        from datetime import datetime, timedelta
        now = datetime.now()
        weekdays = ['月', '火', '水', '木', '金', '土', '日']
        tomorrow = now + timedelta(days=1)
        system += f"\n\n## 現在の日時\n"
        system += f"- 今日: {now.strftime('%Y年%m月%d日')}（{weekdays[now.weekday()]}曜日）\n"
        system += f"- 現在時刻: {now.strftime('%H:%M')}\n"
        system += f"- 「明日」は {tomorrow.strftime('%Y年%m月%d日')} です\n"
        system += f"- 日付パラメータは必ず YYYY-MM-DD 形式で指定してください（例: {tomorrow.strftime('%Y-%m-%d')}）"

        # 現在の状態のプロンプトを追加（無効化: experiment/no-state-machine）
        # state_prompt = load_state_prompt(self.session.current_state)
        # if state_prompt:
        #     system += f"\n\n---\n\n## 現在の状態: {self.session.current_state.value.upper()}\n\n{state_prompt}"

        # Progressive Disclosure Level 1: スキル一覧（description のみ）
        skill_list = self._build_skill_list_section()
        if skill_list:
            system += skill_list

        # Progressive Disclosure Level 2-3: 会話文脈から必要なアクションマニュアルを動的に追加
        action_manuals = self._load_relevant_action_manuals()
        if action_manuals:
            system += action_manuals

        # 出力ルールを最後に追加（recency bias対策）
        system += self._build_output_rules()

        return system

    def _build_output_rules(self) -> str:
        """出力ルールを構築（常にプロンプトの最後に配置）"""
        return """

---

## 出力ルール（厳守）

### ユーザー回答は respond_to_user ツールを使う

重要: ユーザーへの最終回答は、必ず respond_to_user ツールを呼び出して出力する。

テキストとして直接書いた内容は「内部処理」としてユーザーには表示されない。
ユーザーに見せたい回答は respond_to_user ツール経由で出力すること。

### 内部処理の書き方

思考過程や確認事項は、テキストとしてそのまま書く:
```
商品を検索中...
価格は990円、4本セット
在庫を確認...
```

これらはプロセスモニターに表示され、ユーザー回答には含まれない。

### ワークフロー例

1. ツールを呼び出して情報を取得
2. 結果を分析（テキストで思考を書く）
3. respond_to_user ツールでユーザーに回答

```
商品を検索します...

(visual_browse ツールを呼び出し)

検索結果を確認中...
4本セットが990円で見つかった

(respond_to_user ツールを呼び出し)
response: "アベンヌウォーター 50ml 4本セットが990円で見つかりました。カートに入れますか？"
```
"""

    def _build_skill_list_section(self) -> str:
        """スキル一覧（description のみ）- Progressive Disclosure Level 1"""
        skills = SkillRegistry.list_all()
        if not skills:
            return ""

        lines = ["\n\n## 利用可能なスキル"]
        for skill in skills:
            lines.append(f"- `{skill.name}`: {skill.description}")
        lines.append("\n※ スキルを使う場合は visual_browse の skill_name に指定")
        lines.append("※ 詳細が必要な場合は check_skill ツールで SKILL.md を取得")
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

    def _load_relevant_action_manuals(self) -> str:
        """
        廃止: Progressive Disclosureはformat_tool_result()で実装

        以前はここでキーワードマッチングによりアクションマニュアルを
        システムプロンプトに事前ロードしていたが、以下の問題があった:
        - ハードコードされたキーワードの保守が困難
        - 不要なマニュアルがロードされてトークン消費

        新しいアプローチ:
        - ツール実行時にformat_tool_result()がスキル本文とアクションマニュアルを
          tool_resultに注入する
        - LLMはツール呼び出し後に必要な情報を参照できる
        """
        return ""

    def _get_model(self) -> str:
        """使用するモデルを返す"""
        return MODEL

    def _get_tools(self) -> List[Dict[str, Any]]:
        """
        LLMに渡すツール一覧を取得

        Returns:
            respond_to_user + 全スキルツール
        """
        tools = [RESPOND_TO_USER_TOOL]
        tools.extend(get_all_skill_tools())
        return tools

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

        - text blocks → プロセスとして通知
        - tool_use blocks → ツール実行または回答抽出

        Returns:
            {
                "user_response": ユーザー回答（respond_to_userから）,
                "tool_calls": 実行すべきスキルツール呼び出しリスト,
                "new_state": 検出された状態遷移,
                "stop_reason": LLMの停止理由,
            }
        """
        user_response = None
        respond_to_user_id = None  # respond_to_userのtool_use_id
        tool_calls = []
        new_state = None

        for block in response.content:
            if block.type == "text":
                # テキストブロック → プロセスとして処理
                text = block.text
                await self._process_text_block(text)

                # [STATE: XXX] を検出（無効化: experiment/no-state-machine）
                # state_match = re.search(r'\[STATE:\s*(\w+)\]', text)
                # if state_match:
                #     state_name = state_match.group(1).lower()
                #     try:
                #         new_state = State(state_name)
                #     except ValueError:
                #         pass

            elif block.type == "tool_use":
                # ツール呼び出しブロック
                tool_name = block.name
                tool_input = block.input
                tool_use_id = block.id

                print(f"[LLM_DEBUG] Tool use: {tool_name}")

                if tool_name == "respond_to_user":
                    # ユーザー回答を抽出
                    user_response = tool_input.get("response", "")
                    respond_to_user_id = tool_use_id  # IDを保存
                    safe_print(f"[LLM_DEBUG] User response extracted: {user_response[:50]}...")
                else:
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

        return {
            "user_response": user_response,
            "respond_to_user_id": respond_to_user_id,  # tool_use_idを返す
            "tool_calls": tool_calls,
            "new_state": new_state,
            "stop_reason": response.stop_reason,
        }

    async def _process_text_block(self, text: str) -> None:
        """
        テキストブロックをプロセスとして処理

        - 各行をプロセスモニターに通知
        - [STATE: XXX] を検出して状態遷移を通知
        - セーフティネット: 内部処理パターンはフィルタリング
        """
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue

            # [STATE: XXX] を検出（無効化: experiment/no-state-machine）
            # state_match = re.match(r'\[STATE:\s*(\w+)\]', line)
            # if state_match:
            #     state_name = state_match.group(1).upper()
            #     self.session.add_reasoning_step(f"→ {state_name}")
            #     if self._on_reasoning_step:
            #         await self._on_reasoning_step(f"→ {state_name}")
            #     continue

            # セーフティネット: 内部処理パターンはスキップ（プロセスモニターに表示しない）
            should_skip = False
            for pattern in INTERNAL_FILTER_PATTERNS:
                if re.match(pattern, line):
                    should_skip = True
                    logger.debug(f"Filtered internal pattern: {line}")
                    break

            if should_skip:
                continue

            # その他のテキストはプロセスとして通知
            self.session.add_reasoning_step(line)
            if self._on_reasoning_step:
                await self._on_reasoning_step(line)

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
                elif block.type == "tool_use":
                    if block.name == "respond_to_user":
                        text_parts.append(block.input.get("response", ""))
            return "\n".join(text_parts)
        except Exception as e:
            logger.exception(f"LLM call failed: {e}")
            return f"[STATE: CHAT]\nエラーが発生しました: {e}"


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
