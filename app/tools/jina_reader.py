"""
Jina AI Reader - URLからページ内容を取得
https://r.jina.ai/{url} にアクセスするだけでページをMarkdown化
"""
import logging
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

# Jina Reader API endpoint
JINA_READER_BASE_URL = "https://r.jina.ai/"


async def read_url(url: str, timeout: int = 30) -> dict:
    """
    URLのページ内容をJina AI Readerで取得
    
    Args:
        url: 読み込むURL
        timeout: タイムアウト秒数
        
    Returns:
        {
            "success": True/False,
            "content": "Markdown形式のページ内容",
            "url": "元のURL",
            "error": "エラーメッセージ（失敗時）"
        }
    """
    try:
        jina_url = f"{JINA_READER_BASE_URL}{url}"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                jina_url,
                timeout=timeout,
                headers={
                    "Accept": "text/markdown",
                },
                follow_redirects=True,
            )
            
            if response.status_code == 200:
                content = response.text
                logger.info(f"Jina Reader: Successfully read {url} ({len(content)} chars)")
                return {
                    "success": True,
                    "content": content,
                    "url": url,
                }
            else:
                logger.warning(f"Jina Reader: Failed to read {url}, status={response.status_code}")
                return {
                    "success": False,
                    "content": "",
                    "url": url,
                    "error": f"HTTP {response.status_code}",
                }
                
    except httpx.TimeoutException:
        logger.warning(f"Jina Reader: Timeout reading {url}")
        return {
            "success": False,
            "content": "",
            "url": url,
            "error": "Timeout",
        }
    except Exception as e:
        logger.exception(f"Jina Reader: Error reading {url}")
        return {
            "success": False,
            "content": "",
            "url": url,
            "error": str(e),
        }


async def read_urls(urls: list[str], timeout: int = 30) -> list[dict]:
    """
    複数URLのページ内容を一括取得
    
    Args:
        urls: 読み込むURLのリスト
        timeout: 各URLのタイムアウト秒数
        
    Returns:
        各URLの読み込み結果のリスト
    """
    results = []
    for url in urls:
        result = await read_url(url, timeout)
        results.append(result)
    return results


async def search_and_read(
    search_results: list[dict],
    max_pages: int = 3,
    timeout: int = 30,
) -> list[dict]:
    """
    検索結果からURLを抽出してページ内容を取得
    
    Args:
        search_results: Tavily等の検索結果
        max_pages: 読み込む最大ページ数
        timeout: 各URLのタイムアウト秒数
        
    Returns:
        ページ内容を含む検索結果のリスト
    """
    enriched_results = []
    pages_read = 0
    
    for result in search_results:
        url = result.get("url")
        
        if url and pages_read < max_pages:
            page_content = await read_url(url, timeout)
            
            if page_content["success"]:
                result["page_content"] = page_content["content"]
                pages_read += 1
            else:
                result["page_content"] = None
                result["page_error"] = page_content.get("error")
        
        enriched_results.append(result)
    
    return enriched_results


