"""
Web Search Tools
"""
from typing import Optional
from langchain_core.tools import tool
import httpx


@tool
async def search_web(
    query: str,
    num_results: int = 5,
) -> str:
    """
    Webで情報を検索します。
    
    Args:
        query: 検索クエリ
        num_results: 取得する結果の数
        
    Returns:
        検索結果の一覧
    """
    try:
        # DuckDuckGo Instant Answer APIを使用（無料・API key不要）
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.duckduckgo.com/",
                params={
                    "q": query,
                    "format": "json",
                    "no_html": 1,
                    "skip_disambig": 1,
                },
                timeout=10.0,
            )
            
            data = response.json()
            
            results = []
            
            # 抽象的な回答
            if data.get("Abstract"):
                results.append(f"概要: {data['Abstract']}")
                if data.get("AbstractURL"):
                    results.append(f"ソース: {data['AbstractURL']}")
            
            # 関連トピック
            related = data.get("RelatedTopics", [])[:num_results]
            if related:
                results.append("\n関連情報:")
                for topic in related:
                    if isinstance(topic, dict) and "Text" in topic:
                        text = topic["Text"][:200]
                        url = topic.get("FirstURL", "")
                        results.append(f"- {text}")
                        if url:
                            results.append(f"  URL: {url}")
            
            if not results:
                return f"「{query}」に関する情報が見つかりませんでした。より具体的な検索語を試してください。"
            
            return "\n".join(results)
            
    except httpx.TimeoutException:
        return "エラー: 検索がタイムアウトしました。後でもう一度お試しください。"
    except Exception as e:
        return f"エラー: 検索に失敗しました - {str(e)}"

