"""
Tests for Amazon Executor
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.executors.amazon_executor import AmazonExecutor
from app.executors.base import ExecutorFactory
from app.models.schemas import SearchResult, ExecutionResult


class TestAmazonExecutor:
    """AmazonExecutor のテスト"""
    
    def test_executor_factory_returns_amazon_executor(self):
        """ExecutorFactoryがAmazonExecutorを返す"""
        executor = ExecutorFactory.get_executor("product", "amazon")
        assert isinstance(executor, AmazonExecutor)
        assert executor.service_name == "amazon"
    
    def test_amazon_executor_service_name(self):
        """サービス名がamazon"""
        executor = AmazonExecutor()
        assert executor.service_name == "amazon"
    
    def test_amazon_executor_requires_login(self):
        """ログインが必要"""
        executor = AmazonExecutor()
        assert executor._requires_login() is True
    
    def test_amazon_executor_has_selectors(self):
        """セレクタが定義されている"""
        executor = AmazonExecutor()
        assert "add_to_cart" in executor.SELECTORS
        assert "login_link" in executor.SELECTORS
        assert "email_input" in executor.SELECTORS
        assert "password_input" in executor.SELECTORS
    
    def test_amazon_executor_has_urls(self):
        """URLが定義されている"""
        executor = AmazonExecutor()
        assert "login" in executor.URLS
        assert "cart" in executor.URLS
        assert "amazon.co.jp" in executor.URLS["login"]


class TestAmazonExecutorWithMock:
    """モックを使ったAmazonExecutorのテスト"""
    
    @pytest.fixture
    def search_result(self):
        """テスト用SearchResult"""
        return SearchResult(
            id="test-001",
            category="product",
            title="テスト商品 ポストイット",
            url="https://www.amazon.co.jp/dp/B07C5SQK8D",
            price=500,
            details={
                "seller": "Amazon.co.jp",
                "asin": "B07C5SQK8D",
            },
            execution_params={
                "service_name": "amazon",
                "booking_url": "https://www.amazon.co.jp/dp/B07C5SQK8D",
                "requires_login": True,
            },
        )
    
    @pytest.fixture
    def mock_page(self):
        """モックPage"""
        page = AsyncMock()
        page.url = "https://www.amazon.co.jp/dp/B07C5SQK8D"
        page.goto = AsyncMock()
        page.fill = AsyncMock()
        page.click = AsyncMock()
        page.wait_for_selector = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        page.query_selector = AsyncMock()
        return page
    
    @pytest.mark.asyncio
    async def test_do_execute_without_url(self, search_result):
        """URLがない場合はエラー"""
        executor = AmazonExecutor()
        
        # URLなしのSearchResult
        search_result_no_url = SearchResult(
            id="test-002",
            category="product",
            title="URLなし商品",
            url="",
            details={},
        )
        
        with patch("app.executors.amazon_executor.get_page") as mock_get_page:
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
        executor = AmazonExecutor()
        
        # カートボタンが見つからない
        mock_page.query_selector = AsyncMock(return_value=None)
        
        result = await executor._add_to_cart(mock_page)
        
        assert result["success"] is False
        assert "見つかりません" in result["message"]
    
    @pytest.mark.asyncio
    async def test_add_to_cart_success(self, mock_page):
        """カート追加成功"""
        executor = AmazonExecutor()
        
        # カートボタンが見つかる
        mock_button = AsyncMock()
        mock_button.click = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=mock_button)
        mock_page.url = "https://www.amazon.co.jp/gp/cart/view.html"
        
        result = await executor._add_to_cart(mock_page)
        
        assert result["success"] is True
        assert "カートに追加" in result["message"]
    
    @pytest.mark.asyncio
    async def test_ensure_logged_in_already_logged_in(self, mock_page):
        """既にログイン済みの場合"""
        executor = AmazonExecutor()
        
        # アカウント名が表示されている
        mock_element = AsyncMock()
        mock_element.inner_text = AsyncMock(return_value="こんにちは、テストさん")
        mock_page.query_selector = AsyncMock(return_value=mock_element)
        
        result = await executor._ensure_logged_in(mock_page, None)
        
        assert result["success"] is True
        assert "ログイン済み" in result["message"]
    
    @pytest.mark.asyncio
    async def test_ensure_logged_in_no_credentials(self, mock_page):
        """認証情報がない場合"""
        executor = AmazonExecutor()
        
        # ログインしていない状態
        mock_element = AsyncMock()
        mock_element.inner_text = AsyncMock(return_value="ログイン")
        mock_page.query_selector = AsyncMock(return_value=mock_element)
        
        result = await executor._ensure_logged_in(mock_page, None)
        
        assert result["success"] is False
        assert "ログイン情報が必要" in result["message"]
    
    @pytest.mark.asyncio
    async def test_ensure_logged_in_missing_password(self, mock_page):
        """パスワードが不足している場合"""
        executor = AmazonExecutor()
        
        # ログインしていない状態
        mock_element = AsyncMock()
        mock_element.inner_text = AsyncMock(return_value="ログイン")
        mock_page.query_selector = AsyncMock(return_value=mock_element)
        
        result = await executor._ensure_logged_in(
            mock_page,
            {"email": "test@example.com", "password": ""},
        )
        
        assert result["success"] is False
        assert "不足" in result["message"]


class TestIntegrationAmazonExecutor:
    """統合テスト（実際のブラウザを使用しない）"""
    
    @pytest.mark.asyncio
    async def test_full_execute_flow_mocked(self):
        """実行フロー全体のモックテスト"""
        executor = AmazonExecutor()
        
        search_result = SearchResult(
            id="test-integration-001",
            category="product",
            title="統合テスト商品",
            url="https://www.amazon.co.jp/dp/B07C5SQK8D",
            price=1000,
            details={},
            execution_params={
                "service_name": "amazon",
                "requires_login": True,
            },
        )
        
        credentials = {
            "email": "test@example.com",
            "password": "testpassword",
        }
        
        with patch("app.executors.amazon_executor.get_page") as mock_get_page, \
             patch.object(executor, "_ensure_logged_in") as mock_login, \
             patch.object(executor, "_add_to_cart") as mock_cart, \
             patch.object(executor, "_update_progress") as mock_progress:
            
            # モックの設定
            mock_page = AsyncMock()
            mock_page.url = "https://www.amazon.co.jp/dp/B07C5SQK8D"
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
            
            # 進捗更新が呼ばれたか確認
            assert mock_progress.call_count >= 4  # 少なくとも4つのステップ
