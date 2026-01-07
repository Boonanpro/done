"""
Agent State Machine - 状態機械アーキテクチャ

Chain-of-Thought（CoT）を正しく実装するための状態管理。
LLMの推論をプロンプト/ルールでcontrolし、ハードコードを排除する。

状態遷移:
    INTAKE → PLAN → RESEARCH → PROPOSE → CONFIRM → EXECUTE → VERIFY → REPORT
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime


class State(str, Enum):
    """エージェントの状態"""
    
    # 要望を構造化（目的、期限、予算、制約）
    INTAKE = "intake"
    
    # サブタスク分解 + 必要ツール列挙 + 停止条件
    PLAN = "plan"
    
    # 検索/Executor.search()で根拠を集める
    RESEARCH = "research"
    
    # 候補提示（比較表・おすすめ・リスク）
    PROPOSE = "propose"
    
    # 実行の最終確認（不可逆操作は必須）
    CONFIRM = "confirm"
    
    # Executor.execute()で実行
    EXECUTE = "execute"
    
    # 完了確認（予約番号、スクショ等）
    VERIFY = "verify"
    
    # 結果と次の一手
    REPORT = "report"
    
    # エラー状態
    ERROR = "error"


# 状態遷移の定義
STATE_TRANSITIONS = {
    State.INTAKE: [State.PLAN],
    State.PLAN: [State.RESEARCH],
    State.RESEARCH: [State.PROPOSE, State.PLAN],  # 情報不足ならPLANに戻る
    State.PROPOSE: [State.CONFIRM],
    State.CONFIRM: [State.EXECUTE, State.PLAN],  # 修正要求ならPLANに戻る
    State.EXECUTE: [State.VERIFY, State.ERROR],
    State.VERIFY: [State.REPORT, State.ERROR],
    State.REPORT: [],  # 終了状態
    State.ERROR: [State.PLAN],  # エラーからはPLANに戻って再計画
}


@dataclass
class AgentState:
    """
    エージェントの状態を管理するクラス（メモ帳）
    
    各ステップの結果を保持し、状態遷移を管理する。
    タスクの種類（移動、購入、振込など）に関わらず汎用的に使える。
    """
    
    # 現在の状態
    current_state: State = State.INTAKE
    
    # セッション情報
    session_id: str = ""
    user_id: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    # 各ステップの結果（dict = 何でも入る箱）
    intake_result: dict[str, Any] = field(default_factory=dict)
    plan_result: dict[str, Any] = field(default_factory=dict)
    research_result: dict[str, Any] = field(default_factory=dict)
    proposal: dict[str, Any] = field(default_factory=dict)
    execution_result: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)
    
    # 推論過程（プロセス表示用）
    reasoning_steps: list[str] = field(default_factory=list)
    
    # 実行履歴（成功/失敗両方を記録、次の推論に渡す）
    execution_history: list[dict[str, Any]] = field(default_factory=list)
    
    # ユーザーの傾向（将来のPhase 5で実装）
    user_preferences: dict[str, Any] = field(default_factory=dict)
    
    # エラー情報
    error: Optional[str] = None
    
    def can_transition_to(self, next_state: State) -> bool:
        """指定した状態に遷移できるか確認"""
        allowed = STATE_TRANSITIONS.get(self.current_state, [])
        return next_state in allowed
    
    def transition_to(self, next_state: State) -> bool:
        """
        状態を遷移する
        
        Returns:
            成功したらTrue、遷移できない場合はFalse
        """
        if not self.can_transition_to(next_state):
            return False
        
        self.current_state = next_state
        self.updated_at = datetime.utcnow()
        return True
    
    def add_reasoning_step(self, step: str) -> None:
        """推論ステップを追加（プロセス表示用）"""
        self.reasoning_steps.append(step)
    
    def add_execution_record(
        self,
        tool: str,
        action: str,
        success: bool,
        result: Any = None,
        error: str = None,
    ) -> None:
        """
        実行履歴を追加（成功/失敗両方を記録）
        
        次の推論に渡すために構造化して保持する。
        PLANに戻る時やCriticが修正する時に参照される。
        
        Args:
            tool: 使用したツール（ex_reservation, web_search, etc.）
            action: 実行したアクション（search, login, execute, etc.）
            success: 成功したか
            result: 結果（成功時）
            error: エラーメッセージ（失敗時）
        """
        record = {
            "tool": tool,
            "action": action,
            "success": success,
            "timestamp": datetime.utcnow().isoformat(),
        }
        if success and result:
            record["result"] = result
        if not success and error:
            record["error"] = error
        
        self.execution_history.append(record)
    
    def get_failed_tools(self) -> list[str]:
        """失敗したツールのリストを取得"""
        return list(set(
            r["tool"] for r in self.execution_history
            if not r["success"]
        ))
    
    def get_execution_summary(self) -> dict[str, Any]:
        """
        実行履歴のサマリーを取得（次の推論に渡す用）
        """
        return {
            "total_attempts": len(self.execution_history),
            "successes": [r for r in self.execution_history if r["success"]],
            "failures": [r for r in self.execution_history if not r["success"]],
            "failed_tools": self.get_failed_tools(),
        }
    
    def can_proceed_to_propose(self) -> bool:
        """
        停止条件: PROPOSEに進めるか（十分な根拠が揃ったか）
        """
        options = self.research_result.get("options", [])
        return len(options) > 0
    
    def requires_confirmation(self) -> bool:
        """
        不可逆操作（支払い・振込・申込など）かどうか
        不可逆操作は必ずCONFIRMを挟む
        """
        intent = self.intake_result.get("intent", "")
        irreversible_intents = ["予約", "購入", "振込", "申込", "契約", "解約"]
        return any(keyword in intent for keyword in irreversible_intents)
    
    def to_dict(self) -> dict[str, Any]:
        """辞書に変換（API応答用）"""
        return {
            "current_state": self.current_state.value,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "intake_result": self.intake_result,
            "plan_result": self.plan_result,
            "research_result": self.research_result,
            "proposal": self.proposal,
            "execution_result": self.execution_result,
            "verification": self.verification,
            "report": self.report,
            "reasoning_steps": self.reasoning_steps,
            "execution_history": self.execution_history,
            "error": self.error,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentState":
        """辞書から復元"""
        state = cls()
        state.current_state = State(data.get("current_state", "intake"))
        state.session_id = data.get("session_id", "")
        state.user_id = data.get("user_id", "")
        state.intake_result = data.get("intake_result", {})
        state.plan_result = data.get("plan_result", {})
        state.research_result = data.get("research_result", {})
        state.proposal = data.get("proposal", {})
        state.execution_result = data.get("execution_result", {})
        state.verification = data.get("verification", {})
        state.report = data.get("report", {})
        state.reasoning_steps = data.get("reasoning_steps", [])
        state.execution_history = data.get("execution_history", [])
        state.user_preferences = data.get("user_preferences", {})
        state.error = data.get("error")
        return state

