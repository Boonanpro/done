"""
Product Search Tools - EC商品検索
Playwright を使用して各ECサイトから商品情報を取得
"""
from typing import Optional
from langchain_core.tools import tool
from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeout
import asyncio
import re
import urllib.parse

from app.models.schemas import SearchResult, SearchResultCategory


# ブラウザインスタンス管理
_browser: Optional[Browser] = None


async def _get_browser() -> Browser:
    """ブラウザインスタンスを取得"""
    global _browser
    if _browser is None or not _browser.is_connected():
        playwright = await async_playwright().start()
        _browser = await playwright.chromium.launch(
            headless=True,
        )
    return _browser


async def _create_page() -> Page:
    """新しいページを作成"""
    browser = await _get_browser()
    context = await browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    page = await context.new_page()
    return page


def _extract_price(text: str) -> Optional[int]:
    """テキストから価格を抽出"""
    if not text:
        return None
    # カンマ、円記号、¥を除去して数値を抽出
    cleaned = text.replace(",", "").replace("円", "").replace("¥", "").replace("￥", "")
    match = re.search(r"(\d+)", cleaned)
    if match:
        return int(match.group(1))
    return None


@tool
async def search_amazon(
    query: str,
    max_results: int = 5,
) -> list[dict]:
    """
    Amazonで商品を検索します
    
    Args:
        query: 検索キーワード（例: "MacBook Air"）
        max_results: 取得する最大件数（デフォルト: 5）
        
    Returns:
        商品情報のリスト（SearchResult形式）
    """
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.amazon.co.jp/s?k={encoded_query}"
        
        page = await _create_page()
        
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)
            
            # 商品情報を抽出
            results = await page.evaluate(f"""
                () => {{
                    const products = [];
                    const items = document.querySelectorAll('[data-component-type="s-search-result"]');
                    
                    items.forEach((el, index) => {{
                        if (index >= {max_results}) return;
                        
                        try {{
                            // 商品名
                            const titleEl = el.querySelector('h2 a span, .a-text-normal');
                            const title = titleEl ? titleEl.innerText.trim() : '';
                            
                            // 価格
                            const priceEl = el.querySelector('.a-price .a-offscreen, .a-price-whole');
                            const price = priceEl ? priceEl.innerText.trim() : '';
                            
                            // URL
                            const linkEl = el.querySelector('h2 a');
                            const href = linkEl ? linkEl.getAttribute('href') : '';
                            
                            // レビュー数
                            const reviewEl = el.querySelector('[aria-label*="つ星"], .a-icon-alt');
                            const review = reviewEl ? reviewEl.innerText.trim() : '';
                            
                            if (title) {{
                                products.push({{
                                    title: title.substring(0, 100),
                                    price: price,
                                    url: href.startsWith('http') ? href : 'https://www.amazon.co.jp' + href,
                                    review: review
                                }});
                            }}
                        }} catch (e) {{}}
                    }});
                    
                    return products;
                }}
            """)
            
            search_results = []
            for i, product in enumerate(results[:max_results]):
                search_results.append({
                    "id": f"amazon_{i}",
                    "category": SearchResultCategory.PRODUCT.value,
                    "title": product.get("title", f"商品 {i+1}"),
                    "url": product.get("url", url),
                    "price": _extract_price(product.get("price", "")),
                    "status": None,
                    "details": {
                        "source": "Amazon",
                        "review": product.get("review", ""),
                        "price_text": product.get("price", ""),
                    },
                    "execution_params": {
                        "service": "amazon",
                        "requires_login": True,
                    }
                })
            
            if not search_results:
                search_results.append({
                    "id": "amazon_0",
                    "category": SearchResultCategory.PRODUCT.value,
                    "title": f"Amazon検索: {query}",
                    "url": url,
                    "price": None,
                    "status": None,
                    "details": {
                        "message": "Failed to retrieve product info. Please check the URL directly.",
                        "source": "Amazon",
                    },
                    "execution_params": {
                        "service": "amazon",
                        "requires_login": True,
                    }
                })
            
            return search_results
            
        finally:
            await page.close()
            
    except PlaywrightTimeout:
        return [{
            "error": "検索がタイムアウトしました",
            "fallback": True
        }]
    except Exception as e:
        return [{
            "error": f"検索に失敗しました: {str(e)}",
            "fallback": True
        }]


@tool
async def search_rakuten(
    query: str,
    max_results: int = 5,
) -> list[dict]:
    """
    楽天市場で商品を検索します
    
    Args:
        query: 検索キーワード（例: "MacBook Air"）
        max_results: 取得する最大件数（デフォルト: 5）
        
    Returns:
        商品情報のリスト（SearchResult形式）
    """
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://search.rakuten.co.jp/search/mall/{encoded_query}/"
        
        page = await _create_page()
        
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)
            
            results = await page.evaluate(f"""
                () => {{
                    const products = [];
                    const items = document.querySelectorAll('.searchresultitem, [class*="dui-card"]');
                    
                    items.forEach((el, index) => {{
                        if (index >= {max_results}) return;
                        
                        try {{
                            const titleEl = el.querySelector('.title a, [class*="title"] a');
                            const title = titleEl ? titleEl.innerText.trim() : '';
                            
                            const priceEl = el.querySelector('.price, [class*="price"]');
                            const price = priceEl ? priceEl.innerText.trim() : '';
                            
                            const linkEl = el.querySelector('.title a, [class*="title"] a');
                            const href = linkEl ? linkEl.getAttribute('href') : '';
                            
                            if (title) {{
                                products.push({{
                                    title: title.substring(0, 100),
                                    price: price,
                                    url: href
                                }});
                            }}
                        }} catch (e) {{}}
                    }});
                    
                    return products;
                }}
            """)
            
            search_results = []
            for i, product in enumerate(results[:max_results]):
                search_results.append({
                    "id": f"rakuten_{i}",
                    "category": SearchResultCategory.PRODUCT.value,
                    "title": product.get("title", f"商品 {i+1}"),
                    "url": product.get("url", url),
                    "price": _extract_price(product.get("price", "")),
                    "status": None,
                    "details": {
                        "source": "楽天市場",
                        "price_text": product.get("price", ""),
                    },
                    "execution_params": {
                        "service": "rakuten",
                        "requires_login": True,
                    }
                })
            
            if not search_results:
                search_results.append({
                    "id": "rakuten_0",
                    "category": SearchResultCategory.PRODUCT.value,
                    "title": f"楽天市場検索: {query}",
                    "url": url,
                    "price": None,
                    "status": None,
                    "details": {
                        "message": "Failed to retrieve product info. Please check the URL directly.",
                        "source": "楽天市場",
                    },
                    "execution_params": {
                        "service": "rakuten",
                        "requires_login": True,
                    }
                })
            
            return search_results
            
        finally:
            await page.close()
            
    except PlaywrightTimeout:
        return [{
            "error": "検索がタイムアウトしました",
            "fallback": True
        }]
    except Exception as e:
        return [{
            "error": f"検索に失敗しました: {str(e)}",
            "fallback": True
        }]


@tool
async def search_kakaku(
    query: str,
    max_results: int = 5,
) -> list[dict]:
    """
    価格.comで商品を検索します（価格比較）
    
    Args:
        query: 検索キーワード（例: "MacBook Air"）
        max_results: 取得する最大件数（デフォルト: 5）
        
    Returns:
        商品情報のリスト（SearchResult形式）
    """
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://kakaku.com/search_results/{encoded_query}/"
        
        page = await _create_page()
        
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)
            
            results = await page.evaluate(f"""
                () => {{
                    const products = [];
                    const items = document.querySelectorAll('.p-result_item, .itemBox');
                    
                    items.forEach((el, index) => {{
                        if (index >= {max_results}) return;
                        
                        try {{
                            const titleEl = el.querySelector('.p-result_item_title a, .itemTitle a');
                            const title = titleEl ? titleEl.innerText.trim() : '';
                            
                            const priceEl = el.querySelector('.p-result_item_price, .itemPrice');
                            const price = priceEl ? priceEl.innerText.trim() : '';
                            
                            const linkEl = el.querySelector('.p-result_item_title a, .itemTitle a');
                            const href = linkEl ? linkEl.getAttribute('href') : '';
                            
                            if (title) {{
                                products.push({{
                                    title: title.substring(0, 100),
                                    price: price,
                                    url: href.startsWith('http') ? href : 'https://kakaku.com' + href
                                }});
                            }}
                        }} catch (e) {{}}
                    }});
                    
                    return products;
                }}
            """)
            
            search_results = []
            for i, product in enumerate(results[:max_results]):
                search_results.append({
                    "id": f"kakaku_{i}",
                    "category": SearchResultCategory.PRODUCT.value,
                    "title": product.get("title", f"商品 {i+1}"),
                    "url": product.get("url", url),
                    "price": _extract_price(product.get("price", "")),
                    "status": None,
                    "details": {
                        "source": "価格.com",
                        "price_text": product.get("price", ""),
                    },
                    "execution_params": {
                        "service": "kakaku",
                        "requires_login": False,
                    }
                })
            
            if not search_results:
                search_results.append({
                    "id": "kakaku_0",
                    "category": SearchResultCategory.PRODUCT.value,
                    "title": f"価格.com検索: {query}",
                    "url": url,
                    "price": None,
                    "status": None,
                    "details": {
                        "message": "Failed to retrieve product info. Please check the URL directly.",
                        "source": "価格.com",
                    },
                    "execution_params": {
                        "service": "kakaku",
                        "requires_login": False,
                    }
                })
            
            return search_results
            
        finally:
            await page.close()
            
    except PlaywrightTimeout:
        return [{
            "error": "検索がタイムアウトしました",
            "fallback": True
        }]
    except Exception as e:
        return [{
            "error": f"検索に失敗しました: {str(e)}",
            "fallback": True
        }]


@tool
async def search_products(
    query: str,
    sites: Optional[list[str]] = None,
    max_results: int = 3,
) -> list[dict]:
    """
    複数のECサイトで商品を検索して比較します
    
    Args:
        query: 検索キーワード（例: "MacBook Air"）
        sites: 検索するサイト（"amazon", "rakuten", "kakaku"）省略時は全サイト
        max_results: 各サイトから取得する最大件数（デフォルト: 3）
        
    Returns:
        全サイトの商品情報を統合したリスト
    """
    if sites is None:
        sites = ["amazon", "rakuten", "kakaku"]
    
    all_results = []
    
    # 並列で検索実行
    tasks = []
    for site in sites:
        if site == "amazon":
            tasks.append(("amazon", search_amazon.ainvoke({"query": query, "max_results": max_results})))
        elif site == "rakuten":
            tasks.append(("rakuten", search_rakuten.ainvoke({"query": query, "max_results": max_results})))
        elif site == "kakaku":
            tasks.append(("kakaku", search_kakaku.ainvoke({"query": query, "max_results": max_results})))
    
    # 結果を収集
    for site_name, task in tasks:
        try:
            results = await task
            if results and not results[0].get("error"):
                all_results.extend(results)
        except Exception:
            pass
    
    # 価格でソート（安い順）
    all_results.sort(key=lambda x: x.get("price") or float("inf"))
    
    return all_results if all_results else [{
        "id": "product_0",
        "category": SearchResultCategory.PRODUCT.value,
        "title": f"商品検索: {query}",
        "url": f"https://www.google.com/search?q={urllib.parse.quote(query)}",
        "price": None,
        "status": None,
        "details": {
            "message": "Failed to retrieve product info.",
        },
        "execution_params": {}
    }]


async def cleanup_product_browser():
    """ブラウザリソースをクリーンアップ"""
    global _browser
    if _browser:
        await _browser.close()
        _browser = None
