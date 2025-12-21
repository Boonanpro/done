"""
Execution Service for Phase 3B: Execution Engine
タスク実行・状態管理サービス
"""
from typing import Optional, Any
from datetime import datetime
import uuid

from app.models.schemas import (
    ExecutionStatus,
    ExecutionStep,
    ExecutionProgress,
    ExecutionStatusResponse,
    ExecutionResult,
)
from app.services.credentials_service import get_credentials_service


class ExecutionService:
    """タスク実行管理サービス（メモリストレージ版）"""
    
    # クラス変数でメモリストレージを共有
    _execution_state: dict[str, dict[str, Any]] = {}
    _execution_logs: dict[str, list[dict[str, Any]]] = {}
    
    def __init__(self):
        """サービスを初期化"""
        self.credentials_service = get_credentials_service()
    
    async def start_execution(
        self,
        task_id: str,
        user_id: str,
        required_service: Optional[str] = None,
    ) -> ExecutionStatusResponse:
        """
        タスク実行を開始
        
        Args:
            task_id: タスクID
            user_id: ユーザーID
            required_service: 必要なサービス（認証情報チェック用）
            
        Returns:
            実行状態レスポンス
        """
        # 認証情報チェック
        if required_service:
            has_creds = await self.credentials_service.has_credential(
                user_id=user_id,
                service=required_service,
            )
            
            if not has_creds:
                # 認証情報がない場合はawaiting_credentials状態に
                state = self._create_state(
                    task_id=task_id,
                    status=ExecutionStatus.AWAITING_CREDENTIALS,
                    required_service=required_service,
                )
                return self._state_to_response(state)
        
        # 実行開始
        steps = [
            ExecutionStep.OPENED_URL.value,
            ExecutionStep.LOGGED_IN.value,
            ExecutionStep.ENTERED_DETAILS.value,
            ExecutionStep.CONFIRMED.value,
            ExecutionStep.COMPLETED.value,
        ]
        
        state = self._create_state(
            task_id=task_id,
            status=ExecutionStatus.EXECUTING,
            current_step=steps[0],
            steps_remaining=steps,
        )
        
        return self._state_to_response(state)
    
    async def get_execution_status(
        self,
        task_id: str,
    ) -> Optional[ExecutionStatusResponse]:
        """
        実行状態を取得
        
        Args:
            task_id: タスクID
            
        Returns:
            実行状態レスポンス、なければNone
        """
        state = self._execution_state.get(task_id)
        if not state:
            return None
        
        return self._state_to_response(state)
    
    async def update_progress(
        self,
        task_id: str,
        step: str,
        status: str = "success",
        details: Optional[dict[str, Any]] = None,
        screenshot_path: Optional[str] = None,
    ) -> ExecutionStatusResponse:
        """
        実行進捗を更新
        
        Args:
            task_id: タスクID
            step: 完了したステップ
            status: ステップのステータス（success/failed）
            details: ステップ詳細
            screenshot_path: スクリーンショットパス
            
        Returns:
            更新後の実行状態
        """
        state = self._execution_state.get(task_id)
        if not state:
            raise ValueError(f"Task {task_id} not found")
        
        # ログを記録
        log_entry = {
            "id": str(uuid.uuid4()),
            "task_id": task_id,
            "step": step,
            "status": status,
            "details": details,
            "screenshot_path": screenshot_path,
            "created_at": datetime.utcnow(),
        }
        
        if task_id not in self._execution_logs:
            self._execution_logs[task_id] = []
        self._execution_logs[task_id].append(log_entry)
        
        # 状態を更新
        steps_completed = state["steps_completed"] or []
        steps_remaining = state["steps_remaining"] or []
        
        if step in steps_remaining:
            steps_remaining.remove(step)
        if step not in steps_completed:
            steps_completed.append(step)
        
        state["steps_completed"] = steps_completed
        state["steps_remaining"] = steps_remaining
        state["current_step"] = steps_remaining[0] if steps_remaining else None
        state["updated_at"] = datetime.utcnow()
        
        if screenshot_path:
            state["screenshot_path"] = screenshot_path
        
        # 全ステップ完了チェック
        if not steps_remaining:
            state["status"] = ExecutionStatus.COMPLETED.value
            state["completed_at"] = datetime.utcnow()
        
        return self._state_to_response(state)
    
    async def complete_execution(
        self,
        task_id: str,
        result: ExecutionResult,
    ) -> ExecutionStatusResponse:
        """
        実行を完了
        
        Args:
            task_id: タスクID
            result: 実行結果
            
        Returns:
            最終的な実行状態
        """
        state = self._execution_state.get(task_id)
        if not state:
            raise ValueError(f"Task {task_id} not found")
        
        state["status"] = ExecutionStatus.COMPLETED.value if result.success else ExecutionStatus.FAILED.value
        state["completed_at"] = datetime.utcnow()
        state["execution_result"] = result.model_dump()
        state["updated_at"] = datetime.utcnow()
        
        if not result.success:
            state["error_message"] = result.message
        
        return self._state_to_response(state)
    
    async def fail_execution(
        self,
        task_id: str,
        error_message: str,
    ) -> ExecutionStatusResponse:
        """
        実行を失敗として記録
        
        Args:
            task_id: タスクID
            error_message: エラーメッセージ
            
        Returns:
            実行状態
        """
        state = self._execution_state.get(task_id)
        if not state:
            raise ValueError(f"Task {task_id} not found")
        
        state["status"] = ExecutionStatus.FAILED.value
        state["error_message"] = error_message
        state["completed_at"] = datetime.utcnow()
        state["updated_at"] = datetime.utcnow()
        
        return self._state_to_response(state)
    
    async def provide_credentials(
        self,
        task_id: str,
        user_id: str,
        service: str,
        credentials: dict[str, str],
        save_credentials: bool = False,
    ) -> ExecutionStatusResponse:
        """
        実行中に認証情報を提供
        
        Args:
            task_id: タスクID
            user_id: ユーザーID
            service: サービス名
            credentials: 認証情報
            save_credentials: 保存するか
            
        Returns:
            更新後の実行状態
        """
        state = self._execution_state.get(task_id)
        if not state:
            raise ValueError(f"Task {task_id} not found")
        
        if state["status"] != ExecutionStatus.AWAITING_CREDENTIALS.value:
            raise ValueError(f"Task {task_id} is not awaiting credentials")
        
        # 認証情報を保存
        if save_credentials:
            await self.credentials_service.save_credential(
                user_id=user_id,
                service=service,
                credentials=credentials,
            )
        
        # 実行を再開
        steps = [
            ExecutionStep.OPENED_URL.value,
            ExecutionStep.LOGGED_IN.value,
            ExecutionStep.ENTERED_DETAILS.value,
            ExecutionStep.CONFIRMED.value,
            ExecutionStep.COMPLETED.value,
        ]
        
        state["status"] = ExecutionStatus.EXECUTING.value
        state["current_step"] = steps[0]
        state["steps_remaining"] = steps
        state["required_service"] = None
        state["updated_at"] = datetime.utcnow()
        
        return self._state_to_response(state)
    
    async def get_execution_logs(
        self,
        task_id: str,
    ) -> list[dict[str, Any]]:
        """
        タスクの実行ログを取得
        
        Args:
            task_id: タスクID
            
        Returns:
            実行ログのリスト
        """
        return self._execution_logs.get(task_id, [])
    
    def _create_state(
        self,
        task_id: str,
        status: ExecutionStatus,
        current_step: Optional[str] = None,
        steps_completed: Optional[list[str]] = None,
        steps_remaining: Optional[list[str]] = None,
        required_service: Optional[str] = None,
    ) -> dict[str, Any]:
        """実行状態を作成"""
        now = datetime.utcnow()
        state = {
            "id": str(uuid.uuid4()),
            "task_id": task_id,
            "status": status.value,
            "current_step": current_step,
            "steps_completed": steps_completed or [],
            "steps_remaining": steps_remaining or [],
            "required_service": required_service,
            "execution_result": None,
            "error_message": None,
            "screenshot_path": None,
            "started_at": now if status == ExecutionStatus.EXECUTING else None,
            "completed_at": None,
            "created_at": now,
            "updated_at": now,
        }
        self._execution_state[task_id] = state
        return state
    
    def _state_to_response(
        self,
        state: dict[str, Any],
    ) -> ExecutionStatusResponse:
        """状態をレスポンスに変換"""
        progress = None
        if state["status"] == ExecutionStatus.EXECUTING.value:
            progress = ExecutionProgress(
                current_step=state["current_step"],
                steps_completed=state["steps_completed"] or [],
                steps_remaining=state["steps_remaining"] or [],
                screenshot_url=state.get("screenshot_path"),
            )
        
        return ExecutionStatusResponse(
            task_id=state["task_id"],
            status=ExecutionStatus(state["status"]),
            progress=progress,
            required_service=state.get("required_service"),
            execution_result=state.get("execution_result"),
            error_message=state.get("error_message"),
        )


# シングルトンインスタンス
_execution_service: Optional[ExecutionService] = None


def get_execution_service() -> ExecutionService:
    """実行サービスのシングルトンインスタンスを取得"""
    global _execution_service
    if _execution_service is None:
        _execution_service = ExecutionService()
    return _execution_service
