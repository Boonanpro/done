"""
Agent Session Service - StateMachine状態の永続化
"""
import logging
from typing import Optional, Dict
from datetime import datetime, timedelta

from app.services.supabase_client import get_supabase_client
from app.agent.states import AgentState, State

logger = logging.getLogger(__name__)


class SessionService:
    """セッション管理サービス（メモリベース）"""

    def __init__(self):
        self.supabase = get_supabase_client().client
        # メモリ内セッションストア（RLS問題の回避）
        self._memory_store: Dict[str, AgentState] = {}

    async def get_or_create_session(
        self,
        room_id: str,
        user_id: str,
    ) -> AgentState:
        """
        セッションを取得または作成（メモリベース）

        Args:
            room_id: チャットルームID（セッションIDとして使用）
            user_id: ユーザーID

        Returns:
            AgentState: 復元された状態、または新規状態
        """
        # メモリストアから取得
        session_key = f"{user_id}:{room_id}"

        if session_key in self._memory_store:
            state = self._memory_store[session_key]
            logger.info(f"Restored session {room_id} from memory (state: {state.current_state.value})")
            return state
        else:
            # 新規セッション作成
            state = AgentState(session_id=room_id, user_id=user_id)
            self._memory_store[session_key] = state
            logger.info(f"Created new session {room_id} in memory")
            return state

    async def save_session(self, state: AgentState) -> bool:
        """
        セッションを保存（メモリベース）

        Args:
            state: AgentState

        Returns:
            bool: 成功したかどうか
        """
        try:
            session_key = f"{state.user_id}:{state.session_id}"
            self._memory_store[session_key] = state
            logger.debug(f"Saved session {state.session_id} to memory")
            return True

        except Exception as e:
            logger.error(f"Failed to save session to memory: {e}", exc_info=False)
            return False

    async def delete_session(self, session_id: str, user_id: str) -> bool:
        """
        セッションを削除

        Args:
            session_id: セッションID
            user_id: ユーザーID

        Returns:
            bool: 成功したかどうか
        """
        try:
            result = self.supabase.table("agent_sessions").delete().eq(
                "session_id", session_id
            ).eq("user_id", user_id).execute()

            if result.data:
                logger.info(f"Deleted session {session_id}")
                return True
            else:
                logger.warning(f"No session found to delete: {session_id}")
                return False

        except Exception as e:
            logger.exception(f"Failed to delete session: {e}")
            return False

    async def cleanup_old_sessions(self, days: int = 7) -> int:
        """
        古いセッションを削除

        Args:
            days: 何日前までのセッションを削除するか

        Returns:
            int: 削除されたセッション数
        """
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)

            result = self.supabase.table("agent_sessions").delete().lt(
                "updated_at", cutoff.isoformat()
            ).execute()

            count = len(result.data) if result.data else 0
            logger.info(f"Cleaned up {count} old sessions (older than {days} days)")
            return count

        except Exception as e:
            logger.exception(f"Failed to cleanup old sessions: {e}")
            return 0

    def _serialize_state(self, state: AgentState) -> dict:
        """AgentStateをDB保存用dictに変換"""
        return {
            "session_id": state.session_id,
            "user_id": state.user_id,
            "current_state": state.current_state.value,
            "intake_result": state.intake_result,
            "plan_result": state.plan_result,
            "research_result": state.research_result,
            "proposal": state.proposal,
            "execution_result": state.execution_result,
            "verification": state.verification,
            "report": state.report,
            "reasoning_steps": state.reasoning_steps,
            "execution_history": state.execution_history,
            "user_preferences": state.user_preferences,
            "error": state.error,
        }

    def _deserialize_state(self, data: dict) -> AgentState:
        """DB保存データからAgentStateを復元"""
        state = AgentState(
            session_id=data["session_id"],
            user_id=data["user_id"],
        )
        state.current_state = State(data["current_state"])
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


# シングルトンインスタンス
_session_service: SessionService = None


def get_session_service() -> SessionService:
    """SessionServiceのシングルトンインスタンスを取得"""
    global _session_service
    if _session_service is None:
        _session_service = SessionService()
    return _session_service
