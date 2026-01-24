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

# プロンプトディレクトリ
PROMPTS_DIR = Path(__file__).parent / "prompts"

# ツール実行の最大ループ回数
# - DEVELOPモード: 10回（複雑な調査が必要なため）
# - その他: 上限なし（LLMが自然に終了する設計）
# ※安全弁として100回を超えたら強制終了
MAX_TOOL_LOOPS_DEVELOP = 10
MAX_TOOL_LOOPS_SAFETY = 100  # 万が一の暴走防止

# モデル設定（動的切り替え用）
MODELS = {
    "default": "claude-sonnet-4-5-20250929",      # 通常モード: Sonnet 4.5（コーディング最強、コスパ良）
    "develop": "claude-opus-4-5-20251101",        # DEVELOPモード: Opus 4.5（複雑な設計判断）
}

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
            print(f"[RUNNER_DEBUG] Message: {user_message[:50]}...")

            # 0. 認証情報待ちの場合、ユーザー入力から認証情報を抽出
            pending_tool = self.session.context.get("pending_tool_call")
            if pending_tool and not credentials:
                extracted = await self._extract_credentials_from_message(user_message)
                if extracted:
                    credentials = extracted
                    # 認証情報をDBに保存
                    from app.services.credentials_service import get_credentials_service
                    creds_service = get_credentials_service()
                    service_name = pending_tool.get("skill", "unknown")

                    await creds_service.save_credential(
                        user_id=self.session.user_id,
                        service=service_name,
                        credentials=credentials,
                        credential_type="login",
                    )
                    logger.info(f"Saved credentials for {service_name}")

                    # 保留中のツールを再実行
                    self.session.context.pop("pending_tool_call", None)

                    if self._on_reasoning_step:
                        await self._on_reasoning_step("🔐 認証情報を保存しました")
                        await self._on_reasoning_step(f"🔧 {pending_tool['skill']} を再実行します...")

                    result = await execute_tool(
                        tool_call=pending_tool,
                        user_id=self.session.user_id,
                        credentials=credentials,
                    )

                    # ツール結果をtool_result形式でメッセージに追加
                    formatted = format_tool_result(
                        result, pending_tool["skill"], pending_tool["action"]
                    )
                    self.session.add_tool_result(
                        tool_use_id=pending_tool.get("tool_use_id", "pending"),
                        content=formatted.text,
                        images=formatted.images if formatted.has_images() else None,
                    )

                    # LLMに結果を伝えて応答を生成
                    response = await self._call_llm_with_tools()
                    parsed = await self._process_llm_response(response)

                    if parsed["new_state"]:
                        self.session.transition_to(parsed["new_state"])

                    # アシスタントメッセージを追加
                    self.session.add_assistant_message_from_response(response)

                    store = get_session_store()
                    await store.save(self.session)

                    return {
                        "response": parsed["user_response"] or "処理が完了しました。",
                        "state": self.session.current_state.value,
                        "reasoning_steps": self.session.reasoning_steps,
                        "tool_results": [{"tool": pending_tool, "result": result}],
                    }

            # 1. 推論ステップをクリア（新しいターン）
            self.session.clear_reasoning_steps()

            # 2. ユーザーメッセージを追加
            self.session.add_user_message(user_message)

            # 3. LLM呼び出し→ツール実行ループ（Native Tool Use）
            tool_results = []
            user_response = None
            print(f"[RUNNER_DEBUG] Starting LLM loop, state: {self.session.current_state.value}")

            # 状態に応じた上限を決定
            if self.session.current_state == State.DEVELOP:
                max_loops = MAX_TOOL_LOOPS_DEVELOP
            else:
                max_loops = MAX_TOOL_LOOPS_SAFETY

            for loop_count in range(max_loops + 1):
                print(f"[RUNNER_DEBUG] Calling LLM with tools (loop {loop_count})...")

                # LLMをTool Use APIで呼び出し
                response = await self._call_llm_with_tools()

                # レスポンスを処理
                parsed = await self._process_llm_response(response)

                # 状態遷移を適用
                if parsed["new_state"]:
                    self.session.transition_to(parsed["new_state"])

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
                if not parsed["tool_calls"] or loop_count >= max_loops:
                    print(f"[RUNNER_DEBUG] No more tool calls or max loops reached")
                    break

                # ツールを実行
                for tool_call in parsed["tool_calls"]:
                    tool_use_id = tool_call["tool_use_id"]
                    skill_name = tool_call["skill"]
                    action = tool_call["action"]
                    params = tool_call["params"]

                    logger.info(f"Executing tool: {skill_name} {action}")
                    if self._on_reasoning_step:
                        await self._on_reasoning_step(f"🔧 {skill_name} {action}...")

                    result = await execute_tool(
                        tool_call=tool_call,
                        user_id=self.session.user_id,
                        credentials=credentials,
                    )

                    # エラータイプに基づいて処理を分岐
                    error_type = result.get("error_type")

                    # 認証情報が必要な場合は特別処理
                    if result.get("credentials_required") or error_type in (
                        "credentials_required",
                        "credentials_invalid",
                        "session_expired",
                    ):
                        # 保留中のツール呼び出しを保存
                        tool_call["tool_use_id"] = tool_use_id
                        self.session.context["pending_tool_call"] = tool_call

                        # ユーザーに認証情報を要求
                        display_name = result.get("display_name", result.get("service"))
                        labels = result.get("labels", {})

                        field_prompts = []
                        for field in result.get("fields", []):
                            label = labels.get(field, field)
                            field_prompts.append(f"・{label}")

                        prompt_text = f"{display_name}を利用するには認証情報が必要です。\n\n以下の情報を教えてください:\n" + "\n".join(field_prompts)

                        store = get_session_store()
                        await store.save(self.session)

                        return {
                            "response": prompt_text,
                            "state": self.session.current_state.value,
                            "reasoning_steps": self.session.reasoning_steps,
                            "credentials_required": True,
                            "service": result.get("service"),
                            "fields": result.get("fields"),
                            "labels": result.get("labels"),
                        }

                    # エラーログ
                    if error_type and not result.get("success"):
                        logger.info(f"Tool error: type={error_type}, recoverable={result.get('recoverable', True)}")

                    tool_results.append({
                        "tool": tool_call,
                        "result": result,
                    })

                    # ツール結果をtool_result形式でメッセージに追加
                    formatted = format_tool_result(result, skill_name, action)
                    self.session.add_tool_result(
                        tool_use_id=tool_use_id,
                        content=formatted.text,
                        images=formatted.images if formatted.has_images() else None,
                    )

                    if self._on_reasoning_step:
                        status = "✅" if result.get("success") else "❌"
                        vision_indicator = " 👁️" if formatted.has_images() else ""
                        await self._on_reasoning_step(f"{status} ツール実行完了{vision_indicator}")

            # 4. セッションを保存
            store = get_session_store()
            await store.save(self.session)

            # フォールバック: respond_to_userが呼ばれなかった場合
            if not user_response:
                logger.warning("respond_to_user was not called, using fallback")
                user_response = "処理が完了しました。"

            return {
                "response": user_response,
                "state": self.session.current_state.value,
                "reasoning_steps": self.session.reasoning_steps,
                "tool_results": tool_results,
            }

        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"[RUNNER_ERROR] Exception in process_message:")
            print(f"[RUNNER_ERROR] {error_details}")
            logger.exception(f"Error in process_message: {e}")
            return {
                "response": "申し訳ありません。エラーが発生しました。",
                "state": self.session.current_state.value,
                "reasoning_steps": self.session.reasoning_steps,
                "error": str(e),
            }

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

        # 現在の状態のプロンプトを追加
        state_prompt = load_state_prompt(self.session.current_state)
        if state_prompt:
            system += f"\n\n---\n\n## 現在の状態: {self.session.current_state.value.upper()}\n\n{state_prompt}"

        # 利用可能なスキル情報を追加
        system += self._build_skills_prompt()

        # Progressive Disclosure: 会話文脈から必要なアクションマニュアルを動的に追加
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

**重要**: ユーザーへの最終回答は、必ず `respond_to_user` ツールを呼び出して出力する。

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
[STATE: RESEARCH]
商品を検索します...

(amazon_search ツールを呼び出し)

検索結果を確認中...
4本セットが990円で見つかった

(respond_to_user ツールを呼び出し)
response: "アベンヌウォーター 50ml 4本セットが990円で見つかりました。カートに入れますか？"
```
"""

    def _build_skills_prompt(self) -> str:
        """利用可能なスキルのプロンプトを構築（Native Tool Use対応）"""
        skills = SkillRegistry.list_all()
        if not skills:
            return ""

        lines = ["\n\n---\n\n## 利用可能なツール\n"]
        lines.append("以下のツールが利用可能です。ツールを使う時は直接呼び出してください。\n")

        for skill in skills:
            lines.append(f"### {skill.display_name}")

            # SKILL.mdからアクション情報を抽出
            actions = self._extract_actions_from_skill(skill.raw_content)
            if actions:
                tool_names = [f"`{skill.name.replace('-', '_')}_{action}`" for action in actions]
                lines.append(f"- ツール: {', '.join(tool_names)}")

            lines.append(f"- 説明: {skill.description[:100]}...")
            lines.append("")

        # respond_to_user ツールの説明
        lines.append("### ユーザー回答")
        lines.append("- ツール: `respond_to_user`")
        lines.append("- 説明: ユーザーへの最終回答を出力（必須）")
        lines.append("")

        return "\n".join(lines)

    def _extract_actions_from_skill(self, content: str) -> list:
        """SKILL.mdからアクション一覧を抽出"""
        import re
        actions = []

        # テーブル形式 | `action` | を検出
        table_matches = re.findall(r'\|\s*`(\w+)`\s*\|', content)
        if table_matches:
            actions.extend(table_matches)

        # [TOOL: xxx action] 形式からアクションを検出
        tool_matches = re.findall(r'\[TOOL:\s*\S+\s+(\w+)\]', content)
        if tool_matches:
            actions.extend(tool_matches)

        # 重複除去して返す
        return list(dict.fromkeys(actions))

    def _load_relevant_action_manuals(self) -> str:
        """
        会話文脈から必要なアクションマニュアルを動的に読み込む（Progressive Disclosure）

        Returns:
            アクションマニュアルの内容（システムプロンプトに追加する形式）
        """
        # 会話履歴から最新のユーザーメッセージを取得
        messages = self.session.get_messages_for_llm()
        if not messages:
            return ""

        # 最新のユーザーメッセージと直近のコンテキストを分析
        context_text = ""
        for msg in messages[-3:]:  # 直近3メッセージを分析
            content = msg.get("content")
            if isinstance(content, str):
                context_text += content + " "
            elif isinstance(content, list):
                # Vision API形式のメッセージからテキスト部分を抽出
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        context_text += block.get("text", "") + " "

        # アクション検出ルール（スキル名 → アクション → キーワード）
        action_detection_rules = {
            "ex-reservation": {
                "search": ["検索", "予約", "新幹線", "探して", "取って", "東京", "新大阪", "名古屋", "博多", "行き"],
                "cancel": ["キャンセル", "取り消", "払戻", "払い戻", "やめ", "取消"],
            },
            "amazon": {
                "search": ["Amazon", "アマゾン", "買って", "購入", "探して", "商品"],
                "scroll": ["Amazon", "アマゾン", "買って", "購入", "探して", "商品"],  # searchと同時にロード
                "click_product": ["Amazon", "アマゾン", "買って", "購入", "探して", "商品"],  # searchと同時にロード
                "add_to_cart": ["カート", "カートに入れ", "カートに追加"],
                "checkout": ["レジ", "注文", "購入手続き", "チェックアウト"],
            },
        }

        loaded_manuals = []

        for skill_name, action_rules in action_detection_rules.items():
            skill = SkillRegistry.get(skill_name)
            if not skill:
                continue

            for action, keywords in action_rules.items():
                # キーワードマッチング
                if any(kw in context_text for kw in keywords):
                    manual = skill.get_action_manual(action)
                    if manual:
                        loaded_manuals.append((skill_name, action, manual))
                        logger.info(f"Progressive Disclosure: Loaded {skill_name}/{action} manual")

        if not loaded_manuals:
            return ""

        # マニュアルをシステムプロンプト形式で整形
        lines = ["\n\n---\n\n## アクション詳細マニュアル\n"]
        lines.append("以下は、現在のタスクに関連するアクションの詳細な使い方です。\n")

        for skill_name, action, manual in loaded_manuals:
            lines.append(f"### {skill_name} / {action}\n")
            lines.append(manual)
            lines.append("")

        return "\n".join(lines)

    def _get_model(self) -> str:
        """
        現在の状態に応じてモデルを選択（動的モデル切り替え）

        - DEVELOPモード: Opus 4.5（複雑な設計・コード修正）
        - その他: Sonnet 4.5（通常タスク、コスパ最強）
        """
        if self.session.current_state == State.DEVELOP:
            model = MODELS["develop"]
            logger.info(f"Using Opus 4.5 for DEVELOP mode")
        else:
            model = MODELS["default"]

        return model

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

                # [STATE: XXX] を検出
                state_match = re.search(r'\[STATE:\s*(\w+)\]', text)
                if state_match:
                    state_name = state_match.group(1).lower()
                    try:
                        new_state = State(state_name)
                    except ValueError:
                        pass

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
                    print(f"[LLM_DEBUG] User response extracted: {user_response[:50]}...")
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
        """
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue

            # [STATE: XXX] を検出
            state_match = re.match(r'\[STATE:\s*(\w+)\]', line)
            if state_match:
                state_name = state_match.group(1).upper()
                self.session.add_reasoning_step(f"→ {state_name}")
                if self._on_reasoning_step:
                    await self._on_reasoning_step(f"→ {state_name}")
                continue

            # その他のテキストはプロセスとして通知
            self.session.add_reasoning_step(line)
            if self._on_reasoning_step:
                await self._on_reasoning_step(line)

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

    async def _extract_credentials_from_message(self, message: str) -> Optional[Dict[str, str]]:
        """
        ユーザーメッセージから認証情報を抽出

        対応パターン:
        - "会員ID: 12345 パスワード: mypass"
        - "12345 / mypass"
        - "ID: 12345, PW: mypass"
        - "12345\nmypass"
        """
        import re

        # パターン1: ラベル付き（会員ID: xxx パスワード: yyy）
        id_patterns = [
            r'(?:会員ID|ID|ユーザー名|メールアドレス|member_id|username|email)[:\s：]+([^\s,、]+)',
        ]
        pass_patterns = [
            r'(?:パスワード|PW|pass|password)[:\s：]+([^\s,、]+)',
        ]

        member_id = None
        password = None

        for pattern in id_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                member_id = match.group(1).strip()
                break

        for pattern in pass_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                password = match.group(1).strip()
                break

        if member_id and password:
            # サービスに応じてキー名を調整
            pending_tool = self.session.context.get("pending_tool_call")
            service = pending_tool.get("skill", "") if pending_tool else ""

            if service == "amazon":
                return {"email": member_id, "password": password}
            else:
                return {"member_id": member_id, "password": password}

        # パターン2: スラッシュ区切り（12345 / mypass）
        slash_match = re.match(r'^([^\s/]+)\s*/\s*([^\s]+)$', message.strip())
        if slash_match:
            return {
                "member_id": slash_match.group(1).strip(),
                "password": slash_match.group(2).strip(),
            }

        # パターン3: 改行区切り
        lines = [l.strip() for l in message.strip().split('\n') if l.strip()]
        if len(lines) == 2:
            return {
                "member_id": lines[0],
                "password": lines[1],
            }

        # パターン4: スペース区切り（2単語のみの場合）
        words = message.strip().split()
        if len(words) == 2:
            return {
                "member_id": words[0],
                "password": words[1],
            }

        return None

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
