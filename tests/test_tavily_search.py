"""
Tests for Tavily Search Tool
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.config import settings
from app.tools.tavily_search import tavily_search, search_with_tavily
from app.models.schemas import SearchResult, SearchResultCategory


class TestTavilySearch:
    """Tavily検索ツールのテスト"""
    
    @pytest.mark.asyncio
    async def test_tavily_search_returns_results(self):
        """正常な検索結果が返ることをテスト"""
        mock_response = {
            "answer": "This is an AI summary",
            "results": [
                {
                    "title": "Test Result 1",
                    "url": "https://example.com/1",
                    "content": "This is test content 1",
                    "score": 0.95
                },
                {
                    "title": "Test Result 2",
                    "url": "https://example.com/2",
                    "content": "This is test content 2",
                    "score": 0.85
                }
            ]
        }
        
        with patch.object(settings, 'TAVILY_API_KEY', 'test-api-key'):
            with patch("httpx.AsyncClient") as mock_client:
                mock_response_obj = MagicMock()
                mock_response_obj.status_code = 200
                mock_response_obj.json.return_value = mock_response
                
                mock_client_instance = AsyncMock()
                mock_client_instance.post.return_value = mock_response_obj
                mock_client.return_value.__aenter__.return_value = mock_client_instance
                
                results = await tavily_search.ainvoke({
                    "query": "test query",
                    "max_results": 5
                })
                
                # AI回答 + 2つの検索結果 = 3件
                assert len(results) == 3
                
                # AI回答
                assert results[0]["id"] == "tavily_answer"
                assert results[0]["category"] == "general"
                assert "answer" in results[0]["details"]
                
                # 検索結果
                assert results[1]["title"] == "Test Result 1"
                assert results[1]["url"] == "https://example.com/1"
                assert results[2]["title"] == "Test Result 2"
    
    @pytest.mark.asyncio
    async def test_tavily_search_without_api_key(self):
        """APIキーがない場合のエラーハンドリング"""
        with patch.object(settings, 'TAVILY_API_KEY', ''):
            results = await tavily_search.ainvoke({
                "query": "test query"
            })
            
            assert len(results) == 1
            assert results[0].get("error") is not None
            assert results[0].get("fallback") is True
    
    @pytest.mark.asyncio
    async def test_tavily_search_api_error(self):
        """APIエラー時のハンドリング"""
        with patch.object(settings, 'TAVILY_API_KEY', 'test-api-key'):
            with patch("httpx.AsyncClient") as mock_client:
                mock_response_obj = MagicMock()
                mock_response_obj.status_code = 500
                
                mock_client_instance = AsyncMock()
                mock_client_instance.post.return_value = mock_response_obj
                mock_client.return_value.__aenter__.return_value = mock_client_instance
                
                results = await tavily_search.ainvoke({
                    "query": "test query"
                })
                
                assert len(results) == 1
                assert "error" in results[0]
                assert "500" in results[0]["error"]


class TestSearchWithTavily:
    """search_with_tavily関数のテスト"""
    
    @pytest.mark.asyncio
    async def test_returns_search_result_objects(self):
        """SearchResultオブジェクトのリストが返ることをテスト"""
        mock_response = {
            "answer": None,
            "results": [
                {
                    "title": "Test Result",
                    "url": "https://example.com",
                    "content": "Test content",
                    "score": 0.9
                }
            ]
        }
        
        with patch.object(settings, 'TAVILY_API_KEY', 'test-api-key'):
            with patch("httpx.AsyncClient") as mock_client:
                mock_response_obj = MagicMock()
                mock_response_obj.status_code = 200
                mock_response_obj.json.return_value = mock_response
                
                mock_client_instance = AsyncMock()
                mock_client_instance.post.return_value = mock_response_obj
                mock_client.return_value.__aenter__.return_value = mock_client_instance
                
                results = await search_with_tavily("test query")
                
                assert len(results) == 1
                assert isinstance(results[0], SearchResult)
                assert results[0].title == "Test Result"
                assert results[0].category == SearchResultCategory.GENERAL
    
    @pytest.mark.asyncio
    async def test_returns_empty_list_on_error(self):
        """エラー時に空リストが返ることをテスト"""
        with patch.object(settings, 'TAVILY_API_KEY', ''):
            results = await search_with_tavily("test query")
            
            assert results == []
