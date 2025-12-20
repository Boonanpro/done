"""
Tests for Product Search Tools
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.tools.product_search import (
    search_amazon,
    search_rakuten,
    search_kakaku,
    search_products,
    _extract_price,
)
from app.models.schemas import SearchResultCategory


class TestExtractPrice:
    """価格抽出のテスト"""
    
    def test_extract_price_with_yen(self):
        assert _extract_price("¥15,000") == 15000
        assert _extract_price("￥15,000") == 15000
    
    def test_extract_price_with_comma(self):
        assert _extract_price("15,000円") == 15000
        assert _extract_price("1,234,567") == 1234567
    
    def test_extract_price_simple(self):
        assert _extract_price("15000") == 15000
    
    def test_extract_price_empty(self):
        assert _extract_price("") is None
        assert _extract_price(None) is None


class TestSearchAmazon:
    """Amazon検索ツールのテスト"""
    
    @pytest.mark.asyncio
    async def test_search_amazon_returns_results(self):
        """正常な検索結果が返ることをテスト"""
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=[
            {
                "title": "MacBook Air M2",
                "price": "¥164,800",
                "url": "https://www.amazon.co.jp/dp/xxx",
                "review": "4.5つ星"
            }
        ])
        mock_page.close = AsyncMock()
        
        with patch("app.tools.product_search._create_page", return_value=mock_page):
            with patch("asyncio.sleep", return_value=None):
                results = await search_amazon.ainvoke({
                    "query": "MacBook Air",
                    "max_results": 5
                })
                
                assert len(results) >= 1
                assert results[0]["category"] == SearchResultCategory.PRODUCT.value
                assert results[0]["details"]["source"] == "Amazon"
    
    @pytest.mark.asyncio
    async def test_search_amazon_handles_error(self):
        """エラー時のハンドリング"""
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(side_effect=Exception("Network error"))
        mock_page.close = AsyncMock()
        
        with patch("app.tools.product_search._create_page", return_value=mock_page):
            results = await search_amazon.ainvoke({
                "query": "MacBook"
            })
            
            assert len(results) == 1
            assert "error" in results[0]


class TestSearchRakuten:
    """楽天市場検索ツールのテスト"""
    
    @pytest.mark.asyncio
    async def test_search_rakuten_returns_results(self):
        """正常な検索結果が返ることをテスト"""
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=[
            {
                "title": "MacBook Air M2 ケース",
                "price": "2,980円",
                "url": "https://item.rakuten.co.jp/xxx"
            }
        ])
        mock_page.close = AsyncMock()
        
        with patch("app.tools.product_search._create_page", return_value=mock_page):
            with patch("asyncio.sleep", return_value=None):
                results = await search_rakuten.ainvoke({
                    "query": "MacBook Air ケース"
                })
                
                assert len(results) >= 1
                assert results[0]["category"] == SearchResultCategory.PRODUCT.value
                assert results[0]["details"]["source"] == "楽天市場"


class TestSearchKakaku:
    """価格.com検索ツールのテスト"""
    
    @pytest.mark.asyncio
    async def test_search_kakaku_returns_results(self):
        """正常な検索結果が返ることをテスト"""
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=[
            {
                "title": "Apple MacBook Air 13インチ",
                "price": "¥148,000〜",
                "url": "https://kakaku.com/item/xxx"
            }
        ])
        mock_page.close = AsyncMock()
        
        with patch("app.tools.product_search._create_page", return_value=mock_page):
            with patch("asyncio.sleep", return_value=None):
                results = await search_kakaku.ainvoke({
                    "query": "MacBook Air"
                })
                
                assert len(results) >= 1
                assert results[0]["category"] == SearchResultCategory.PRODUCT.value
                assert results[0]["details"]["source"] == "価格.com"


class TestSearchProducts:
    """複合検索ツールのテスト"""
    
    @pytest.mark.asyncio
    async def test_search_products_combines_results(self):
        """複数サイトの結果が統合されることをテスト"""
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=[
            {
                "title": "Test Product",
                "price": "10,000円",
                "url": "https://example.com"
            }
        ])
        mock_page.close = AsyncMock()
        
        with patch("app.tools.product_search._create_page", return_value=mock_page):
            with patch("asyncio.sleep", return_value=None):
                results = await search_products.ainvoke({
                    "query": "テスト商品",
                    "sites": ["amazon"],
                    "max_results": 2
                })
                
                assert len(results) >= 1
