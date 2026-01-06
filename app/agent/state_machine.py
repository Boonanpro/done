"""
State Machine - 状態機械を駆動するメインロジック

新しいアーキテクチャ：
1. 状態機械で固定の遷移
2. 各状態でLLMを呼び出し
3. Executorで実行
4. Criticで評価（Step 4で追加予定）

既存のagent.pyとは独立して動作し、段階的に移行する。
"""
import json
import logging
from typing import Optional, Any, AsyncIterator

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

logger = logging.getLogger(__name__)


class StateMachine:
    """
    状態機械を駆動するクラス
    
    使い方:
        sm = StateMachine(session_id="xxx", user_id="yyy")
        result = await sm.process_message("新大阪から博多まで行きたい")
    """
    
    def __init__(
        self,
        session_id: str,
        user_id: str,
        llm_client: Optional[Any] = None,
    ):
        self.state = AgentState(session_id=session_id, user_id=user_id)
        self.llm_client = llm_client  # Anthropic client（外部から注入）
    
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
    
    async def _process_intake(self, message: str) -> dict[str, Any]:
        """INTAKE: ユーザーの要望を構造化"""
        self.state.add_reasoning_step("ユーザーの要望を分析しています...")
        
        # LLMを呼び出して要望を構造化
        prompt = get_intake_prompt(message, self.state.user_preferences)
        llm_response = await self._call_llm(prompt)
        
        # レスポンスをパース
        intake_result = self._parse_json_response(llm_response)
        self.state.intake_result = intake_result
        
        # reasoning_stepsをマージ
        if "reasoning_steps" in intake_result:
            for step in intake_result["reasoning_steps"]:
                self.state.add_reasoning_step(step)
        
        # 次の状態へ
        self.state.transition_to(State.PLAN)
        
        # PLANも続けて実行
        return await self._process_plan()
    
    async def _process_plan(self) -> dict[str, Any]:
        """PLAN: サブタスク分解"""
        self.state.add_reasoning_step("実行計画を立てています...")
        
        prompt = get_plan_prompt(self.state.intake_result)
        llm_response = await self._call_llm(prompt)
        
        plan_result = self._parse_json_response(llm_response)
        self.state.plan_result = plan_result
        
        if "reasoning_steps" in plan_result:
            for step in plan_result["reasoning_steps"]:
                self.state.add_reasoning_step(step)
        
        # 次の状態へ
        self.state.transition_to(State.RESEARCH)
        
        # RESEARCHも続けて実行
        return await self._process_research()
    
    async def _process_research(self) -> dict[str, Any]:
        """RESEARCH: 情報収集（Executor.search()を呼ぶ）"""
        self.state.add_reasoning_step("情報を収集しています...")
        
        # 使用するExecutorを特定
        tools = self.state.plan_result.get("tools", [])
        search_results = []
        
        for tool in tools:
            result = await self._call_executor_search(tool)
            if result:
                search_results.append(result)
        
        # LLMで検索結果を整理
        prompt = get_research_prompt(self.state.plan_result, search_results)
        llm_response = await self._call_llm(prompt)
        
        research_result = self._parse_json_response(llm_response)
        self.state.research_result = research_result
        
        if "reasoning_steps" in research_result:
            for step in research_result["reasoning_steps"]:
                self.state.add_reasoning_step(step)
        
        # 十分な情報が集まったか確認
        if not self.state.can_proceed_to_propose():
            # 情報不足 → PLANに戻る
            self.state.add_reasoning_step("情報が不足しています。計画を見直します...")
            self.state.transition_to(State.PLAN)
            return {
                "state": State.PLAN.value,
                "response": "情報が不足しています。もう少し詳しく教えてください。",
                "reasoning_steps": self.state.reasoning_steps,
            }
        
        # 次の状態へ
        self.state.transition_to(State.PROPOSE)
        
        # PROPOSEも続けて実行
        return await self._process_propose()
    
    async def _process_propose(self) -> dict[str, Any]:
        """PROPOSE: 提案を作成"""
        self.state.add_reasoning_step("おすすめを選んでいます...")
        
        prompt = get_propose_prompt(
            self.state.intake_result,
            self.state.research_result,
        )
        llm_response = await self._call_llm(prompt)
        
        proposal = self._parse_json_response(llm_response)
        self.state.proposal = proposal
        
        if "reasoning_steps" in proposal:
            for step in proposal["reasoning_steps"]:
                self.state.add_reasoning_step(step)
        
        # 次の状態へ（CONFIRM）
        self.state.transition_to(State.CONFIRM)
        
        # 承認待ち
        return {
            "state": State.CONFIRM.value,
            "response": self._format_proposal(proposal),
            "reasoning_steps": self.state.reasoning_steps,
            "needs_confirmation": True,
            "proposal": proposal,
        }
    
    async def _process_confirm(self, message: str) -> dict[str, Any]:
        """CONFIRM: ユーザーの返答を判定"""
        
        # 特別なメッセージの処理
        if message.lower() in ["ok", "yes", "はい", "お願い", "進めて", "それで"]:
            # 承認
            self.state.add_reasoning_step("承認されました。実行を開始します...")
            self.state.transition_to(State.EXECUTE)
            return await self._process_execute()
        
        # LLMで判定
        prompt = get_confirm_prompt(self.state.proposal, message)
        llm_response = await self._call_llm(prompt)
        
        confirm_result = self._parse_json_response(llm_response)
        response_type = confirm_result.get("type", "other")
        
        if response_type == "approval":
            # 承認
            self.state.add_reasoning_step("承認されました。実行を開始します...")
            self.state.transition_to(State.EXECUTE)
            return await self._process_execute()
        
        elif response_type == "modification":
            # 修正要望 → PLANに戻る
            modification = confirm_result.get("modification_details", message)
            self.state.add_reasoning_step(f"修正要望: {modification}")
            
            # 修正内容をintake_resultに反映
            self.state.intake_result["modification"] = modification
            
            self.state.transition_to(State.PLAN)
            return await self._process_plan()
        
        elif response_type == "rejection":
            # 拒否
            self.state.add_reasoning_step("キャンセルされました。")
            return {
                "state": State.REPORT.value,
                "response": "わかりました。キャンセルしました。",
                "reasoning_steps": self.state.reasoning_steps,
            }
        
        elif response_type == "question":
            # 質問 → 回答して再度CONFIRM
            self.state.add_reasoning_step(f"質問に回答します: {message}")
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
        self.state.add_reasoning_step("実行中...")
        
        # 使用するExecutorを特定
        tools = self.state.plan_result.get("tools", [])
        
        for tool in tools:
            result = await self._call_executor_execute(tool)
            self.state.execution_result = result
            break  # 最初の1つだけ実行（複数対応は将来）
        
        # 次の状態へ
        self.state.transition_to(State.VERIFY)
        
        return await self._process_verify()
    
    async def _process_verify(self) -> dict[str, Any]:
        """VERIFY: 実行結果を確認"""
        self.state.add_reasoning_step("実行結果を確認しています...")
        
        prompt = get_verify_prompt(self.state.execution_result)
        llm_response = await self._call_llm(prompt)
        
        verification = self._parse_json_response(llm_response)
        self.state.verification = verification
        
        if "reasoning_steps" in verification:
            for step in verification["reasoning_steps"]:
                self.state.add_reasoning_step(step)
        
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
        """LLMを呼び出す"""
        if not self.llm_client:
            # モック応答（テスト用）
            logger.warning("LLM client not set, returning mock response")
            return '{"mock": true}'
        
        try:
            response = await self.llm_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as e:
            logger.exception(f"LLM call failed: {e}")
            return '{"error": "LLM call failed"}'
    
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
    
    async def _call_executor_search(self, executor_name: str) -> Optional[dict]:
        """Executor.search()を呼ぶ"""
        try:
            from app.executors.registry import ExecutorRegistry
            
            registry = ExecutorRegistry()
            executor = registry.get_executor(executor_name)
            
            if not executor:
                logger.warning(f"Executor not found: {executor_name}")
                return None
            
            # 検索パラメータを構築
            params = self._build_search_params()
            
            result = await executor.search(params)
            return result.to_dict()
        
        except Exception as e:
            logger.exception(f"Executor search failed: {e}")
            return None
    
    async def _call_executor_execute(self, executor_name: str) -> dict:
        """Executor.execute()を呼ぶ"""
        try:
            from app.executors.registry import ExecutorRegistry
            from app.models.schemas import SearchResult, SearchResultCategory
            
            registry = ExecutorRegistry()
            executor = registry.get_executor(executor_name)
            
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
            lines.append(f"**価格**: ¥{rec.get('price'):,}")
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

