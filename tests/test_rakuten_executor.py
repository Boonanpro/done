"""
Tests for Rakuten Executor
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.executors.rakuten_executor import RakutenExecutor
from app.executors.base import ExecutorFactory
from app.models.schemas import SearchResult, ExecutionResult


class TestRakutenExecutor:
    """RakutenExecutor のテスト"""
    
    def test_executor_factory_returns_rakuten_executor(self):
        """ExecutorFactoryがRakutenExecutorを返す"""
        executor = ExecutorFactory.get_executor("product", "rakuten")
        assert isinstance(executor, RakutenExecutor)
        assert executor.service_name == "rakuten"
    
    def test_rakuten_executor_service_name(self):
        """サービス名がrakuten"""
        executor = RakutenExecutor()
        assert executor.service_name == "rakuten"
    
    def test_rakuten_executor_requires_login(self):
        """ログインが必要"""
        executor = RakutenExecutor()
        assert executor._requires_login() is True
    
    def test_rakuten_executor_has_selectors(self):
        """セレクタが定義されている"""
        executor = RakutenExecutor()
        assert "add_to_cart" in executor.SELECTORS
        assert "login_link" in executor.SELECTORS
        assert "user_id_input" in executor.SELECTORS
        assert "password_input" in executor.SELECTORS
        assert "floating_cart" in executor.SELECTORS
    
    def test_rakuten_executor_has_urls(self):
        """URLが定義されている"""
        executor = RakutenExecutor()
        assert "login" in executor.URLS
        assert "cart" in executor.URLS
        assert "rakuten" in executor.URLS["login"]


class TestRakutenExecutorWithMock:
    """モックを使ったRakutenExecutorのテスト"""
    
    @pytest.fixture
    def search_result(self):
        """テスト用SearchResult"""
        return SearchResult(
            id="test-001",
            category="product",
            title="テスト商品 楽天市場",
            url="https://item.rakuten.co.jp/test-shop/test-item/",
            price=1500,
            details={
                "shop": "テストショップ",
                "item_id": "test-item",
            },
            execution_params={
                "service_name": "rakuten",
                "booking_url": "https://item.rakuten.co.jp/test-shop/test-item/",
                "requires_login": True,
            },
        )
    
    @pytest.fixture
    def mock_page(self):
        """モックPage"""
        page = AsyncMock()
        page.url = "https://item.rakuten.co.jp/test-shop/test-item/"
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
    async def test_do_execute_without_url(self, search_result):
        """URLがない場合はエラー"""
        executor = RakutenExecutor()
        
        # URLなしのSearchResult
        search_result_no_url = SearchResult(
            id="test-002",
            category="product",
            title="URLなし商品",
            url="",
            details={},
        )
        
        with patch("app.executors.rakuten_executor.get_page") as mock_get_page:
            mock_page = AsyncMock()
            mock_get_page.return_value = mock_page
            
            result = await executor._do_execute(
                task_id="task-001",
                search_result=search_result_no_url,
                credentials=None,
            )
            
            assert result.success is False
            assert "URL" in result.message
    
    @pytest.mark.asyncio
    async def test_add_to_cart_button_not_found(self, search_result, mock_page):
        """カートボタンが見つからない場合"""
        executor = RakutenExecutor()
        
        # カートボタンが見つからない
        mock_page.query_selector = AsyncMock(return_value=None)
        
        # get_by_roleのモック
        mock_locator = AsyncMock()
        mock_locator.count = AsyncMock(return_value=0)
        mock_page.get_by_role = MagicMock(return_value=mock_locator)
        
        result = await executor._add_to_cart(mock_page)
        
        assert result["success"] is False
        assert "見つかりません" in result["message"]
    
    @pytest.mark.asyncio
    async def test_add_to_cart_success(self, mock_page):
        """カート追加成功"""
        executor = RakutenExecutor()
        
        # カートボタンが見つかる
        mock_button = AsyncMock()
        mock_button.click = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=mock_button)
        mock_page.url = "https://basket.step.rakuten.co.jp/rms/basket/"
        
        result = await executor._add_to_cart(mock_page)
        
        assert result["success"] is True
        assert "カートに追加" in result["message"]
    
    @pytest.mark.asyncio
    async def test_ensure_logged_in_already_logged_in(self, mock_page):
        """既にログイン済みの場合"""
        executor = RakutenExecutor()
        
        # マイページ要素が表示されている
        mock_element = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=mock_element)
        
        result = await executor._ensure_logged_in(mock_page, None)
        
        assert result["success"] is True
        assert "ログイン済み" in result["message"]
    
    @pytest.mark.asyncio
    async def test_ensure_logged_in_no_credentials(self, mock_page):
        """認証情報がない場合"""
        executor = RakutenExecutor()
        
        # ログインしていない状態（両方の要素がない）
        async def query_side_effect(selector):
            if "mypage" in selector or "member" in selector or "user-name" in selector:
                return None
            if "login" in selector:
                return AsyncMock()  # ログインボタンがある
            return None
        
        mock_page.query_selector = AsyncMock(side_effect=query_side_effect)
        
        result = await executor._ensure_logged_in(mock_page, None)
        
        assert result["success"] is False
        assert "ログイン情報が必要" in result["message"]
    
    @pytest.mark.asyncio
    async def test_ensure_logged_in_missing_password(self, mock_page):
        """パスワードが不足している場合"""
        executor = RakutenExecutor()
        
        # ログインしていない状態
        async def query_side_effect(selector):
            if "mypage" in selector or "member" in selector or "user-name" in selector:
                return None
            if "login" in selector:
                return AsyncMock()  # ログインボタンがある
            return None
        
        mock_page.query_selector = AsyncMock(side_effect=query_side_effect)
        
        result = await executor._ensure_logged_in(
            mock_page,
            {"email": "test@example.com", "password": ""},
        )
        
        assert result["success"] is False
        assert "不足" in result["message"]
    
    @pytest.mark.asyncio
    async def test_hide_floating_elements(self, mock_page):
        """フローティング要素の非表示"""
        executor = RakutenExecutor()
        
        # evaluateが呼ばれることを確認
        await executor._hide_floating_elements(mock_page)
        
        mock_page.evaluate.assert_called_once()


class TestIntegrationRakutenExecutor:
    """統合テスト（実際のブラウザを使用しない）"""
    
    @pytest.mark.asyncio
    async def test_full_execute_flow_mocked(self):
        """実行フロー全体のモックテスト"""
        executor = RakutenExecutor()
        
        search_result = SearchResult(
            id="test-integration-001",
            category="product",
            title="統合テスト商品",
            url="https://item.rakuten.co.jp/test-shop/test-item/",
            price=2000,
            details={},
            execution_params={
                "service_name": "rakuten",
                "requires_login": True,
            },
        )
        
        credentials = {
            "email": "test@example.com",
            "password": "testpassword",
        }
        
        with patch("app.executors.rakuten_executor.get_page") as mock_get_page, \
             patch.object(executor, "_ensure_logged_in") as mock_login, \
             patch.object(executor, "_add_to_cart") as mock_cart, \
             patch.object(executor, "_hide_floating_elements") as mock_hide, \
             patch.object(executor, "_update_progress") as mock_progress:
            
            # モックの設定
            mock_page = AsyncMock()
            mock_page.url = "https://item.rakuten.co.jp/test-shop/test-item/"
            mock_page.goto = AsyncMock()
            mock_get_page.return_value = mock_page
            
            mock_login.return_value = {"success": True, "message": "ログイン成功"}
            mock_cart.return_value = {"success": True, "message": "カートに追加しました"}
            
            # 実行
            result = await executor._do_execute(
                task_id="task-integration-001",
                search_result=search_result,
                credentials=credentials,
            )
            
            # 検証
            assert result.success is True
            assert "カートに追加" in result.message
            assert result.confirmation_number is not None
            assert result.details is not None
            assert "cart_url" in result.details
            
            # フローティング要素の非表示が呼ばれたか確認
            mock_hide.assert_called_once()
            
            # 進捗更新が呼ばれたか確認
            assert mock_progress.call_count >= 4  # 少なくとも4つのステップ
