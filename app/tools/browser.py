"""
Browser Automation Tools using Playwright
"""
from typing import Optional
from langchain_core.tools import tool
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
import asyncio
import os

# ブラウザセッション管理
_browser: Optional[Browser] = None
_context: Optional[BrowserContext] = None
_page: Optional[Page] = None


async def get_browser() -> Browser:
    """ブラウザインスタンスを取得"""
    global _browser
    if _browser is None:
        playwright = await async_playwright().start()
        _browser = await playwright.chromium.launch(
            headless=False,  # ヘッドありモードで可視化
        )
    return _browser


async def get_context() -> BrowserContext:
    """ブラウザコンテキストを取得（セッション維持用）"""
    global _context
    if _context is None:
        browser = await get_browser()
        # ユーザーデータディレクトリを使用してセッションを維持
        user_data_dir = os.path.join(os.path.expanduser("~"), ".ai_secretary", "browser_data")
        os.makedirs(user_data_dir, exist_ok=True)
        _context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
    return _context


async def get_page() -> Page:
    """ページインスタンスを取得"""
    global _page
    if _page is None:
        context = await get_context()
        _page = await context.new_page()
    return _page


@tool
async def browse_website(url: str) -> str:
    """
    指定されたURLのWebサイトを開いて内容を取得します。
    
    Args:
        url: 閲覧するWebサイトのURL
        
    Returns:
        ページのタイトルと主要なテキスト内容
    """
    try:
        page = await get_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        
        title = await page.title()
        
        # ページの主要なテキストを取得
        content = await page.evaluate("""
            () => {
                const article = document.querySelector('article, main, .content, #content');
                if (article) return article.innerText.substring(0, 5000);
                return document.body.innerText.substring(0, 5000);
            }
        """)
        
        return f"タイトル: {title}\n\n内容:\n{content}"
    except Exception as e:
        return f"エラー: Webサイトの閲覧に失敗しました - {str(e)}"


@tool
async def fill_form(selector: str, value: str) -> str:
    """
    フォームフィールドに値を入力します。
    
    Args:
        selector: 入力フィールドのCSSセレクタ
        value: 入力する値
        
    Returns:
        成功または失敗のメッセージ
    """
    try:
        page = await get_page()
        await page.fill(selector, value)
        return f"成功: '{selector}' に '{value}' を入力しました"
    except Exception as e:
        return f"エラー: フォーム入力に失敗しました - {str(e)}"


@tool
async def click_element(selector: str) -> str:
    """
    指定されたWeb要素をクリックします。
    
    Args:
        selector: クリックする要素のCSSセレクタ
        
    Returns:
        成功または失敗のメッセージ
    """
    try:
        page = await get_page()
        await page.click(selector)
        await page.wait_for_load_state("domcontentloaded")
        
        new_url = page.url
        return f"成功: '{selector}' をクリックしました。現在のURL: {new_url}"
    except Exception as e:
        return f"エラー: クリックに失敗しました - {str(e)}"


@tool
async def take_screenshot(filename: str = "screenshot.png") -> str:
    """
    現在のページのスクリーンショットを撮影します。
    
    Args:
        filename: 保存するファイル名
        
    Returns:
        保存先のパス
    """
    try:
        page = await get_page()
        screenshots_dir = os.path.join(os.path.expanduser("~"), ".ai_secretary", "screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)
        
        filepath = os.path.join(screenshots_dir, filename)
        await page.screenshot(path=filepath, full_page=True)
        
        return f"スクリーンショットを保存しました: {filepath}"
    except Exception as e:
        return f"エラー: スクリーンショットの撮影に失敗しました - {str(e)}"


async def cleanup_browser():
    """ブラウザリソースをクリーンアップ"""
    global _browser, _context, _page
    
    if _page:
        await _page.close()
        _page = None
    
    if _context:
        await _context.close()
        _context = None
    
    if _browser:
        await _browser.close()
        _browser = None

