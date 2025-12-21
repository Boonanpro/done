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
    AuthOptions,
    AuthFieldInfo,
)
from app.services.credentials_service import get_credentials_service
from app.services.dynamic_auth import get_dynamic_auth_service


class ExecutionService:
    """タスク実行管理サービス（メモリストレージ版）"""
    
    # クラス変数でメモリストレージを共有
    _execution_state: dict[str, dict[str, Any]] = {}
    _execution_logs: dict[str, list[dict[str, Any]]] = {}
    
    def __init__(self):
        """サービスを初期化"""
        self.credentials_service = get_credentials_service()
        self.dynamic_auth_service = get_dynamic_auth_service()
    
    def _get_auth_options(self, service: str) -> AuthOptions:
        """
        サービスに応じた認証オプションを取得
        
        Args:
            service: サービス名
            
        Returns:
            認証オプション（ログインと新規登録のフィールド情報）
        """
        # サービス別の表示名
        service_names = {
            "willer": "WILLER EXPRESS",
            "amazon": "Amazon",
            "rakuten": "楽天市場",
            "ex_reservation": "スマートEX",
        }
        
        # 共通のログインフィールド
        login_fields = [
            AuthFieldInfo(
                name="email",
                label="メールアドレス",
                type="email",
                required=True,
                placeholder="example@email.com",
            ),
            AuthFieldInfo(
                name="password",
                label="パスワード",
                type="password",
                required=True,
                placeholder="パスワードを入力",
            ),
        ]
        
        # 自動生成パスワード
        generated_password = self.dynamic_auth_service.generate_secure_password()
        
        # サービス別の新規登録フィールド
        registration_fields = [
            AuthFieldInfo(
                name="email",
                label="メールアドレス",
                type="email",
                required=True,
                placeholder="example@email.com",
            ),
            AuthFieldInfo(
                name="password",
                label="パスワード",
                type="password",
                required=True,
                placeholder="自動生成されました",
                default_value=generated_password,  # 自動生成値
            ),
        ]
        
        # サービス固有のフィールドを追加
        if service == "willer":
            registration_fields.extend([
                AuthFieldInfo(
                    name="name",
                    label="お名前",
                    type="text",
                    required=True,
                    placeholder="山田 太郎",
                ),
                AuthFieldInfo(
                    name="phone",
                    label="電話番号",
                    type="tel",
                    required=True,
                    placeholder="090-1234-5678",
                ),
            ])
        
        return AuthOptions(
            service=service,
            service_display_name=service_names.get(service, service),
            login_fields=login_fields,
            registration_fields=registration_fields,
            generated_password=generated_password,
        )
    
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
                # ログイン/新規登録オプションを生成
                auth_options = self._get_auth_options(required_service)
                
                state = self._create_state(
                    task_id=task_id,
                    status=ExecutionStatus.AWAITING_CREDENTIALS,
                    required_service=required_service,
                    auth_options=auth_options,
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
        save_credentials: bool = True,
        is_new_registration: bool = False,
    ) -> ExecutionStatusResponse:
        """
        実行中に認証情報を提供（ログインまたは新規登録）
        
        Args:
            task_id: タスクID
            user_id: ユーザーID
            service: サービス名
            credentials: 認証情報
            save_credentials: 保存するか（デフォルトTrue）
            is_new_registration: True=新規登録、False=ログイン
            
        Returns:
            更新後の実行状態
        """
        state = self._execution_state.get(task_id)
        if not state:
            raise ValueError(f"Task {task_id} not found")
        
        if state["status"] != ExecutionStatus.AWAITING_CREDENTIALS.value:
            raise ValueError(f"Task {task_id} is not awaiting credentials")
        
        # 認証情報を保存（ログインでも新規登録でも保存）
        if save_credentials:
            await self.credentials_service.save_credential(
                user_id=user_id,
                service=service,
                credentials=credentials,
            )
        
        # 実行を再開（新規登録の場合は登録ステップを追加）
        if is_new_registration:
            steps = [
                ExecutionStep.OPENED_URL.value,
                "registering",  # 新規登録中
                ExecutionStep.LOGGED_IN.value,
                ExecutionStep.ENTERED_DETAILS.value,
                ExecutionStep.CONFIRMED.value,
                ExecutionStep.COMPLETED.value,
            ]
        else:
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
        state["auth_options"] = None  # 認証オプションをクリア
        state["is_new_registration"] = is_new_registration
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
        auth_options: Optional[AuthOptions] = None,
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
            "auth_options": auth_options.model_dump() if auth_options else None,
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
        
        # auth_optionsを復元
        auth_options = None
        if state.get("auth_options"):
            auth_options = AuthOptions(**state["auth_options"])
        
        return ExecutionStatusResponse(
            task_id=state["task_id"],
            status=ExecutionStatus(state["status"]),
            progress=progress,
            required_service=state.get("required_service"),
            auth_options=auth_options,
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
