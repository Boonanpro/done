"""
Tests for EX Reservation Executor
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.executors.ex_reservation_executor import EXReservationExecutor
from app.executors.base import ExecutorFactory
from app.models.schemas import SearchResult, ExecutionResult


class TestEXReservationExecutor:
    """EXReservationExecutor のテスト"""
    
    def test_executor_factory_returns_ex_executor(self):
        """ExecutorFactoryがEXReservationExecutorを返す"""
        executor = ExecutorFactory.get_executor("train")
        assert isinstance(executor, EXReservationExecutor)
        assert executor.service_name == "ex_reservation"
    
    def test_ex_executor_service_name(self):
        """サービス名がex_reservation"""
        executor = EXReservationExecutor()
        assert executor.service_name == "ex_reservation"
    
    def test_ex_executor_requires_login(self):
        """ログインが必要"""
        executor = EXReservationExecutor()
        assert executor._requires_login() is True
    
    def test_ex_executor_has_selectors(self):
        """セレクタが定義されている（実サイト調査済み）"""
        executor = EXReservationExecutor()
        assert "login_button" in executor.SELECTORS
        assert "member_id_input" in executor.SELECTORS
        assert "password_input" in executor.SELECTORS
        assert "departure_station" in executor.SELECTORS
        assert "arrival_station" in executor.SELECTORS
        assert "continue_button" in executor.SELECTORS  # 検索ボタン
        assert "otp_input" in executor.SELECTORS  # ワンタイムパスワード
    
    def test_ex_executor_has_urls(self):
        """URLが定義されている（SmartEX実サイト調査済み）"""
        executor = EXReservationExecutor()
        assert "login" in executor.URLS
        assert "my_page" in executor.URLS
        assert "smart" in executor.URLS["login"]  # SmartEXのURL


class TestEXReservationExecutorWithMock:
    """モックを使ったEXReservationExecutorのテスト"""
    
    @pytest.fixture
    def search_result(self):
        """テスト用SearchResult"""
        return SearchResult(
            id="test-001",
            category="train",
            title="新幹線予約 東京→新大阪",
            url="https://expy.jp/reservation/",
            details={
                "departure": "東京",
                "arrival": "新大阪",
                "date": "2025-01-15",
                "time": "10:00",
                "train_name": "のぞみ",
            },
            execution_params={
                "service_name": "ex_reservation",
                "requires_login": True,
            },
        )
    
    @pytest.fixture
    def mock_page(self):
        """モックPage"""
        page = AsyncMock()
        page.url = "https://expy.jp/reservation/"
        page.goto = AsyncMock()
        page.fill = AsyncMock()
        page.click = AsyncMock()
        page.wait_for_selector = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        page.query_selector = AsyncMock()
        page.evaluate = AsyncMock()
        page.keyboard = MagicMock()
        page.keyboard.press = AsyncMock()
        return page
    
    @pytest.mark.asyncio
    async def test_ensure_logged_in_already_logged_in(self, mock_page):
        """既にログイン済みの場合"""
        executor = EXReservationExecutor()
        
        # マイページリンクが表示されている
        mock_element = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=mock_element)
        
        result = await executor._ensure_logged_in(mock_page, None)
        
        assert result["success"] is True
        assert "ログイン済み" in result["message"]
    
    @pytest.mark.asyncio
    async def test_ensure_logged_in_no_credentials(self, mock_page):
        """認証情報がない場合"""
        executor = EXReservationExecutor()
        
        # ログインしていない状態
        mock_page.query_selector = AsyncMock(return_value=None)
        
        result = await executor._ensure_logged_in(mock_page, None)
        
        assert result["success"] is False
        assert "ログイン情報が必要" in result["message"]
    
    @pytest.mark.asyncio
    async def test_ensure_logged_in_missing_password(self, mock_page):
        """パスワードが不足している場合"""
        executor = EXReservationExecutor()
        
        # ログインしていない状態
        mock_page.query_selector = AsyncMock(return_value=None)
        
        result = await executor._ensure_logged_in(
            mock_page,
            {"email": "test@example.com", "password": ""},
        )
        
        assert result["success"] is False
        assert "不足" in result["message"]
    
    @pytest.mark.asyncio
    async def test_enter_reservation_details(self, mock_page):
        """予約情報の入力（SmartEX用）"""
        executor = EXReservationExecutor()
        
        # 「列車を検索」ボタンと駅選択comboboxのモック
        mock_element = AsyncMock()
        mock_element.click = AsyncMock()
        mock_element.select_option = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=mock_element)
        mock_page.query_selector_all = AsyncMock(return_value=[mock_element] * 5)
        
        result = await executor._enter_reservation_details(
            mock_page, "東京", "新大阪", "2025-01-15", "10:00"
        )
        
        assert result["success"] is True
        assert "入力しました" in result["message"]
    
    @pytest.mark.asyncio
    async def test_search_and_select_train_no_results(self, mock_page):
        """列車が見つからない場合"""
        executor = EXReservationExecutor()
        
        # 「予約を続ける」ボタンあり、候補なし
        async def query_side_effect(selector):
            if "予約を続ける" in selector:
                return AsyncMock()
            return None
        
        mock_page.query_selector = AsyncMock(side_effect=query_side_effect)
        
        result = await executor._search_and_select_train(mock_page)
        
        assert result["success"] is False
        assert "見つかりません" in result["message"]
    
    @pytest.mark.asyncio
    async def test_search_and_select_train_success(self, mock_page):
        """列車検索・選択成功"""
        executor = EXReservationExecutor()
        
        # すべての要素が見つかる
        mock_element = AsyncMock()
        mock_element.click = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=mock_element)
        
        result = await executor._search_and_select_train(mock_page)
        
        assert result["success"] is True
        assert "選択しました" in result["message"]
        assert "train_info" in result


class TestIntegrationEXReservationExecutor:
    """統合テスト（実際のブラウザを使用しない）"""
    
    @pytest.mark.asyncio
    async def test_full_execute_flow_mocked(self):
        """実行フロー全体のモックテスト"""
        executor = EXReservationExecutor()
        
        search_result = SearchResult(
            id="test-integration-001",
            category="train",
            title="新幹線予約テスト",
            url="https://expy.jp/reservation/",
            details={
                "departure": "東京",
                "arrival": "新大阪",
                "date": "2025-01-15",
                "time": "10:00",
            },
            execution_params={
                "service_name": "ex_reservation",
                "requires_login": True,
            },
        )
        
        credentials = {
            "email": "test_member_id",
            "password": "testpassword",
        }
        
        with patch("app.executors.ex_reservation_executor.get_page") as mock_get_page, \
             patch.object(executor, "_ensure_logged_in") as mock_login, \
             patch.object(executor, "_enter_reservation_details") as mock_enter, \
             patch.object(executor, "_search_and_select_train") as mock_search, \
             patch.object(executor, "_update_progress") as mock_progress:
            
            # モックの設定
            mock_page = AsyncMock()
            mock_page.url = "https://expy.jp/reservation/"
            mock_page.goto = AsyncMock()
            mock_get_page.return_value = mock_page
            
            mock_login.return_value = {"success": True, "message": "ログイン成功"}
            mock_enter.return_value = {"success": True, "message": "入力完了"}
            mock_search.return_value = {
                "success": True,
                "message": "列車を選択しました",
                "train_info": {"train_name": "のぞみ123号"},
            }
            
            # 実行
            result = await executor._do_execute(
                task_id="task-integration-001",
                search_result=search_result,
                credentials=credentials,
            )
            
            # 検証
            assert result.success is True
            assert "確認画面まで進みました" in result.message
            assert result.confirmation_number is not None
            assert result.details is not None
            assert "departure" in result.details
            assert "arrival" in result.details
            
            # 進捗更新が呼ばれたか確認
            assert mock_progress.call_count >= 4  # 少なくとも4つのステップ
