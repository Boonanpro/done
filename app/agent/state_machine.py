"""
State Machine - 状態機械を駆動するメインロジック

新しいアーキテクチャ：
1. 状態機械で固定の遷移
2. 各状態でLLMを呼び出し
3. Executorで実行
4. Criticで評価

既存のagent.pyとは独立して動作し、段階的に移行する。
"""
import json
import logging
from typing import Optional, Any, AsyncIterator

import anthropic

from app.agent.states import AgentState, State
from app.agent.prompts import (
    get_intake_prompt,
    get_plan_prompt,
    get_research_prompt,
    get_propose_prompt,
    get_confirm_prompt,
    get_verify_prompt,
    get_report_prompt,
)
from app.config import settings

logger = logging.getLogger(__name__)

# 利用可能な情報源
TOOL_TYPES = {
    "none": "検索不要（LLMの知識で回答）",
    "web_search": "Web検索（Tavily + Jina）",
    "ex_reservation": "EX予約（新幹線）",
    "amazon": "Amazon",
    "rakuten": "楽天",
    "highway_bus": "高速バス",
}


class StateMachine:
    """
    状態機械を駆動するクラス
    
    使い方:
        sm = StateMachine(session_id="xxx", user_id="yyy")
        result = await sm.process_message("新大阪から博多まで行きたい")
        
    SSEストリーミング:
        sm = StateMachine(session_id="xxx", user_id="yyy", on_reasoning_step=callback)
        # callbackは async def callback(step: str) の形式
    """
    
    def __init__(
        self,
        session_id: str,
        user_id: str,
        llm_client: Optional[Any] = None,
        on_reasoning_step: Optional[Any] = None,  # コールバック関数
        existing_state: Optional[AgentState] = None,  # 既存セッションから復元
    ):
        # 既存セッションがあれば復元、なければ新規作成
        if existing_state:
            self.state = existing_state
            logger.info(f"Restored existing session {session_id} (state: {existing_state.current_state.value})")
        else:
            self.state = AgentState(session_id=session_id, user_id=user_id)
            logger.info(f"Created new session {session_id}")

        self._on_reasoning_step = on_reasoning_step  # SSE用コールバック

        # LLMクライアント（渡されなければ自動生成）
        if llm_client:
            self.llm_client = llm_client
        elif settings.ANTHROPIC_API_KEY:
            self.llm_client = anthropic.AsyncAnthropic(
                api_key=settings.ANTHROPIC_API_KEY
            )
        else:
            self.llm_client = None
            logger.warning("ANTHROPIC_API_KEY not set, LLM calls will return mock responses")
    
    async def _add_reasoning_step(self, step: str) -> None:
        """推論ステップを追加し、コールバックがあれば呼び出す"""
        import asyncio
        self.state.add_reasoning_step(step)
        if self._on_reasoning_step:
            await self._on_reasoning_step(step)
            # SSEが即座に送信されるよう、小さな遅延を入れる
            await asyncio.sleep(0.05)
    
    async def process_message(self, message: str) -> dict[str, Any]:
        """
        ユーザーメッセージを処理し、次の状態に遷移
        
        Returns:
            {
                "state": 現在の状態,
                "response": ユーザーへの応答,
                "reasoning_steps": 推論過程,
                "needs_confirmation": 承認が必要か,
                "error": エラーがあれば,
            }
        """
        try:
            current = self.state.current_state
            
            if current == State.INTAKE:
                return await self._process_intake(message)
            
            elif current == State.PLAN:
                return await self._process_plan()
            
            elif current == State.RESEARCH:
                return await self._process_research()
            
            elif current == State.PROPOSE:
                return await self._process_propose()
            
            elif current == State.CONFIRM:
                return await self._process_confirm(message)
            
            elif current == State.EXECUTE:
                return await self._process_execute()
            
            elif current == State.VERIFY:
                return await self._process_verify()
            
            elif current == State.REPORT:
                return await self._process_report()
            
            else:
                return {
                    "state": current.value,
                    "error": f"Unknown state: {current}",
                }
        
        except Exception as e:
            logger.exception(f"Error in state machine: {e}")
            self.state.error = str(e)
            return {
                "state": State.ERROR.value,
                "error": str(e),
            }
        finally:
            # セッションを保存
            await self._save_session()
    
    async def _process_intake(self, message: str) -> dict[str, Any]:
        """INTAKE: ユーザーの要望を構造化"""
        await self._add_reasoning_step("ユーザーの要望を分析しています...")

        # 会話履歴を取得（文脈理解のため）
        conversation_history = await self._get_conversation_history(limit=10)

        # 前回の状態情報を準備
        previous_state = {
            "current_state": self.state.current_state.value,
            "intake_result": self.state.intake_result,
            "research_result": self.state.research_result,
        }

        # DEBUG: セッション状態を確認
        logger.warning(f"[DEBUG] Session ID: {self.state.session_id}")
        logger.warning(f"[DEBUG] research_result: {self.state.research_result}")
        logger.warning(f"[DEBUG] credentials_required: {self.state.research_result.get('credentials_required') if self.state.research_result else None}")

        # LLMを呼び出して要望を構造化（ストリーミングで[STEP]がリアルタイム送信される）
        prompt = get_intake_prompt(message, self.state.user_preferences, conversation_history, previous_state)
        llm_response = await self._call_llm(prompt)

        # レスポンスをパース
        intake_result = self._parse_json_response(llm_response)

        # task_typeを取得
        task_type = intake_result.get("task_type", "other")
        
        # reasoning_stepsをマージ
        if "reasoning_steps" in intake_result:
            for step in intake_result["reasoning_steps"]:
                await self._add_reasoning_step(step)

        # ========================================
        # follow_up: 前回の情報不足を解消
        # ========================================
        if task_type == "follow_up":
            # 前回のintake_resultに新しい情報をマージ
            if self.state.intake_result:
                previous_details = self.state.intake_result.get("details", {})
                new_details = intake_result.get("details", {})
                merged_details = {**previous_details, **new_details}
                self.state.intake_result["details"] = merged_details
                logger.info(f"Merged details: {merged_details}")
            else:
                self.state.intake_result = intake_result

            # 必須情報が揃ったか確認
            if self._has_sufficient_info():
                await self._add_reasoning_step("→ 必須情報が揃いました。計画を立てます")
                self.state.transition_to(State.PLAN)
                return await self._process_plan()
            else:
                # まだ不足
                missing = self._get_missing_info_str()
                await self._add_reasoning_step(f"→ まだ{missing}が不足しています")
                return {
                    "state": State.INTAKE.value,
                    "response": f"{missing}を教えてください。",
                    "reasoning_steps": self.state.reasoning_steps,
                }

        # ========================================
        # credentials_providing: 認証情報の提供
        # ========================================
        if task_type == "credentials_providing":
            credentials = intake_result.get("credentials", {})
            member_id = credentials.get("member_id")
            password = credentials.get("password")

            if not member_id or not password:
                await self._add_reasoning_step("→ 認証情報が不完全です")
                return {
                    "state": State.INTAKE.value,
                    "response": "会員IDとパスワードの両方を教えてください。",
                    "reasoning_steps": self.state.reasoning_steps,
                }

            # 前回のresearch_resultから、どのExecutorの認証情報が必要だったかを取得
            executor_name = self.state.research_result.get("executor_name")
            if not executor_name:
                await self._add_reasoning_step("→ 認証情報を保存するExecutorが不明です")
                return {
                    "state": State.INTAKE.value,
                    "response": "認証情報の保存に失敗しました。もう一度最初からお試しください。",
                    "reasoning_steps": self.state.reasoning_steps,
                }

            # credentials_serviceで保存
            await self._add_reasoning_step(f"→ {executor_name}の認証情報を保存しています...")
            from app.services.credentials_service import get_credentials_service
            creds_service = get_credentials_service()

            try:
                await creds_service.save_credential(
                    user_id=self.state.user_id,
                    service=executor_name,
                    credentials={
                        "member_id": member_id,
                        "password": password,
                    },
                )
                await self._add_reasoning_step("→ 認証情報を保存しました")
            except Exception as e:
                logger.exception(f"Failed to save credentials: {e}")
                await self._add_reasoning_step(f"→ 認証情報の保存に失敗: {e}")
                return {
                    "state": State.INTAKE.value,
                    "response": "認証情報の保存に失敗しました。もう一度お試しください。",
                    "reasoning_steps": self.state.reasoning_steps,
                }

            # 認証情報保存成功 → PLANからやり直す（既にplan_resultがあるはず）
            if self.state.plan_result:
                await self._add_reasoning_step("→ 認証情報が揃ったので検索を再開します")
                self.state.transition_to(State.RESEARCH)
                return await self._process_research()
            else:
                # plan_resultがない場合はINTAKEから
                await self._add_reasoning_step("→ 認証情報が揃いました。計画を立てます")
                self.state.transition_to(State.PLAN)
                return await self._process_plan()

        # 雑談・質問の場合は状態機械を抜ける
        if task_type == "other":
            # 検索が必要かどうかを確認
            requires_search = intake_result.get("requires_search", False)
            search_results = None
            
            if requires_search:
                search_query = intake_result.get("search_query", "")
                if search_query:
                    await self._add_reasoning_step(f"→ 検索中: {search_query}")
                    search_results = await self._call_web_search(search_query)
                    if search_results:
                        await self._add_reasoning_step("→ 検索結果を元に回答します")
                    else:
                        await self._add_reasoning_step("→ 検索結果が見つかりませんでした")
            
            if not requires_search:
                await self._add_reasoning_step("→ 通常の会話として応答します")

            return await self._respond_as_chat(message, search_results=search_results)

        # ========================================
        # 新しいタスク (travel, purchase等)
        # ========================================
        self.state.intake_result = intake_result

        # 必須情報チェック（PLANに進む前に）
        if not self._has_sufficient_info():
            missing = self._get_missing_info_str()
            await self._add_reasoning_step(f"→ {missing}が不足しています")
            return {
                "state": State.INTAKE.value,
                "response": f"{missing}を教えてください。",
                "reasoning_steps": self.state.reasoning_steps,
            }

        # 次の状態へ
        self.state.transition_to(State.PLAN)

        # PLANも続けて実行
        return await self._process_plan()
    
    async def _process_plan(self) -> dict[str, Any]:
        """PLAN: サブタスク分解"""
        await self._add_reasoning_step("実行計画を立てています...")
        
        # 過去の実行履歴があれば渡す（失敗したツールを避けるため）
        prompt = get_plan_prompt(
            self.state.intake_result,
            execution_history=self.state.execution_history,
        )
        llm_response = await self._call_llm(prompt)
        
        plan_result = self._parse_json_response(llm_response)
        self.state.plan_result = plan_result
        
        if "reasoning_steps" in plan_result:
            for step in plan_result["reasoning_steps"]:
                await self._add_reasoning_step(step)
        
        # 次の状態へ
        self.state.transition_to(State.RESEARCH)
        
        # RESEARCHも続けて実行
        return await self._process_research()
    
    async def _process_research(self) -> dict[str, Any]:
        """RESEARCH: 情報収集（ツールに応じて分岐）"""
        await self._add_reasoning_step("情報を収集しています...")

        # 使用するツールを特定
        tools = self.state.plan_result.get("tools", [])
        search_results = []
        credentials_required_executor = None  # 認証情報が必要なExecutor

        for tool in tools:
            if tool == "none":
                # 検索不要
                await self._add_reasoning_step("→ LLMの知識で回答します")
                continue

            elif tool == "web_search":
                # Tavily検索 + Jinaでページ内容取得
                await self._add_reasoning_step("→ Web検索を実行中...")
                try:
                    result = await self._call_web_search()
                    if result:
                        search_results.append(result)
                        self.state.add_execution_record(
                            tool="web_search",
                            action="search",
                            success=True,
                            result={"count": len(result.get("results", []))},
                        )
                    else:
                        self.state.add_execution_record(
                            tool="web_search",
                            action="search",
                            success=False,
                            error="検索結果が空でした",
                        )
                except Exception as e:
                    self.state.add_execution_record(
                        tool="web_search",
                        action="search",
                        success=False,
                        error=str(e),
                    )
                    await self._add_reasoning_step(f"→ Web検索に失敗: {e}")

            else:
                # Executor.search()
                await self._add_reasoning_step(f"→ {tool}で検索中...")
                try:
                    result = await self._call_executor_search(tool)
                    if result:
                        # 認証情報が必要な場合を検知
                        if result.get("error") == "credentials_required":
                            credentials_required_executor = tool
                            await self._add_reasoning_step(f"→ {tool}の認証情報が必要です")
                            self.state.add_execution_record(
                                tool=tool,
                                action="search",
                                success=False,
                                error="credentials_required",
                            )
                        else:
                            search_results.append(result)
                            self.state.add_execution_record(
                                tool=tool,
                                action="search",
                                success=True,
                                result={"count": len(result.get("options", []))},
                            )
                    else:
                        self.state.add_execution_record(
                            tool=tool,
                            action="search",
                            success=False,
                            error="検索結果が空でした",
                        )
                except Exception as e:
                    self.state.add_execution_record(
                        tool=tool,
                        action="search",
                        success=False,
                        error=str(e),
                    )
                    await self._add_reasoning_step(f"→ {tool}の検索に失敗: {e}")

        # 認証情報が必要な場合、優先的に要求
        if credentials_required_executor:
            executor_display_name = {
                "ex_reservation": "EX予約",
                "amazon": "Amazon",
                "rakuten": "楽天",
            }.get(credentials_required_executor, credentials_required_executor)

            # Web検索結果があれば参考情報として表示
            reference_info = ""
            if search_results:
                await self._add_reasoning_step("→ 参考情報として時刻表を確認しました")
                reference_info = "\n\n【参考】Web検索で時刻表情報を確認しています..."

            response = f"{executor_display_name}の認証情報が必要です。\n\n以下の情報を教えてください：\n- 会員ID\n- パスワード{reference_info}"

            # 状態をINTAKEに戻す（認証情報の入力を待つ）
            self.state.transition_to(State.INTAKE)
            # 認証情報が必要なことをresearch_resultに記録
            self.state.research_result = {
                "credentials_required": True,
                "executor_name": credentials_required_executor,
                "web_search_results": search_results,
            }

            # DEBUG: 設定を確認
            logger.warning(f"[DEBUG] Setting credentials_required=True for executor={credentials_required_executor}")
            logger.warning(f"[DEBUG] research_result set to: {self.state.research_result}")

            return {
                "state": State.INTAKE.value,
                "response": response,
                "reasoning_steps": self.state.reasoning_steps,
            }

        # LLMで検索結果を整理
        prompt = get_research_prompt(self.state.plan_result, search_results)
        llm_response = await self._call_llm(prompt)
        
        research_result = self._parse_json_response(llm_response)
        self.state.research_result = research_result
        
        if "reasoning_steps" in research_result:
            for step in research_result["reasoning_steps"]:
                await self._add_reasoning_step(step)
        
        # 十分な情報が集まったか確認
        if not self.state.can_proceed_to_propose():
            # 情報不足 → 具体的な不足情報を提示
            await self._add_reasoning_step("情報が不足しています。計画を見直します...")

            # research_resultから不足情報を取得
            missing_items = research_result.get("missing", [])
            if missing_items:
                missing_str = "、".join(missing_items)
                response = f"{missing_str}の情報が不足しています。詳しく教えてください。"
            else:
                # missingがない場合は基本情報をチェック
                missing_str = self._get_missing_info_str()
                response = f"{missing_str}を教えてください。"

            # 状態はINTAKEに戻す（ユーザーからの追加情報を待つ）
            self.state.transition_to(State.INTAKE)
            return {
                "state": State.INTAKE.value,
                "response": response,
                "reasoning_steps": self.state.reasoning_steps,
            }
        
        # 次の状態へ
        self.state.transition_to(State.PROPOSE)
        
        # PROPOSEも続けて実行
        return await self._process_propose()
    
    async def _process_propose(self) -> dict[str, Any]:
        """PROPOSE: 提案を作成"""
        await self._add_reasoning_step("おすすめを選んでいます...")
        
        prompt = get_propose_prompt(
            self.state.intake_result,
            self.state.research_result,
        )
        llm_response = await self._call_llm(prompt)
        
        proposal = self._parse_json_response(llm_response)
        self.state.proposal = proposal
        
        if "reasoning_steps" in proposal:
            for step in proposal["reasoning_steps"]:
                await self._add_reasoning_step(step)
        
        # ============================================================
        # Criticで提案を評価（最大2回まで修正を試みる）
        # 問題があれば、必要に応じてJina + Tavilyで再検索して修正
        # ============================================================
        from app.agent.critic import Critic
        critic = Critic(self.llm_client)
        
        for attempt in range(2):
            evaluation = await critic.evaluate_proposal(
                self.state.proposal,
                self.state.intake_result,
            )
            
            if evaluation.get("is_valid", True):
                break
            
            # 問題がある場合 → 自問形式で表示
            issues = evaluation.get("issues", [])
            suggestions = evaluation.get("suggestions", [])
            
            # 自問形式に変換して表示
            self_question = await critic.format_as_self_question(issues, suggestions)
            if self_question:
                await self._add_reasoning_step(self_question)
            
            # 修正を試みる（必要に応じてWeb再検索を実行）
            fixed_proposal, fix_steps = await critic.suggest_fix(
                self.state.proposal,
                issues,
                suggestions,
                intake_result=self.state.intake_result,  # 再検索用
            )
            
            # 修正過程のreasoning_stepsを追加
            for step in fix_steps:
                await self._add_reasoning_step(step)
            
            self.state.proposal = fixed_proposal
        
        # ============================================================
        
        # 次の状態へ（CONFIRM）
        self.state.transition_to(State.CONFIRM)
        
        # 承認待ち
        return {
            "state": State.CONFIRM.value,
            "response": self._format_proposal(self.state.proposal),
            "reasoning_steps": self.state.reasoning_steps,
            "needs_confirmation": True,
            "proposal": self.state.proposal,
        }
    
    async def _process_confirm(self, message: str) -> dict[str, Any]:
        """CONFIRM: ユーザーの返答を判定"""
        
        # 特別なメッセージの処理
        if message.lower() in ["ok", "yes", "はい", "お願い", "進めて", "それで"]:
            # 承認
            await self._add_reasoning_step("承認されました。実行を開始します...")
            self.state.transition_to(State.EXECUTE)
            return await self._process_execute()
        
        # LLMで判定
        prompt = get_confirm_prompt(self.state.proposal, message)
        llm_response = await self._call_llm(prompt)
        
        confirm_result = self._parse_json_response(llm_response)
        response_type = confirm_result.get("type", "other")
        
        if response_type == "approval":
            # 承認
            await self._add_reasoning_step("承認されました。実行を開始します...")
            self.state.transition_to(State.EXECUTE)
            return await self._process_execute()
        
        elif response_type == "modification":
            # 修正要望 → PLANに戻る
            modification = confirm_result.get("modification_details", message)
            await self._add_reasoning_step(f"修正要望: {modification}")
            
            # 修正内容をintake_resultに反映
            self.state.intake_result["modification"] = modification
            
            self.state.transition_to(State.PLAN)
            return await self._process_plan()
        
        elif response_type == "rejection":
            # 拒否
            await self._add_reasoning_step("キャンセルされました。")
            return {
                "state": State.REPORT.value,
                "response": "わかりました。キャンセルしました。",
                "reasoning_steps": self.state.reasoning_steps,
            }
        
        elif response_type == "question":
            # 質問 → 回答して再度CONFIRM
            await self._add_reasoning_step(f"質問に回答します: {message}")
            # TODO: 質問に回答するロジック
            return {
                "state": State.CONFIRM.value,
                "response": "（質問への回答）",
                "reasoning_steps": self.state.reasoning_steps,
                "needs_confirmation": True,
            }
        
        else:
            # その他
            return {
                "state": State.CONFIRM.value,
                "response": "すみません、よくわかりませんでした。「OK」で進める、または修正内容を教えてください。",
                "reasoning_steps": self.state.reasoning_steps,
                "needs_confirmation": True,
            }
    
    async def _process_execute(self) -> dict[str, Any]:
        """EXECUTE: Executor.execute()を呼ぶ"""
        await self._add_reasoning_step("実行中...")

        # 使用するExecutorを特定
        tools = self.state.plan_result.get("tools", [])

        for tool in tools:
            # web_searchやnoneはスキップ（Executorのみ実行）
            if tool in ["web_search", "none"]:
                continue

            await self._add_reasoning_step(f"→ {tool}で予約を実行しています...")
            result = await self._call_executor_execute(tool)
            self.state.execution_result = result

            if result.get("success"):
                await self._add_reasoning_step(f"→ {tool}の実行が完了しました")
            else:
                await self._add_reasoning_step(f"→ {tool}の実行に失敗: {result.get('message')}")

            break  # 最初の1つだけ実行（複数対応は将来）

        # 次の状態へ
        self.state.transition_to(State.VERIFY)

        return await self._process_verify()
    
    async def _process_verify(self) -> dict[str, Any]:
        """VERIFY: 実行結果を確認"""
        await self._add_reasoning_step("実行結果を確認しています...")
        
        prompt = get_verify_prompt(self.state.execution_result)
        llm_response = await self._call_llm(prompt)
        
        verification = self._parse_json_response(llm_response)
        self.state.verification = verification
        
        if "reasoning_steps" in verification:
            for step in verification["reasoning_steps"]:
                await self._add_reasoning_step(step)
        
        # 次の状態へ
        self.state.transition_to(State.REPORT)
        
        return await self._process_report()
    
    async def _process_report(self) -> dict[str, Any]:
        """REPORT: 最終レポート作成"""
        
        prompt = get_report_prompt(
            self.state.intake_result,
            self.state.verification,
        )
        llm_response = await self._call_llm(prompt)
        
        report = self._parse_json_response(llm_response)
        self.state.report = report
        
        return {
            "state": State.REPORT.value,
            "response": self._format_report(report),
            "reasoning_steps": self.state.reasoning_steps,
            "report": report,
        }
    
    # ============================================================
    # ヘルパーメソッド
    # ============================================================
    
    async def _call_llm(self, prompt: str) -> str:
        """LLMを呼び出す（ストリーミング版）
        
        [STEP] 行を検出したらリアルタイムでコールバックを呼び出し、
        [RESULT]...[/RESULT] の中身をJSONとして返す。
        """
        if not self.llm_client:
            # モック応答（テスト用）
            logger.warning("LLM client not set, returning mock response")
            return '{"mock": true}'
        
        try:
            full_response = ""
            current_line = ""
            in_result = False
            result_content = ""
            step_count = 0
            
            print(f"[LLM_CALL] Starting LLM stream...", flush=True)
            
            # ストリーミングで受け取る
            async with self.llm_client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                async for text in stream.text_stream:
                    full_response += text
                    current_line += text
                    
                    # 改行で行を処理
                    while "\n" in current_line:
                        line, current_line = current_line.split("\n", 1)
                        line = line.strip()
                        
                        # [STEP] 行を検出
                        if line.startswith("[STEP]"):
                            step_text = line[6:].strip()
                            if step_text:
                                step_count += 1
                                print(f"[LLM_CALL] STEP detected #{step_count}: {step_text[:50]}...", flush=True)
                                await self._add_reasoning_step(step_text)
                        
                        # [RESULT] 開始
                        elif line == "[RESULT]":
                            in_result = True
                            print(f"[LLM_CALL] RESULT block started", flush=True)
                        
                        # [/RESULT] 終了
                        elif line == "[/RESULT]":
                            in_result = False
                            print(f"[LLM_CALL] RESULT block ended", flush=True)
                        
                        # RESULT内のコンテンツを収集
                        elif in_result:
                            result_content += line + "\n"
            
            print(f"[LLM_CALL] Stream complete. Steps: {step_count}, Has RESULT: {bool(result_content.strip())}", flush=True)
            
            # 最後の行を処理
            if current_line.strip():
                if current_line.strip().startswith("[STEP]"):
                    step_text = current_line.strip()[6:].strip()
                    if step_text:
                        await self._add_reasoning_step(step_text)
            
            # [RESULT]が見つからなかった場合は全文を返す（後方互換）
            if not result_content.strip():
                print(f"[LLM_CALL] No RESULT block, returning full response (first 200 chars): {full_response[:200]}...", flush=True)
                return full_response
            
            return result_content.strip()
            
        except Exception as e:
            logger.exception(f"LLM call failed: {e}")
            return '{"error": "LLM call failed"}'
    
    async def _call_llm_with_messages(self, system_prompt: str, messages: list) -> str:
        """Messages配列方式でLLMを呼び出す（会話履歴対応）
        
        Args:
            system_prompt: システムプロンプト
            messages: [{"role": "user/assistant", "content": "..."}] の配列
        
        Returns:
            LLMの応答テキスト
        """
        if not self.llm_client:
            logger.warning("LLM client not set, returning mock response")
            return "モック応答です"
        
        try:
            response = await self.llm_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                system=system_prompt,
                messages=messages,
            )
            return response.content[0].text
        except Exception as e:
            logger.exception(f"LLM call with messages failed: {e}")
            return "エラーが発生しました"
    
    def _parse_json_response(self, response: str) -> dict:
        """LLMのレスポンスからJSONを抽出"""
        try:
            # ```json ... ``` を抽出
            if "```json" in response:
                start = response.find("```json") + 7
                end = response.find("```", start)
                json_str = response[start:end].strip()
            elif "```" in response:
                start = response.find("```") + 3
                end = response.find("```", start)
                json_str = response[start:end].strip()
            else:
                json_str = response.strip()
            
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON: {e}")
            return {"raw_response": response}
    
    async def _call_web_search(self, query: str = None) -> Optional[dict]:
        """Tavily検索 + Jinaでページ内容取得
        
        Args:
            query: 検索クエリ（指定がない場合はintake_resultから構築）
        """
        try:
            from app.tools.tavily_search import search_with_tavily
            from app.tools.jina_reader import search_and_read
            
            # 検索クエリを構築（引数で指定されていない場合）
            if not query:
                intent = self.state.intake_result.get("intent", "")
                details = self.state.intake_result.get("details", {})
                
                # クエリを組み立て
                query_parts = [intent]
                for key in ["departure", "arrival", "date", "time"]:
                    if details.get(key):
                        query_parts.append(str(details[key]))
                
                query = " ".join(query_parts)
            
            # Tavilyで検索
            tavily_results = await search_with_tavily(query, max_results=5)
            
            if not tavily_results:
                return None
            
            # Jinaでページ内容を取得（上位3件）
            results_with_content = await search_and_read(
                [r.model_dump() for r in tavily_results],
                max_pages=3,
            )
            
            return {
                "source": "web_search",
                "query": query,
                "results": results_with_content,
            }
        
        except Exception as e:
            logger.exception(f"Web search failed: {e}")
            return None
    
    async def _respond_as_chat(self, message: str, search_results: dict = None) -> dict[str, Any]:
        """雑談・質問への通常応答（Messages配列方式）
        
        Args:
            message: ユーザーのメッセージ
            search_results: 検索結果（requires_searchがtrueの場合に渡される）
        """
        from datetime import datetime
        import pytz
        
        # 現在時刻（日本時間）
        jst = pytz.timezone('Asia/Tokyo')
        now = datetime.now(jst)
        current_datetime = now.strftime("%Y年%m月%d日 %H:%M:%S（%A）")
        
        # 検索結果セクションを構築
        search_section = ""
        if search_results and search_results.get("results"):
            search_section = "\n## 検索結果（参考情報）\n"
            for i, result in enumerate(search_results["results"][:5], 1):
                title = result.get("title", "")
                content = result.get("content", "")[:500]  # 長すぎる場合は切り詰め
                url = result.get("url", "")
                search_section += f"\n### {i}. {title}\n{content}\n出典: {url}\n"
            search_section += "\n※上記の検索結果を参考に、最新の情報を含めて回答してください。\n"
        
        # システムプロンプト
        system_prompt = f"""あなたは「ダン」という名前のAI秘書です。

## 現在の情報
- 現在時刻: {current_datetime}
- タイムゾーン: 日本時間 (JST/UTC+9)
{search_section}
## あなたの特徴
- 親しみやすく、カジュアルな口調
- 技術的な質問には技術的に答える
- 自分のソースコードにはアクセスできないが、一般的なLLM/AIの仕組みは説明できる
- 「分からない」時は正直に言う
- ユーザーの質問の真意を理解しようとする

## 注意
- 質問の意図を正しく理解してから答える
- 「コードを修正したい」などの技術的質問には、具体的なアドバイスを
- 会話履歴から文脈を読み取る
- 検索結果がある場合は、その情報を元に回答する"""
        
        # 会話履歴をMessages配列形式で取得
        conversation_history = await self._get_conversation_history(limit=10)
        messages = []
        
        # 古い順に追加（reversedで時系列順に）
        for msg in reversed(conversation_history):
            role = "user" if msg.get("sender_type") == "human" else "assistant"
            content = msg.get("content", "")
            if content:
                messages.append({"role": role, "content": content})
        
        # 新しいユーザーメッセージを追加
        messages.append({"role": "user", "content": message})
        
        # Messages配列方式でLLMを呼び出し
        response = await self._call_llm_with_messages(system_prompt, messages)
        
        return {
            "state": "CHAT",
            "response": response.strip(),
            "reasoning_steps": self.state.reasoning_steps,
            "is_chat": True,
        }
    
    async def _get_conversation_history(self, limit: int = 10) -> list:
        """会話履歴を取得"""
        try:
            from app.services.supabase_client import get_supabase_client
            
            supabase = get_supabase_client()
            
            # ユーザーのdan_roomを取得してメッセージを取得
            if not self.state.user_id:
                return []
            
            # usersテーブルからdan_room_idを直接取得
            user_result = supabase.client.table("users").select("dan_room_id").eq("id", self.state.user_id).limit(1).execute()
            if not user_result.data or not user_result.data[0].get("dan_room_id"):
                return []
            
            room_id = user_result.data[0]["dan_room_id"]
            
            # chat_messagesテーブルからメッセージを取得
            messages_result = supabase.client.table("chat_messages").select(
                "content, sender_type, created_at"
            ).eq("room_id", room_id).order("created_at", desc=True).limit(limit).execute()
            
            return messages_result.data or []
        except Exception as e:
            logger.warning(f"Failed to get conversation history: {e}")
            return []
    
    async def _call_executor_search(self, executor_name: str) -> Optional[dict]:
        """Executor.search()を呼ぶ"""
        try:
            from app.executors.registry import ExecutorRegistry, register_all_executors

            # Executorを登録
            register_all_executors()

            # executor_nameからservice_type/service_nameを判定
            executor_mapping = {
                "ex_reservation": ("train", "ex_reservation"),
                "amazon": ("product", "amazon"),
                "rakuten": ("product", "rakuten"),
                "highway_bus": ("bus", "willer"),
                "bank_transfer": ("payment", "bank_transfer"),
                "voice": ("voice", "phone"),
            }

            if executor_name not in executor_mapping:
                logger.warning(f"Unknown executor: {executor_name}")
                return None

            service_type, service_name = executor_mapping[executor_name]
            executor = ExecutorRegistry.find(
                service_type=service_type,
                service_name=service_name,
                capability="search",
            )

            if not executor:
                logger.warning(f"Executor not found: {executor_name}")
                return None

            # credentials取得
            from app.services.credentials_service import get_credentials_service
            creds_service = get_credentials_service()
            credentials = await creds_service.get_credential(
                self.state.user_id,
                executor_name,
            )

            # 認証情報が必要なのに未登録の場合、特別な応答を返す
            if not credentials and executor_name in ["ex_reservation", "amazon", "rakuten"]:
                return {
                    "error": "credentials_required",
                    "executor_name": executor_name,
                    "message": f"{executor_name}の認証情報が登録されていません",
                }

            # 検索パラメータを構築
            params = self._build_search_params()

            result = await executor.search(params, credentials)

            # ExecutorSearchResult → dict変換
            if hasattr(result, 'to_dict'):
                return result.to_dict()
            elif hasattr(result, 'model_dump'):
                return result.model_dump()
            else:
                return result

        except Exception as e:
            logger.exception(f"Executor search failed: {e}")
            return None
    
    async def _call_executor_execute(self, executor_name: str) -> dict:
        """Executor.execute()を呼ぶ"""
        try:
            from app.executors.registry import ExecutorRegistry, register_all_executors
            from app.models.schemas import SearchResult, SearchResultCategory
            
            # Executorを登録
            register_all_executors()
            
            # executor_nameからservice_type/service_nameを判定
            executor_mapping = {
                "ex_reservation": ("train", "ex_reservation"),
                "amazon": ("product", "amazon"),
                "rakuten": ("product", "rakuten"),
                "highway_bus": ("bus", "willer"),
                "bank_transfer": ("payment", "bank_transfer"),
                "voice": ("voice", "phone"),
            }
            
            if executor_name not in executor_mapping:
                logger.warning(f"Unknown executor: {executor_name}")
                return {"success": False, "message": f"Unknown executor: {executor_name}"}
            
            service_type, service_name = executor_mapping[executor_name]
            executor = ExecutorRegistry.find(
                service_type=service_type,
                service_name=service_name,
                capability="execute",
            )
            
            if not executor:
                logger.warning(f"Executor not found: {executor_name}")
                return {"success": False, "message": f"Executor not found: {executor_name}"}
            
            # 選択されたオプションからSearchResultを構築
            recommendation = self.state.proposal.get("recommendation", {})
            
            search_result = SearchResult(
                category=SearchResultCategory.GENERAL,
                title=recommendation.get("title", ""),
                url=recommendation.get("url"),
                price=recommendation.get("price"),
                details=recommendation.get("details", {}),
            )
            
            # credentials取得
            from app.services.credentials_service import get_credentials_service
            creds_service = get_credentials_service()
            credentials = await creds_service.get_credential(
                self.state.user_id,
                executor_name,
            )
            
            result = await executor.execute(
                task_id=f"sm-{self.state.session_id}",
                user_id=self.state.user_id,
                search_result=search_result,
                credentials=credentials,
            )
            
            return {
                "success": result.success,
                "message": result.message,
                "confirmation_number": result.confirmation_number,
                "details": result.details,
            }
        
        except Exception as e:
            logger.exception(f"Executor execute failed: {e}")
            return {"success": False, "message": str(e)}
    
    def _build_search_params(self) -> dict:
        """検索パラメータを構築"""
        intake = self.state.intake_result
        details = intake.get("details", {})
        
        return {
            "departure": details.get("departure", details.get("from", "")),
            "arrival": details.get("arrival", details.get("to", "")),
            "date": details.get("date", ""),
            "time": details.get("time", ""),
            "query": intake.get("intent", ""),
        }
    
    def _format_proposal(self, proposal: dict) -> str:
        """提案をフォーマット"""
        rec = proposal.get("recommendation", {})
        reason = proposal.get("recommendation_reason", "")
        
        lines = []
        lines.append(f"**おすすめ**: {rec.get('title', '不明')}")
        if rec.get("price"):
            try:
                price = int(rec.get('price'))
                lines.append(f"**価格**: ¥{price:,}")
            except (ValueError, TypeError):
                lines.append(f"**価格**: ¥{rec.get('price')}")
        if reason:
            lines.append(f"**理由**: {reason}")
        
        alts = proposal.get("alternatives", [])
        if alts:
            lines.append("\n**代替案**:")
            for alt in alts:
                lines.append(f"- {alt.get('title', '不明')}")
        
        lines.append("\nこれで進めますか？")
        
        return "\n".join(lines)
    
    def _format_report(self, report: dict) -> str:
        """レポートをフォーマット"""
        lines = []
        lines.append(f"## {report.get('title', '完了')}")
        lines.append(report.get("summary", ""))
        
        details = report.get("details", {})
        if details:
            lines.append("\n**詳細**:")
            for key, value in details.items():
                lines.append(f"- {key}: {value}")
        
        notes = report.get("notes", [])
        if notes:
            lines.append("\n**注意**:")
            for note in notes:
                lines.append(f"- {note}")

        return "\n".join(lines)

    async def _save_session(self) -> None:
        """セッションを保存"""
        try:
            from app.services.session_service import get_session_service
            session_service = get_session_service()
            logger.warning(f"[DEBUG] Saving session {self.state.session_id}, research_result={self.state.research_result}")
            await session_service.save_session(self.state)
            logger.warning(f"[DEBUG] Session saved successfully")
        except Exception as e:
            logger.warning(f"Failed to save session: {e}")

    def _has_sufficient_info(self) -> bool:
        """必須情報が揃っているか確認"""
        details = self.state.intake_result.get("details", {})
        task_type = self.state.intake_result.get("task_type")

        if task_type in ["travel", "reservation"]:
            return bool(details.get("departure") and details.get("arrival"))
        elif task_type == "purchase":
            return bool(details.get("product"))
        elif task_type == "payment":
            return bool(details.get("amount") and details.get("recipient"))
        elif task_type == "phone":
            return bool(details.get("phone_number") or details.get("company"))
        # 他のタスクタイプは情報不足なし（検索等で補完可能）
        return True

    def _get_missing_info_str(self) -> str:
        """不足している情報を文字列で取得"""
        details = self.state.intake_result.get("details", {})
        task_type = self.state.intake_result.get("task_type")
        missing = []

        if task_type in ["travel", "reservation"]:
            if not details.get("departure"):
                missing.append("出発地")
            if not details.get("arrival"):
                missing.append("到着地")
        elif task_type == "purchase":
            if not details.get("product"):
                missing.append("商品名")
        elif task_type == "payment":
            if not details.get("amount"):
                missing.append("金額")
            if not details.get("recipient"):
                missing.append("支払先")
        elif task_type == "phone":
            if not details.get("phone_number") and not details.get("company"):
                missing.append("電話番号または会社名")

        if missing:
            return "と".join(missing)
        return "詳細情報"

