"""
Tests for Travel Search Tools
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.tools.travel_search import search_train, search_bus, search_flight
from app.models.schemas import SearchResultCategory


class TestSearchTrain:
    """電車検索ツールのテスト"""
    
    @pytest.mark.asyncio
    async def test_search_train_returns_results(self):
        """正常な検索結果が返ることをテスト"""
        # モックページを作成
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=[
            {
                "time": "17:00発 → 19:30着",
                "fare": "14,500円",
                "duration": "2時間30分",
                "transfer": "乗換0回",
                "summary": "のぞみ47号"
            }
        ])
        mock_page.close = AsyncMock()
        
        with patch("app.tools.travel_search._create_page", return_value=mock_page):
            results = await search_train.ainvoke({
                "departure": "新大阪",
                "arrival": "博多",
                "date": "2024-12-28",
                "time": "17:00"
            })
            
            assert len(results) >= 1
            assert results[0]["category"] == SearchResultCategory.TRAIN.value
            assert results[0]["details"]["departure"] == "新大阪"
            assert results[0]["details"]["arrival"] == "博多"
    
    @pytest.mark.asyncio
    async def test_search_train_handles_timeout(self):
        """タイムアウト時のエラーハンドリング"""
        from playwright.async_api import TimeoutError as PlaywrightTimeout
        
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(side_effect=PlaywrightTimeout("Timeout"))
        mock_page.close = AsyncMock()
        
        with patch("app.tools.travel_search._create_page", return_value=mock_page):
            results = await search_train.ainvoke({
                "departure": "東京",
                "arrival": "大阪"
            })
            
            assert len(results) == 1
            assert "error" in results[0]
            assert results[0].get("fallback") is True


class TestSearchBus:
    """高速バス検索ツールのテスト"""
    
    @pytest.mark.asyncio
    async def test_search_bus_returns_results(self):
        """正常な検索結果が返ることをテスト"""
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=[
            {
                "time": "22:00発",
                "price": "5,000円",
                "name": "東京-大阪 夜行バス",
                "status": "○ 空席あり"
            }
        ])
        mock_page.close = AsyncMock()
        
        with patch("app.tools.travel_search._create_page", return_value=mock_page):
            with patch("asyncio.sleep", return_value=None):
                results = await search_bus.ainvoke({
                    "departure": "東京",
                    "arrival": "大阪",
                    "date": "2024-12-28"
                })
                
                assert len(results) >= 1
                assert results[0]["category"] == SearchResultCategory.BUS.value
    
    @pytest.mark.asyncio
    async def test_search_bus_handles_error(self):
        """エラー時のハンドリング"""
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(side_effect=Exception("Network error"))
        mock_page.close = AsyncMock()
        
        with patch("app.tools.travel_search._create_page", return_value=mock_page):
            results = await search_bus.ainvoke({
                "departure": "東京",
                "arrival": "大阪"
            })
            
            assert len(results) == 1
            assert "error" in results[0]


class TestSearchFlight:
    """航空便検索ツールのテスト"""
    
    @pytest.mark.asyncio
    async def test_search_flight_returns_results(self):
        """正常な検索結果が返ることをテスト"""
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=[
            {
                "price": "¥15,000",
                "time": "10:00 - 11:30",
                "airline": "JAL",
                "duration": "1h 30m"
            }
        ])
        mock_page.close = AsyncMock()
        
        with patch("app.tools.travel_search._create_page", return_value=mock_page):
            with patch("asyncio.sleep", return_value=None):
                results = await search_flight.ainvoke({
                    "departure": "HND",
                    "arrival": "ITM",
                    "date": "2024-12-28"
                })
                
                assert len(results) >= 1
                assert results[0]["category"] == SearchResultCategory.FLIGHT.value
    
    @pytest.mark.asyncio
    async def test_search_flight_with_default_date(self):
        """日付省略時のテスト"""
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=[])
        mock_page.close = AsyncMock()
        
        with patch("app.tools.travel_search._create_page", return_value=mock_page):
            with patch("asyncio.sleep", return_value=None):
                results = await search_flight.ainvoke({
                    "departure": "HND",
                    "arrival": "FUK"
                })
                
                # フォールバック結果が返る
                assert len(results) >= 1
                assert results[0]["category"] == SearchResultCategory.FLIGHT.value
