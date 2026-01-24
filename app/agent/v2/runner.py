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
from app.agent.v2.tools import parse_tool_call, execute_tool, format_tool_result, FormattedToolResult, SkillRegistry
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

                    # 結果をセッションに追加（Vision API対応）
                    formatted = format_tool_result(
                        result, pending_tool["skill"], pending_tool["action"]
                    )
                    if formatted.has_images():
                        # 画像があればVision形式で追加
                        self.session.add_user_message_with_images(
                            formatted.text, formatted.images
                        )
                    else:
                        self.session.add_user_message(formatted.text)

                    # LLMに結果を伝えて応答を生成
                    llm_response = await self._call_llm()
                    parsed = self._parse_response(llm_response)
                    if parsed["new_state"]:
                        self.session.transition_to(parsed["new_state"])
                    self.session.add_assistant_message(llm_response)

                    store = get_session_store()
                    await store.save(self.session)

                    return {
                        "response": parsed["user_response"],
                        "state": self.session.current_state.value,
                        "reasoning_steps": self.session.reasoning_steps,
                        "tool_results": [{"tool": pending_tool, "result": result}],
                    }

            # 1. 推論ステップをクリア（新しいターン）
            self.session.clear_reasoning_steps()

            # 2. ユーザーメッセージを追加
            self.session.add_user_message(user_message)

            # 3. LLM呼び出し→ツール実行ループ
            tool_results = []
            print(f"[RUNNER_DEBUG] Starting LLM loop, state: {self.session.current_state.value}")

            # 状態に応じた上限を決定
            if self.session.current_state == State.DEVELOP:
                max_loops = MAX_TOOL_LOOPS_DEVELOP
            else:
                max_loops = MAX_TOOL_LOOPS_SAFETY  # 実質上限なし（LLMが自然に終了）

            for loop_count in range(max_loops + 1):
                # LLMを呼び出し
                print(f"[RUNNER_DEBUG] Calling LLM (loop {loop_count})...")
                llm_response = await self._call_llm()
                print(f"[RUNNER_DEBUG] LLM response length: {len(llm_response)}")

                # レスポンスを解析
                parsed = self._parse_response(llm_response)

                # 状態遷移を検出・適用
                if parsed["new_state"]:
                    self.session.transition_to(parsed["new_state"])

                # アシスタントメッセージを追加
                self.session.add_assistant_message(llm_response)

                # ツール呼び出しを検出
                tool_call = parse_tool_call(llm_response)

                if not tool_call or loop_count >= max_loops:
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

                # エラータイプに基づいて処理を分岐
                error_type = result.get("error_type")

                # 認証情報が必要な場合は特別処理
                # credentials_required または認証関連のerror_typeの場合
                if result.get("credentials_required") or error_type in (
                    "credentials_required",
                    "credentials_invalid",
                    "session_expired",
                ):
                    # 保留中のツール呼び出しを保存
                    self.session.context["pending_tool_call"] = tool_call

                    # ユーザーに認証情報を要求
                    display_name = result.get("display_name", result.get("service"))
                    labels = result.get("labels", {})

                    # フィールドのラベルを取得
                    field_prompts = []
                    for field in result.get("fields", []):
                        label = labels.get(field, field)
                        field_prompts.append(f"・{label}")

                    prompt_text = f"{display_name}を利用するには認証情報が必要です。\n\n以下の情報を教えてください:\n" + "\n".join(field_prompts)

                    # セッションを保存
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

                # その他のエラー: 実際のエラーメッセージをLLMに伝える
                # error_typeがあれば、それをログに記録
                if error_type and not result.get("success"):
                    logger.info(f"Tool error: type={error_type}, recoverable={result.get('recoverable', True)}")

                tool_results.append({
                    "tool": tool_call,
                    "result": result,
                })

                # 結果をMessagesに追加（userロールで追加してLLMに伝える）
                # Vision API対応: 画像があればcontent blocks形式で追加
                formatted = format_tool_result(
                    result, tool_call["skill"], tool_call["action"]
                )
                if formatted.has_images():
                    # 画像があればVision形式で追加（ダンが画面を見られる）
                    self.session.add_user_message_with_images(
                        formatted.text, formatted.images
                    )
                    logger.info(f"[VISION] Added {len(formatted.images)} image(s) to message")
                else:
                    self.session.add_user_message(formatted.text)

                if self._on_reasoning_step:
                    status = "✅" if result.get("success") else "❌"
                    vision_indicator = " 👁️" if formatted.has_images() else ""
                    await self._on_reasoning_step(f"{status} ツール実行完了{vision_indicator}")

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

### 内部処理は必ず [STEP] で囲む

以下のような内部処理は、必ず `[STEP]` で始める:
- 「〜を確認します」 → `[STEP] 〜を確認します`
- 「〜を実行します」 → `[STEP] 〜を実行します`
- 「〜を探します」 → `[STEP] 〜を探します`

**[STEP] なしで書くと、ユーザーに見えてしまう。**

### 絶対に書いてはいけない表現

以下は [STEP] 付きでも禁止:
- 「ツール実行:」「ツールを実行」
- 「回答を作成」
- 「スクリーンショットを見ると」
- 「画面をスクロールして」
"""

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

            # SKILL.mdからアクション情報を抽出
            actions = self._extract_actions_from_skill(skill.raw_content)
            if actions:
                lines.append(f"- 利用可能なアクション: {', '.join(actions)}")

            lines.append(f"- 説明: {skill.description[:100]}...")
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

    async def _call_llm(self) -> str:
        """LLMを呼び出す（ストリーミング）"""
        if not self.llm_client:
            return "[STATE: CHAT]\nLLMクライアントが設定されていません。"

        messages = self.session.get_messages_for_llm()
        system_prompt = self._build_system_prompt()
        model = self._get_model()

        full_response = ""
        current_line = ""

        try:
            async with self.llm_client.messages.stream(
                model=model,
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

    # 内部処理パターン（[STEP] なしで出力された場合にフィルタ）
    # セーフティネット: LLMがルール違反した場合の最後の防壁
    # 注意: パターンは短い単純な行のみにマッチするよう制限
    #       長い文章（句点を含む複文）は正当なコンテンツの可能性が高い
    INTERNAL_PATTERNS = [
        # 完全に単独の内部処理行のみ（。や、を含まない短い行）
        re.compile(r'^[^。、]{0,15}を確認します$'),  # 15文字以下で「〜を確認します」
        re.compile(r'^[^。、]{0,15}を実行します$'),  # 15文字以下で「〜を実行します」
        re.compile(r'^[^。、]{0,15}を探します$'),    # 15文字以下で「〜を探します」
        # 明らかに内部的な表現（行頭のみ）
        re.compile(r'^ツール実行[:：]'),
        re.compile(r'^回答を作成'),
    ]

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """
        LLMのレスポンスを解析

        内部制御情報を除外してユーザー向け応答のみを抽出:
        - [STATE: XXX] → 状態遷移として処理、ユーザーには非表示
        - [STEP] XXX → 推論過程として記録、ユーザーには非表示
        - [TOOL: xxx action] + パラメータ → ツール呼び出しとして処理、ユーザーには非表示
        - コードブロック内のツール呼び出し → プロンプト例コピーの可能性、除外
        - 内部処理パターン（セーフティネット） → LLMがルール違反した場合の防壁

        Returns:
            {
                "new_state": 新しい状態（あれば）,
                "steps": [STEP]の内容リスト,
                "user_response": ユーザーに見せる部分,
            }
        """
        new_state = None
        steps = []
        user_lines = []

        lines = response.split("\n")
        i = 0
        n = len(lines)

        while i < n:
            line = lines[i]
            stripped = line.strip()

            # 1. [STATE: XXX] を検出
            state_match = re.match(r'\[STATE:\s*(\w+)\]', stripped)
            if state_match:
                state_name = state_match.group(1).lower()
                try:
                    new_state = State(state_name)
                except ValueError:
                    pass
                i += 1
                continue

            # 2. [STEP] を検出
            if stripped.startswith("[STEP]"):
                step_text = stripped[6:].strip()
                if step_text:
                    steps.append(step_text)
                i += 1
                continue

            # 3. ``` + [TOOL:] パターン（コードブロック内のツール呼び出し）
            if stripped == "```":
                # 次の行を先読みしてツール呼び出しかチェック
                if i + 1 < n and re.match(r'\[TOOL:\s*\S+\s+\w+\]', lines[i + 1].strip()):
                    # ツールブロック: 閉じる ``` まで全てスキップ
                    i += 2  # ``` と [TOOL:] をスキップ
                    while i < n:
                        if lines[i].strip() == "```":
                            i += 1  # 閉じる ``` をスキップ
                            break
                        i += 1
                    continue
                # 通常のコードブロック: そのまま出力
                user_lines.append(line)
                i += 1
                continue

            # 4. [TOOL: xxx action] を直接検出
            if re.match(r'\[TOOL:\s*\S+\s+\w+\]', stripped):
                i += 1
                # パラメータ行をスキップ（key: value 形式）
                while i < n:
                    param_line = lines[i].strip()
                    # 空行で終了（空行自体もスキップ）
                    if param_line == "":
                        i += 1
                        break
                    # パラメータ形式でなければ終了
                    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*:\s*.+$', param_line):
                        break  # この行は次のループで処理
                    i += 1
                continue

            # 5. セーフティネット: 内部処理パターンをフィルタ（短い単純な行のみ）
            if stripped and any(pattern.match(stripped) for pattern in self.INTERNAL_PATTERNS):
                logger.debug(f"Filtered internal pattern: {stripped}")
                i += 1
                continue

            # 6. その他: ユーザー向け応答
            user_lines.append(line)
            i += 1

        # ユーザー向け応答を整形
        user_response = "\n".join(user_lines).strip()

        # 連続する空行を1つにまとめる（フィルタリング後の整形）
        user_response = re.sub(r'\n{3,}', '\n\n', user_response)

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
