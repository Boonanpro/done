"""
Tavily Search Tool - AI-optimized web search
"""
from typing import Optional
from langchain_core.tools import tool
import httpx

from app.config import settings
from app.models.schemas import SearchResult, SearchResultCategory


@tool
async def tavily_search(
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
) -> list[dict]:
    """
    Tavily APIを使用してWeb検索を実行します。
    AI向けに最適化された検索結果を返します。
    
    Args:
        query: 検索クエリ
        max_results: 取得する結果の最大数（デフォルト: 5）
        search_depth: 検索の深さ "basic" または "advanced"
        
    Returns:
        SearchResult形式の検索結果リスト
    """
    if not settings.TAVILY_API_KEY:
        return [{
            "error": "TAVILY_API_KEY is not configured",
            "fallback": True
        }]
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.TAVILY_API_KEY,
                    "query": query,
                    "search_depth": search_depth,
                    "max_results": max_results,
                    "include_answer": True,
                    "include_raw_content": False,
                },
                timeout=30.0,
            )
            
            if response.status_code != 200:
                return [{
                    "error": f"Tavily API error: {response.status_code}",
                    "fallback": True
                }]
            
            data = response.json()
            
            results = []
            
            # AIによる回答がある場合
            if data.get("answer"):
                results.append({
                    "id": "tavily_answer",
                    "category": SearchResultCategory.GENERAL.value,
                    "title": "AI Summary",
                    "url": None,
                    "price": None,
                    "status": None,
                    "details": {
                        "answer": data["answer"],
                        "type": "ai_summary"
                    },
                    "execution_params": {}
                })
            
            # 検索結果
            for i, result in enumerate(data.get("results", [])[:max_results]):
                results.append({
                    "id": f"tavily_{i}",
                    "category": SearchResultCategory.GENERAL.value,
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "price": None,
                    "status": None,
                    "details": {
                        "content": result.get("content", ""),
                        "score": result.get("score", 0),
                    },
                    "execution_params": {
                        "source": "tavily",
                        "requires_login": False
                    }
                })
            
            return results
            
    except httpx.TimeoutException:
        return [{
            "error": "Search timed out",
            "fallback": True
        }]
    except Exception as e:
        return [{
            "error": f"Search failed: {str(e)}",
            "fallback": True
        }]


async def search_with_tavily(query: str, max_results: int = 5) -> list[SearchResult]:
    """
    Tavily検索を実行し、SearchResultオブジェクトのリストを返す
    （エージェント以外からの直接呼び出し用）
    
    Args:
        query: 検索クエリ
        max_results: 取得する結果の最大数
        
    Returns:
        SearchResultオブジェクトのリスト
    """
    raw_results = await tavily_search.ainvoke({
        "query": query,
        "max_results": max_results
    })
    
    # エラーの場合は空リストを返す
    if raw_results and isinstance(raw_results[0], dict) and raw_results[0].get("error"):
        return []
    
    return [
        SearchResult(
            id=r["id"],
            category=SearchResultCategory(r["category"]),
            title=r["title"],
            url=r.get("url"),
            price=r.get("price"),
            status=r.get("status"),
            details=r.get("details", {}),
            execution_params=r.get("execution_params", {})
        )
        for r in raw_results
    ]
