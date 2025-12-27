"""
Execution Engine Test
Phase 3B: 実行エンジン自動テスト

テスト実行: pytest tests/test_execution_engine.py -v
"""
import pytest


class TestExecutionStatusAPI:
    """実行状態API"""
    
    def test_execution_status_not_found(self, client):
        """GET /api/v1/task/{id}/execution-status - 存在しないタスク"""
        response = client.get("/api/v1/task/nonexistent-task-id/execution-status")
        assert response.status_code == 404
    
    def test_provide_credentials_not_found(self, client):
        """POST /api/v1/task/{id}/provide-credentials - 存在しないタスク"""
        response = client.post(
            "/api/v1/task/nonexistent-task-id/provide-credentials",
            json={
                "service": "ex_reservation",
                "credentials": {
                    "email": "test@example.com",
                    "password": "test123"
                },
                "save_credentials": False
            }
        )
        assert response.status_code == 404


class TestExecutionService:
    """実行サービスのユニットテスト"""
    
    @pytest.mark.asyncio
    async def test_start_execution(self):
        """実行開始テスト"""
        from app.services.execution_service import get_execution_service
        from app.models.schemas import ExecutionStatus
        import uuid
        
        service = get_execution_service()
        task_id = str(uuid.uuid4())
        user_id = "test-user"
        
        # 認証不要で実行開始
        result = await service.start_execution(
            task_id=task_id,
            user_id=user_id,
            required_service=None,
        )
        
        assert result.task_id == task_id
        assert result.status == ExecutionStatus.EXECUTING
        assert result.progress is not None
        assert len(result.progress.steps_remaining) > 0
    
    @pytest.mark.asyncio
    async def test_start_execution_awaiting_credentials(self):
        """認証待ち状態テスト"""
        from app.services.execution_service import get_execution_service
        from app.models.schemas import ExecutionStatus
        import uuid
        
        service = get_execution_service()
        task_id = str(uuid.uuid4())
        user_id = "test-user-no-creds"
        
        # 認証が必要なサービスで実行開始（認証情報なし）
        result = await service.start_execution(
            task_id=task_id,
            user_id=user_id,
            required_service="ex_reservation",
        )
        
        assert result.task_id == task_id
        assert result.status == ExecutionStatus.AWAITING_CREDENTIALS
        assert result.required_service == "ex_reservation"
    
    @pytest.mark.asyncio
    async def test_update_progress(self):
        """進捗更新テスト"""
        from app.services.execution_service import get_execution_service
        from app.models.schemas import ExecutionStatus, ExecutionStep
        import uuid
        
        service = get_execution_service()
        task_id = str(uuid.uuid4())
        user_id = "test-user-progress"
        
        # 実行開始
        await service.start_execution(
            task_id=task_id,
            user_id=user_id,
            required_service=None,
        )
        
        # 進捗更新
        result = await service.update_progress(
            task_id=task_id,
            step=ExecutionStep.OPENED_URL.value,
            details={"url": "https://example.com"},
        )
        
        assert result.status == ExecutionStatus.EXECUTING
        assert ExecutionStep.OPENED_URL.value in result.progress.steps_completed
    
    @pytest.mark.asyncio
    async def test_provide_credentials(self):
        """認証情報提供テスト"""
        from app.services.execution_service import get_execution_service
        from app.models.schemas import ExecutionStatus
        import uuid
        
        service = get_execution_service()
        task_id = str(uuid.uuid4())
        user_id = "test-user-provide-creds"
        
        # 認証待ち状態で開始
        await service.start_execution(
            task_id=task_id,
            user_id=user_id,
            required_service="amazon",
        )
        
        # 認証情報を提供
        result = await service.provide_credentials(
            task_id=task_id,
            user_id=user_id,
            service="amazon",
            credentials={"email": "test@example.com", "password": "test123"},
            save_credentials=False,
        )
        
        assert result.status == ExecutionStatus.EXECUTING
        assert result.required_service is None
    
    @pytest.mark.asyncio
    async def test_complete_execution(self):
        """実行完了テスト"""
        from app.services.execution_service import get_execution_service
        from app.models.schemas import ExecutionStatus, ExecutionResult
        import uuid
        
        service = get_execution_service()
        task_id = str(uuid.uuid4())
        user_id = "test-user-complete"
        
        # 実行開始
        await service.start_execution(
            task_id=task_id,
            user_id=user_id,
            required_service=None,
        )
        
        # 完了
        result_obj = ExecutionResult(
            success=True,
            confirmation_number="ABC123",
            message="予約が完了しました",
        )
        
        result = await service.complete_execution(
            task_id=task_id,
            result=result_obj,
        )
        
        assert result.status == ExecutionStatus.COMPLETED
        assert result.execution_result is not None
        assert result.execution_result["confirmation_number"] == "ABC123"
    
    @pytest.mark.asyncio
    async def test_fail_execution(self):
        """実行失敗テスト"""
        from app.services.execution_service import get_execution_service
        from app.models.schemas import ExecutionStatus
        import uuid
        
        service = get_execution_service()
        task_id = str(uuid.uuid4())
        user_id = "test-user-fail"
        
        # 実行開始
        await service.start_execution(
            task_id=task_id,
            user_id=user_id,
            required_service=None,
        )
        
        # 失敗
        result = await service.fail_execution(
            task_id=task_id,
            error_message="サイトにアクセスできませんでした",
        )
        
        assert result.status == ExecutionStatus.FAILED
        assert result.error_message == "サイトにアクセスできませんでした"


class TestCredentialsService:
    """認証情報サービスのユニットテスト"""
    
    @pytest.mark.asyncio
    async def test_save_and_get_credential(self):
        """認証情報の保存と取得"""
        from app.services.credentials_service import get_credentials_service
        import uuid
        
        service = get_credentials_service()
        user_id = f"test-user-{uuid.uuid4().hex[:8]}"
        
        # 保存
        result = await service.save_credential(
            user_id=user_id,
            service="test_service",
            credentials={"email": "test@example.com", "password": "secret123"},
        )
        assert result["success"] == True
        
        # 取得
        cred = await service.get_credential(user_id=user_id, service="test_service")
        assert cred is not None
        assert cred["email"] == "test@example.com"
        assert cred["password"] == "secret123"
    
    @pytest.mark.asyncio
    async def test_list_credentials(self):
        """認証情報一覧取得"""
        from app.services.credentials_service import get_credentials_service
        import uuid
        
        service = get_credentials_service()
        user_id = f"test-user-list-{uuid.uuid4().hex[:8]}"
        
        # 複数保存
        await service.save_credential(
            user_id=user_id,
            service="service1",
            credentials={"email": "a@example.com", "password": "pass1"},
        )
        await service.save_credential(
            user_id=user_id,
            service="service2",
            credentials={"email": "b@example.com", "password": "pass2"},
        )
        
        # 一覧取得
        creds = await service.list_credentials(user_id=user_id)
        services = [c["service"] for c in creds]
        assert "service1" in services
        assert "service2" in services
    
    @pytest.mark.asyncio
    async def test_delete_credential(self):
        """認証情報削除"""
        from app.services.credentials_service import get_credentials_service
        import uuid
        
        service = get_credentials_service()
        user_id = f"test-user-delete-{uuid.uuid4().hex[:8]}"
        
        # 保存
        await service.save_credential(
            user_id=user_id,
            service="to_delete",
            credentials={"email": "del@example.com", "password": "delpass"},
        )
        
        # 削除
        result = await service.delete_credential(user_id=user_id, service="to_delete")
        assert result["success"] == True
        
        # 取得できないことを確認
        cred = await service.get_credential(user_id=user_id, service="to_delete")
        assert cred is None
    
    @pytest.mark.asyncio
    async def test_has_credential(self):
        """認証情報存在チェック"""
        from app.services.credentials_service import get_credentials_service
        import uuid
        
        service = get_credentials_service()
        user_id = f"test-user-has-{uuid.uuid4().hex[:8]}"
        
        # 保存前
        has = await service.has_credential(user_id=user_id, service="check_service")
        assert has == False
        
        # 保存後
        await service.save_credential(
            user_id=user_id,
            service="check_service",
            credentials={"email": "check@example.com", "password": "checkpass"},
        )
        has = await service.has_credential(user_id=user_id, service="check_service")
        assert has == True


class TestExecutorFactory:
    """Executorファクトリーのテスト"""
    
    def test_get_train_executor(self):
        """TrainExecutor取得"""
        from app.executors.base import ExecutorFactory, BaseExecutor
        from app.executors.ex_reservation_executor import EXReservationExecutor
        
        executor = ExecutorFactory.get_executor("train")
        assert isinstance(executor, BaseExecutor)
        assert isinstance(executor, EXReservationExecutor)
        assert executor.service_name == "ex_reservation"
    
    def test_get_product_executor(self):
        """ProductExecutor取得"""
        from app.executors.base import ExecutorFactory, BaseExecutor
        from app.executors.amazon_executor import AmazonExecutor
        
        executor = ExecutorFactory.get_executor("product", "amazon")
        assert isinstance(executor, BaseExecutor)
        assert isinstance(executor, AmazonExecutor)
        assert executor.service_name == "amazon"
    
    def test_get_generic_executor(self):
        """GenericExecutor取得"""
        from app.executors.base import ExecutorFactory, GenericExecutor
        
        executor = ExecutorFactory.get_executor("unknown")
        assert isinstance(executor, GenericExecutor)


class TestSmartFallback:
    """Smart fallback feature tests - LLM-powered alternative proposals"""
    
    @pytest.mark.asyncio
    async def test_generate_fallback_travel(self):
        """Test _generate_fallback_proposals for travel tasks"""
        from app.agent.agent import AISecretaryAgent
        from app.models.schemas import TaskType
        
        agent = AISecretaryAgent()
        
        # Test travel fallback (should suggest distance-appropriate options)
        alternatives = await agent._generate_fallback_proposals(
            wish="Book a bus from Osaka to Tottori on December 30th",
            task_type=TaskType.TRAVEL,
            failed_action="WILLER bus booking",
            error_message="No available buses found for this route"
        )
        
        # Should return ranked alternatives
        assert alternatives is not None
        assert isinstance(alternatives, str)
        assert len(alternatives) > 0
        # Should contain recommendation markers
        assert "おすすめ" in alternatives or "🥇" in alternatives
    
    @pytest.mark.asyncio
    async def test_generate_fallback_purchase(self):
        """Test _generate_fallback_proposals for purchase tasks"""
        from app.agent.agent import AISecretaryAgent
        from app.models.schemas import TaskType
        
        agent = AISecretaryAgent()
        
        # Test purchase fallback
        alternatives = await agent._generate_fallback_proposals(
            wish="Buy a laptop on Amazon",
            task_type=TaskType.PURCHASE,
            failed_action="Amazon cart addition",
            error_message="Product out of stock"
        )
        
        assert alternatives is not None
        assert isinstance(alternatives, str)
        assert len(alternatives) > 0