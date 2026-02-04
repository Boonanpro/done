"""
Visual Browser Agent

視覚ベースのブラウザ操作エージェント。
Gemini 3 Flash を使用。

スクリーンショットを見てLLMが判断し、操作を実行。
スキルが存在しない場合のフォールバックとして使用。
"""

import hashlib
import logging
import re
import time
from typing import Dict, Any, Optional, List
from datetime import datetime

import google.generativeai as genai

from app.config import settings
from app.services import learning_service
from app.executors.visual.history import ActionType, BrowserSession
from app.executors.visual.recorder import BrowserRecorder, LOGS_DIR
from app.executors.visual.actions import (
    ActionExecutor,
    ActionResult,
    VISUAL_AGENT_ACTIONS,
    get_action_type,
)
from app.services.issue_tracker import IssueTracker, Issue, IssueType

logger = logging.getLogger(__name__)

# ============================================
# モデル設定
# ============================================

# Gemini 3 Flash
VISUAL_AGENT_MODEL = "gemini-3-flash"

# 最大ステップ数（安全弁）
MAX_STEPS = 20


class VisualAgent:
    """
    視覚ベースブラウザエージェント

    スクリーンショットを見てLLMが次のアクションを決定し、
    タスクが完了するまで繰り返す。

    Usage:
        recorder = BrowserRecorder(user_id="user123")
        agent = VisualAgent(recorder=recorder)
        result = await agent.execute_task(
            task="アベンヌウォーター50mlを4本購入",
            site="amazon.co.jp",
        )
    """

    def __init__(
        self,
        recorder: Optional[BrowserRecorder] = None,
        model: str = VISUAL_AGENT_MODEL,
        max_steps: int = MAX_STEPS,
        on_thinking: Optional[callable] = None,
        on_step: Optional[callable] = None,
        on_plan: Optional[callable] = None,
    ):
        """
        Args:
            recorder: 操作記録器（省略時は新規作成）
            model: 使用するモデル
            max_steps: 最大ステップ数
            on_thinking: 思考テキストのコールバック（リアルタイム表示用）
            on_step: ステップ完了時のコールバック
            on_plan: 計画作成時のコールバック（計画内容を通知）
        """
        self.recorder = recorder or BrowserRecorder()
        self.model = model
        self.max_steps = max_steps
        self.on_thinking = on_thinking
        self.on_step_callback = on_step
        self.on_plan_callback = on_plan

        self.page = None
        self.action_executor = None

        # Gemini API の設定
        if settings.GOOGLE_GEMINI_API_KEY:
            genai.configure(api_key=settings.GOOGLE_GEMINI_API_KEY)

        # メッセージ履歴（Gemini形式）
        self.chat_history: List[Dict[str, Any]] = []

        self._total_tokens = 0
        self._prev_screenshot_hash: Optional[str] = None
        self._unchanged_screen_count = 0

    def _summarize_reasoning(self, reasoning: str, limit: int = 1200) -> str:
        """思考ログを短く整形"""
        if not reasoning:
            return ""
        reasoning = reasoning.strip()
        if len(reasoning) <= limit:
            return reasoning
        return reasoning[:limit] + "..."

    def _classify_decision(self, action_name: str, result_dict: Dict[str, Any]) -> tuple[str, str]:
        """判断方式を簡易判定"""
        selector_probes = result_dict.get("selector_probes") or []
        if selector_probes:
            for probe in selector_probes:
                if not isinstance(probe, dict):
                    continue
                if probe.get("unique") and probe.get("first_visible"):
                    if probe.get("reliability") == "high":
                        return "selector", "validated_high_reliability"
                    return "selector", "validated_selector_candidate"

            if any(p.get("reliability") == "high" for p in selector_probes if isinstance(p, dict)):
                return "visual", "high_reliability_not_unique_or_hidden"
            return "visual", "selector_candidates_not_unique"

        selectors = result_dict.get("selectors", []) or []
        has_high = any(
            isinstance(s, dict) and s.get("reliability") == "high" for s in selectors
        )

        if has_high:
            return "selector", "high_reliability_selector"

        if action_name in ("navigate", "wait", "press_key"):
            return "direct", "no_element_target"

        if action_name in ("scroll",):
            return "direct", "scroll_action"

        if selectors:
            return "visual", "selectors_low_reliability"

        return "visual", "no_selectors"

    def _get_gemini_tools(self) -> List:
        """Gemini形式のツール定義を生成"""
        function_declarations = []

        for action in VISUAL_AGENT_ACTIONS:
            # パラメータをGemini形式に変換
            properties = {}
            required = action["parameters"].get("required", [])

            for prop_name, prop_def in action["parameters"].get("properties", {}).items():
                prop_type = prop_def.get("type", "string").upper()
                if prop_type == "INTEGER":
                    prop_type = "NUMBER"
                elif prop_type == "BOOLEAN":
                    prop_type = "BOOLEAN"
                else:
                    prop_type = "STRING"

                properties[prop_name] = genai.protos.Schema(
                    type=prop_type,
                    description=prop_def.get("description", ""),
                )

            func_decl = genai.protos.FunctionDeclaration(
                name=action["name"],
                description=action["description"],
                parameters=genai.protos.Schema(
                    type="OBJECT",
                    properties=properties,
                    required=required,
                ) if properties else None,
            )
            function_declarations.append(func_decl)

        return [genai.protos.Tool(function_declarations=function_declarations)]

    def _build_gemini_content(self, text: str, screenshot_base64: Optional[str] = None) -> List[Dict[str, Any]]:
        """Gemini形式のコンテンツを構築"""
        parts = [{"text": text}]

        if screenshot_base64:
            parts.append({
                "inline_data": {
                    "mime_type": "image/png",
                    "data": screenshot_base64,
                }
            })

        return parts

    async def execute_task(
        self,
        task: str,
        site: Optional[str] = None,
        initial_url: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        credentials: Optional[Dict[str, str]] = None,
        on_step: Optional[callable] = None,
        selector_hints: Optional[str] = None,
        skill_manual: Optional[str] = None,
        skill_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        タスクを視覚ベースで実行

        Args:
            task: タスクの説明（例: "アベンヌウォーター50mlを4本購入"）
            site: 対象サイト（例: "amazon.co.jp"）
            initial_url: 開始URL（省略時はサイトから推測）
            params: 追加パラメータ
            credentials: 認証情報
            on_step: ステップごとのコールバック（後方互換性のため残す）
            selector_hints: 学習済みスキルからのセレクタヒント
            skill_manual: スキルの手順書（check_skillで取得した内容）
            skill_name: スキル名（read_manualアクションで使用）

        Returns:
            実行結果
        """
        self._selector_hints = selector_hints
        self._skill_manual = skill_manual
        from app.tools.browser import get_executor_page

        if not settings.GOOGLE_GEMINI_API_KEY:
            return {
                "success": False,
                "error": "LLM client not initialized (GOOGLE_GEMINI_API_KEY not set)",
            }

        # コールバックを設定
        if on_step:
            self.on_step_callback = on_step

        # ページを取得
        self.page = await get_executor_page()
        self.action_executor = ActionExecutor(self.page, skill_name=skill_name)

        # セッション開始
        self.recorder.start_session(task=task, site=site, model=self.model)

        # 初期URLに移動
        if initial_url:
            await self._navigate_initial(initial_url)
        elif site:
            await self._navigate_initial(f"https://{site}")

        # システムプロンプトを構築
        system_prompt = self._build_system_prompt(task, params or {}, credentials)

        # Gemini モデルを初期化（システムプロンプト付き）
        gemini_model = genai.GenerativeModel(
            model_name=self.model,
            system_instruction=system_prompt,
            tools=self._get_gemini_tools(),
        )

        # チャットセッションを開始
        chat = gemini_model.start_chat(history=[])

        # 初回のスクリーンショットを取得
        screenshot_data = await self.page.screenshot_base64()
        screenshot_base64 = screenshot_data.get("base64", "")

        # ============================================
        # Phase 1: 計画フェーズ（表示のみ、承認なし）
        # ============================================
        from app.services.cancellation import CancellationRegistry
        CancellationRegistry.check_cancelled_raise()

        plan = await self._create_plan(task, screenshot_base64, params or {})
        if plan:
            summary = plan.get("summary", "")
            steps = plan.get("steps", []) if isinstance(plan, dict) else []
            plan_lines = []
            if summary:
                plan_lines.append(summary)
            if steps:
                for i, step in enumerate(steps, 1):
                    plan_lines.append(f"{i}. {step}")
            plan_message = "\n".join(plan_lines) if plan_lines else "計画を作成"
            page_url = None
            if self.page:
                try:
                    page_url = self.page.url
                except Exception:
                    page_url = None
            self.recorder.add_event(
                event_type="plan",
                message=plan_message,
                page_url=page_url,
            )
        if plan and self.on_plan_callback:
            await self._safe_callback(self.on_plan_callback, plan)

        # ============================================
        # Phase 2: 実行フェーズ（即座に開始）
        # ============================================
        initial_message = f"以下のタスクを実行してください:\n\n{task}\n\n現在の画面を確認して、最初のアクションを決定してください。"

        # エージェントループ
        result = None
        for step_num in range(1, self.max_steps + 1):
            # キャンセルチェック
            CancellationRegistry.check_cancelled_raise()

            logger.info(f"[VisualAgent] Step {step_num}/{self.max_steps}")

            try:
                start_time = time.time()

                # メッセージを構築
                if step_num == 1:
                    # 初回メッセージ
                    content_parts = self._build_gemini_content(initial_message, screenshot_base64)
                else:
                    # tool_result を含むメッセージは既に chat.history に追加されている
                    content_parts = None

                # LLM呼び出し
                if content_parts:
                    response = await chat.send_message_async(
                        content_parts,
                        generation_config=genai.types.GenerationConfig(
                            max_output_tokens=1024,
                        ),
                    )
                else:
                    # 前のループで function_response を送信済みなので、ここでは何もしない
                    # (Geminiは自動的に次のレスポンスを返す)
                    pass

                llm_duration_ms = int((time.time() - start_time) * 1000)

                # キャンセルチェック
                CancellationRegistry.check_cancelled_raise()

                # トークン使用量を記録
                if hasattr(response, "usage_metadata"):
                    self._total_tokens += (
                        response.usage_metadata.prompt_token_count +
                        response.usage_metadata.candidates_token_count
                    )

                # 応答からアクションを抽出
                action, reasoning = self._extract_action_from_gemini(response)

                # 思考をコールバックで通知
                if reasoning and self.on_thinking:
                    await self._safe_callback(self.on_thinking, reasoning)

                if reasoning:
                    page_url = None
                    if self.page:
                        try:
                            page_url = self.page.url
                        except Exception:
                            page_url = None
                    self.recorder.add_event(
                        event_type="thinking",
                        message=self._summarize_reasoning(reasoning),
                        step_index=step_num,
                        page_url=page_url,
                    )

                if not action:
                    # テキストのみの応答（ツール呼び出しなし）= 完了
                    logger.info("[VisualAgent] No tool use in response, assuming done")
                    self.recorder.end_session(success=True)
                    result = {
                        "success": True,
                        "message": reasoning or "Task completed",
                        "steps": step_num,
                        "total_tokens": self._total_tokens,
                    }
                    break

                action_name = action.get("name", "unknown")
                action_params = action.get("params", {})

                logger.info(f"[VisualAgent] Action: {action_name}")

                # アクションを実行
                exec_start = time.time()
                action_result = await self.action_executor.execute(
                    action_name=action_name,
                    params=action_params,
                )
                exec_duration_ms = int((time.time() - exec_start) * 1000)

                # ステップを記録
                result_dict = action_result.to_dict()
                page_url = None
                if self.page:
                    try:
                        page_url = self.page.url
                    except Exception:
                        page_url = None
                if page_url:
                    result_dict["page_url"] = page_url

                decision_type, decision_reason = self._classify_decision(action_name, result_dict)

                step = self.recorder.add_step(
                    action=get_action_type(action_name),
                    params=action_params,
                    result=result_dict,
                    screenshot_base64=screenshot_base64,
                    llm_reasoning=reasoning,
                    duration_ms=llm_duration_ms + exec_duration_ms,
                    page_url=page_url,
                    decision_type=decision_type,
                    decision_reason=decision_reason,
                )

                self.recorder.add_event(
                    event_type="step",
                    message=f"Step {step.index}: {action_name} {'OK' if action_result.success else 'NG'}",
                    step_index=step.index,
                    page_url=page_url,
                )

                # 学習イベントを記録
                if action_name not in ("done", "ask_user"):
                    try:
                        context = await self._detect_context()
                        await self._record_learning_event(
                            action_name=action_name,
                            action_params=action_params,
                            action_result=action_result,
                            context=context,
                            skill_name=skill_name,
                            site=site,
                        )
                    except Exception as e:
                        logger.debug(f"[VisualAgent] Learning event recording failed: {e}")

                # ステップ完了をコールバックで通知
                if self.on_step_callback:
                    await self._safe_callback(
                        self.on_step_callback,
                        step_num,
                        action_name,
                        action_result,
                    )

                # 完了チェック
                if action_name == "done":
                    success = action_params.get("success", True)
                    message = action_params.get("message", "Task completed")
                    extracted_data = action_params.get("extracted_data", {})

                    self.recorder.end_session(success=success)
                    self.recorder.session.total_tokens = self._total_tokens

                    # 失敗時はイシューを記録
                    if not success:
                        await self._record_issue(
                            issue_type=IssueType.EXECUTION_FAILED,
                            error_message=message,
                            screenshot_base64=screenshot_base64,
                        )

                    result = {
                        "success": success,
                        "message": message,
                        "extracted_data": extracted_data,
                        "steps": step_num,
                        "total_tokens": self._total_tokens,
                    }
                    break

                # ユーザー入力が必要な場合
                if action_result.data.get("requires_user_input"):
                    self.recorder.end_session(success=False, error_message="User input required")

                    await self._record_issue(
                        issue_type=IssueType.USER_INPUT_REQUIRED,
                        error_message=action_result.message or "ユーザー入力が必要",
                        screenshot_base64=screenshot_base64,
                    )

                    result = {
                        "success": False,
                        "requires_user_input": True,
                        "question": action_result.message,
                        "options": action_result.data.get("options", []),
                        "steps": step_num,
                    }
                    break

                # 新しいスクリーンショットを取得
                screenshot_data = await self.page.screenshot_base64()
                screenshot_base64 = screenshot_data.get("base64", "")

                # 繰り返し検出
                repeat_warning = self._detect_repeat_actions(action_name, action_params)

                # function_response を送信
                result_text = action_result.message or "Action completed"
                if action_result.data:
                    result_text += f"\n\nDetails: {action_result.data}"
                if repeat_warning:
                    result_text = repeat_warning + "\n\n" + result_text

                # Gemini に function_response を送信（スクリーンショット付き）
                function_response_parts = [
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=action_name,
                            response={"result": result_text},
                        )
                    ),
                    genai.protos.Part(
                        inline_data=genai.protos.Blob(
                            mime_type="image/png",
                            data=screenshot_base64.encode() if isinstance(screenshot_base64, str) else screenshot_base64,
                        )
                    ) if screenshot_base64 else None,
                ]
                function_response_parts = [p for p in function_response_parts if p is not None]

                # 次のレスポンスを取得
                response = await chat.send_message_async(
                    function_response_parts,
                    generation_config=genai.types.GenerationConfig(
                        max_output_tokens=1024,
                    ),
                )

            except Exception as e:
                logger.error(f"[VisualAgent] Step {step_num} error: {e}", exc_info=True)

        # 最大ステップ到達
        if result is None:
            progress = self._generate_progress_summary()

            try:
                progress["summary_text"] = await self._ask_llm_for_summary(chat)
            except Exception:
                progress["summary_text"] = f"実行アクション: {', '.join(progress['actions_executed'][-5:])}"

            self.recorder.end_session(success=False, error_message="Max steps reached")

            await self._record_issue(
                issue_type=IssueType.EXECUTION_FAILED,
                error_message=f"タスクが{self.max_steps}ステップ以内に完了しませんでした",
                screenshot_base64=screenshot_base64 if 'screenshot_base64' in locals() else None,
            )

            result = {
                "success": False,
                "error": f"タスクが{self.max_steps}ステップ以内に完了しませんでした",
                "steps": self.max_steps,
                "total_tokens": self._total_tokens,
                "progress": progress,
            }

        # ログを保存
        await self.recorder.save()

        return result

    def _extract_action_from_gemini(self, response) -> tuple[Optional[Dict[str, Any]], str]:
        """
        Geminiレスポンスからアクション情報を抽出

        Returns:
            (action, reasoning) のタプル
            - action: {"name": ..., "params": ...} またはNone
            - reasoning: LLMの思考テキスト
        """
        reasoning = ""
        action = None

        if not response.candidates:
            return None, ""

        candidate = response.candidates[0]
        if not candidate.content or not candidate.content.parts:
            return None, ""

        for part in candidate.content.parts:
            if hasattr(part, "text") and part.text:
                reasoning = part.text

            if hasattr(part, "function_call") and part.function_call:
                func_call = part.function_call
                action = {
                    "name": func_call.name,
                    "params": dict(func_call.args) if func_call.args else {},
                }
                break

        return action, reasoning

    async def _safe_callback(self, callback: callable, *args) -> None:
        """コールバックを安全に実行（同期/非同期両対応）"""
        import asyncio
        try:
            result = callback(*args)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.warning(f"[VisualAgent] Callback error: {e}")

    async def _navigate_initial(self, url: str) -> None:
        """初期URLに移動"""
        await self.page.goto(url)
        await self.page.wait_for_timeout(3000)

        screenshot_data = await self.page.screenshot_base64()
        self.recorder.add_step(
            action=ActionType.NAVIGATE,
            params={"url": url},
            result={"success": True, "current_url": self.page.url},
            screenshot_base64=screenshot_data.get("base64", ""),
        )

    async def _create_plan(
        self,
        task: str,
        screenshot_base64: str,
        params: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        タスクの実行計画を作成
        """
        planning_prompt = f"""あなたはブラウザを操作するAIエージェントの計画担当です。

# タスク
{task}

# 指示
このタスクを完了するための手順を簡潔に箇条書きで作成してください。
各ステップは具体的で実行可能なものにしてください。

# 出力形式（厳守）
以下のJSON形式で出力してください:
{{
  "summary": "タスクの要約（1行）",
  "steps": [
    "ステップ1の説明",
    "ステップ2の説明",
    ...
  ]
}}
"""

        try:
            # 計画用に別のモデルインスタンスを使用（ツールなし）
            planning_model = genai.GenerativeModel(model_name=self.model)

            content_parts = self._build_gemini_content(planning_prompt, screenshot_base64)

            response = await planning_model.generate_content_async(
                content_parts,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=512,
                ),
            )

            # トークン使用量を記録
            if hasattr(response, "usage_metadata"):
                self._total_tokens += (
                    response.usage_metadata.prompt_token_count +
                    response.usage_metadata.candidates_token_count
                )

            # レスポンスをパース
            import json
            text = response.text if hasattr(response, "text") else ""

            # JSONを抽出
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            plan = json.loads(text.strip())
            logger.info(f"[VisualAgent] Plan created: {plan.get('summary', '')}")
            return plan

        except Exception as e:
            logger.warning(f"[VisualAgent] Failed to create plan: {e}")
            return None

    def _build_system_prompt(self, task: str, params: Dict[str, Any], credentials: Optional[Dict[str, str]] = None) -> str:
        """システムプロンプトを構築"""
        params_str = ""
        if params:
            params_lines = [f"  - {k}: {v}" for k, v in params.items()]
            params_str = "\n" + "\n".join(params_lines)

        hints_section = ""
        if hasattr(self, "_selector_hints") and self._selector_hints:
            hints_section = f"""

# 学習済みセレクタ情報（過去の成功操作から）
以下は過去に成功した操作で使用されたセレクタです。参考にしてください：

```
{self._selector_hints}
```

※ これらは参考情報です。実際のページを見て判断してください。
"""

        credentials_section = ""
        if credentials and (credentials.get("id") or credentials.get("password")):
            credentials_section = f"""

# 認証情報
ログインが必要な場合は以下を使用してください：
- メールアドレス/ユーザーID: {credentials.get('id', '（未設定）')}
- パスワード: {credentials.get('password', '（未設定）')}

※ ユーザーに認証情報を聞く必要はありません。上記を使用してください。
"""

        skill_manual_section = ""
        if hasattr(self, "_skill_manual") and self._skill_manual:
            skill_manual_section = f"""

# スキル手順書
以下はこのタスクの手順書です。参考にして実行してください：

---
{self._skill_manual}
---

※ 手順書通りにいかない場合は `ask_user` でユーザーに確認してください。
"""

        return f"""あなたはブラウザを操作するAIエージェントです。

# タスク
{task}{params_str}

# 画面情報
- 解像度: 1024x768 ピクセル
- 座標系: 左上が (0, 0)、右下が (1024, 768)

# 指示
1. スクリーンショットを見て、タスクを完了するために必要な次のアクションを1つ決定してください
2. 画面上の要素の位置を確認し、適切なアクションを選択してください
3. タスクが完了したら、必ず `done` アクションを呼び出してください

# 重要なルール
- 一度に1つのアクションのみ実行
- **座標指定を優先**（CSSセレクタは使わない）

# 最重要：ユーザーに確認を求める（ask_user）
**困った時は必ずユーザーに聞く。勝手に判断しない。**

以下の場合は `ask_user` でユーザーに確認を求めること：
- エラーが表示された
- 予期しないページに遷移した
- 目的の要素が見つからない
- 同じ操作を2回試しても失敗する
- サイトを切り替えるか迷う
- ログインや認証が必要
- 複数の選択肢がある（どの商品を選ぶか等）

# 決済・送信の最終確定ボタンは押さない
「注文を確定」「購入する」「今すぐ買う」「送信する」「申込を確定」等の
最終確定ボタンは、クリックせずに `done` で現在の状態を報告すること。
メインエージェントの承認を得てから実行する。

**絶対にしてはいけないこと：**
- ユーザーに聞かずに別のサイトに切り替える
- エラーを無視して強引に続行する
- 勝手にタスクを諦める

# テキスト入力の手順（必ずこの順序で）
1. 入力欄を `click` でクリック → フォーカスが当たる
2. **次のステップで** `type` を使って文字を入力
3. 必要なら press_enter: true で Enter を押す

# ポップアップ対策
ポップアップやモーダルが表示された場合：
1. まず `press_key` で Escape キーを押す（最も確実）
2. 2回試しても閉じない場合は `ask_user` でユーザーに対処法を聞く

# 繰り返し禁止ルール
同じ操作を2回試して失敗したら、`ask_user` でユーザーに聞く。
自分で判断せず、ユーザーと一緒に問題を解決する。

# 現在の日時
{datetime.now().strftime('%Y年%m月%d日 %H:%M')}
{hints_section}{credentials_section}{skill_manual_section}"""

    def _detect_repeat_actions(
        self,
        action_name: str,
        action_params: Dict[str, Any],
    ) -> Optional[str]:
        """
        繰り返しアクションを検出して警告を生成
        """
        # TODO: Gemini形式のhistoryから過去のアクションを抽出して実装
        # 現時点では簡略化
        return None

    def _generate_progress_summary(self) -> Dict[str, Any]:
        """
        実行した操作のサマリを生成
        """
        actions = []
        if self.recorder and self.recorder.session:
            for step in self.recorder.session.steps:
                action_val = step.action.value if hasattr(step.action, 'value') else str(step.action)
                if action_val != "done":
                    actions.append(action_val)

        steps_detail = []
        if self.recorder and self.recorder.session:
            for step in self.recorder.session.steps:
                steps_detail.append({
                    "action": step.action.value if hasattr(step.action, 'value') else str(step.action),
                    "success": step.result.get("success", True),
                    "url": step.page_url,
                })

        return {
            "actions_executed": actions[-10:],
            "steps_detail": steps_detail[-10:],
            "total_steps": len(actions),
        }

    async def _ask_llm_for_summary(self, chat) -> str:
        """
        LLMに今まで何をしたかを要約させる
        """
        summary_prompt = """
これまでの操作を日本語で簡潔に要約してください。
- 完了した操作
- 未完了の操作（もしあれば）
- 現在の画面状態

フォーマット:
【完了】〇〇、△△
【未完了】□□
【現在】××ページを表示中
"""
        try:
            response = await chat.send_message_async(
                summary_prompt,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=500,
                ),
            )
            return response.text
        except Exception as e:
            logger.warning(f"[VisualAgent] Failed to generate LLM summary: {e}")
            return ""

    # ============================================
    # 学習データ収集機能
    # ============================================

    async def _detect_context(self) -> Dict[str, Any]:
        """
        現在のページからコンテキスト情報を検出
        """
        context = {}

        if not self.page:
            return context

        try:
            context["page_url"] = self.page.url

            url = self.page.url.lower()
            if "/cart" in url or "/gp/cart" in url:
                context["page_type"] = "cart"
            elif "/search" in url or "/s?" in url or "keywords=" in url:
                context["page_type"] = "search_results"
            elif "/dp/" in url or "/product" in url:
                context["page_type"] = "product_detail"
            elif "/order" in url or "/history" in url:
                context["page_type"] = "order_history"
            elif "login" in url or "signin" in url or "ap/signin" in url:
                context["page_type"] = "login"
            else:
                context["page_type"] = "other"

            logged_in = await self._detect_logged_in_state()
            if logged_in is not None:
                context["logged_in"] = logged_in

            cart_count = await self._detect_cart_count()
            if cart_count is not None:
                context["cart_count"] = cart_count

        except Exception as e:
            logger.warning(f"[VisualAgent] Failed to detect context: {e}")

        return context

    async def _detect_logged_in_state(self) -> Optional[bool]:
        """
        ログイン状態を検出
        """
        if not self.page:
            return None

        try:
            url = self.page.url.lower()

            if "amazon" in url:
                nav_text = await self.page.evaluate('''() => {
                    const navLink = document.querySelector('#nav-link-accountList');
                    return navLink ? navLink.innerText : '';
                }''')
                if nav_text:
                    if "ログイン" in nav_text or "サインイン" in nav_text:
                        return False
                    elif "さん" in nav_text or "アカウント" in nav_text:
                        return True

            elif "rakuten" in url:
                header_text = await self.page.evaluate('''() => {
                    const header = document.querySelector('.header-user-nav, .my-info');
                    return header ? header.innerText : '';
                }''')
                if header_text:
                    if "ログイン" in header_text:
                        return False
                    elif "さん" in header_text or "マイページ" in header_text:
                        return True

            else:
                page_text = await self.page.evaluate('''() => {
                    const body = document.body;
                    return body ? body.innerText.slice(0, 3000) : '';
                }''')
                if "ログイン" in page_text and "ログアウト" not in page_text:
                    return False
                elif "ログアウト" in page_text or "マイページ" in page_text:
                    return True

        except Exception as e:
            logger.debug(f"[VisualAgent] Failed to detect logged_in state: {e}")

        return None

    async def _detect_cart_count(self) -> Optional[int]:
        """
        カート内の商品数を検出
        """
        if not self.page:
            return None

        try:
            url = self.page.url.lower()

            if "amazon" in url:
                count_text = await self.page.evaluate('''() => {
                    const cartCount = document.querySelector('#nav-cart-count');
                    return cartCount ? cartCount.innerText.trim() : '';
                }''')
                if count_text and count_text.isdigit():
                    return int(count_text)

            elif "rakuten" in url:
                count_text = await self.page.evaluate('''() => {
                    const cartBadge = document.querySelector('.cart-badge, .cart-count');
                    return cartBadge ? cartBadge.innerText.trim() : '';
                }''')
                if count_text:
                    match = re.search(r'\d+', count_text)
                    if match:
                        return int(match.group())

        except Exception as e:
            logger.debug(f"[VisualAgent] Failed to detect cart count: {e}")

        return None

    async def _record_learning_event(
        self,
        action_name: str,
        action_params: Dict[str, Any],
        action_result: "ActionResult",
        context: Dict[str, Any],
        skill_name: Optional[str] = None,
        site: Optional[str] = None,
    ) -> None:
        """
        アクション実行結果を学習イベントとして記録
        """
        try:
            session_id = ""
            browser_session_id = None

            if self.recorder and self.recorder.session:
                browser_session_id = self.recorder.session.id
                session_id = getattr(self.recorder, "agent_session_id", browser_session_id)

            user_id = self.recorder.user_id if self.recorder else None

            await learning_service.record_action_event(
                session_id=session_id or browser_session_id or "unknown",
                action_name=action_name,
                technical_success=action_result.success,
                context=context,
                user_id=user_id,
                browser_session_id=browser_session_id,
                site=site,
                skill_name=skill_name,
                action_params=action_params,
            )

            logger.debug(f"[VisualAgent] Recorded learning event: {action_name} on {site}")

        except Exception as e:
            logger.warning(f"[VisualAgent] Failed to record learning event: {e}")

    # ============================================
    # イシュー記録機能
    # ============================================

    async def _record_issue(
        self,
        issue_type: IssueType,
        error_message: str,
        screenshot_base64: str = None,
        fallback_action: str = None,
    ) -> None:
        """
        エラー発生時にイシューを記録
        """
        try:
            screenshot_path = None
            if screenshot_base64:
                screenshot_path = await self._save_screenshot_for_issue(screenshot_base64)

            html_path = await self._save_html_snapshot()

            page_url = None
            if self.page:
                try:
                    page_url = self.page.url
                except Exception:
                    pass

            task = self.recorder.session.task if self.recorder.session else "不明なタスク"
            site = self.recorder.session.site if self.recorder.session else None
            user_id = self.recorder.user_id

            issue = Issue(
                issue_type=issue_type,
                original_wish=task,
                service_type="visual_browse",
                service_name=site,
                research_result={},
                error_message=error_message,
                error_details={
                    "step_count": self._step_index if hasattr(self, '_step_index') else 0,
                    "model": self.model,
                },
                user_id=user_id,
                screenshots=[screenshot_path] if screenshot_path else [],
                html_snapshot_path=html_path,
                page_url=page_url,
                fallback_action=fallback_action,
            )

            tracker = IssueTracker()
            issue_id = await tracker.record_issue(issue)
            logger.info(f"[VisualAgent] Issue recorded: {issue_id} ({issue_type.value})")

        except Exception as e:
            logger.error(f"[VisualAgent] Failed to record issue: {e}")

    async def _save_screenshot_for_issue(self, screenshot_base64: str) -> str:
        """
        イシュー用にスクリーンショットを保存
        """
        import base64
        from pathlib import Path

        try:
            session_id = self.recorder.session.id if self.recorder.session else "unknown"
            session_dir = LOGS_DIR / session_id / "issues"
            session_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"issue_{timestamp}.png"
            filepath = session_dir / filename

            image_data = base64.b64decode(screenshot_base64)
            with open(filepath, "wb") as f:
                f.write(image_data)

            return f"{session_id}/issues/{filename}"

        except Exception as e:
            logger.error(f"[VisualAgent] Failed to save screenshot for issue: {e}")
            return None

    async def _save_html_snapshot(self) -> str:
        """
        現在のページのHTMLスナップショットを保存
        """
        from pathlib import Path

        if not self.page:
            return None

        try:
            html_content = await self.page.content()

            session_id = self.recorder.session.id if self.recorder.session else "unknown"
            session_dir = LOGS_DIR / session_id / "issues"
            session_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"snapshot_{timestamp}.html"
            filepath = session_dir / filename

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_content)

            return f"{session_id}/issues/{filename}"

        except Exception as e:
            logger.error(f"[VisualAgent] Failed to save HTML snapshot: {e}")
            return None
