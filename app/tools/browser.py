"""
Browser Automation Tools using Playwright
Uses a dedicated thread with its own event loop to avoid Windows asyncio issues
"""
from typing import Optional, Any
from langchain_core.tools import tool
import asyncio
import os
import threading
import queue


# ===== 専用スレッドでPlaywrightを実行 =====

_browser_thread: Optional[threading.Thread] = None
_command_queue: queue.Queue = queue.Queue()
_result_queue: queue.Queue = queue.Queue()
_thread_ready = threading.Event()
_shutdown_event = threading.Event()


def _browser_thread_main():
    """Playwright専用スレッドのメイン関数"""
    import asyncio
    
    # Windows用のイベントループポリシーを設定
    if hasattr(asyncio, 'WindowsProactorEventLoopPolicy'):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    # 新しいイベントループを作成
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(_browser_worker())
    finally:
        loop.close()


async def _browser_worker():
    """ブラウザワーカー（専用スレッド内で実行）"""
    from playwright.async_api import async_playwright
    
    playwright = None
    browser = None
    context = None
    page = None
    
    try:
        # Playwrightを初期化
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=False)
        
        user_data_dir = os.path.join(os.path.expanduser("~"), ".ai_secretary", "browser_data")
        os.makedirs(user_data_dir, exist_ok=True)
        
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = await context.new_page()
        
        # 準備完了を通知
        _thread_ready.set()
        
        # コマンドループ
        while not _shutdown_event.is_set():
            try:
                # コマンドを取得（タイムアウト付き）
                try:
                    cmd, args = _command_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                
                result = {"success": True}
                
                try:
                    if cmd == "goto":
                        await page.goto(
                            args.get("url", ""),
                            wait_until=args.get("wait_until", "domcontentloaded"),
                            timeout=args.get("timeout", 30000)
                        )
                    
                    elif cmd == "wait_for_load_state":
                        await page.wait_for_load_state(args.get("state", "domcontentloaded"))
                    
                    elif cmd == "query_selector":
                        element = await page.query_selector(args.get("selector", ""))
                        result["element"] = element
                    
                    elif cmd == "query_selector_all":
                        elements = await page.query_selector_all(args.get("selector", ""))
                        result["count"] = len(elements)
                        result["elements"] = elements
                    
                    elif cmd == "fill":
                        selector = args.get("selector", "")
                        element = args.get("element")
                        if element:
                            await element.fill(args.get("value", ""))
                        elif selector:
                            await page.fill(selector, args.get("value", ""))
                    
                    elif cmd == "click":
                        selector = args.get("selector", "")
                        element = args.get("element")
                        if element:
                            await element.click()
                        elif selector:
                            await page.click(selector)
                    
                    elif cmd == "get_url":
                        result["url"] = page.url
                    
                    elif cmd == "get_title":
                        result["title"] = await page.title()
                    
                    elif cmd == "screenshot":
                        path = args.get("path", "screenshot.png")
                        dir_path = os.path.dirname(path)
                        if dir_path:
                            os.makedirs(dir_path, exist_ok=True)
                        await page.screenshot(path=path, full_page=args.get("full_page", True))
                        result["path"] = path
                    
                    elif cmd == "evaluate":
                        result["result"] = await page.evaluate(args.get("expression", ""))
                    
                    elif cmd == "text_content":
                        element = args.get("element")
                        if element:
                            result["text"] = await element.text_content()
                        else:
                            selector = args.get("selector", "")
                            elem = await page.query_selector(selector)
                            result["text"] = await elem.text_content() if elem else None
                    
                    elif cmd == "shutdown":
                        _shutdown_event.set()
                    
                except Exception as e:
                    result = {"success": False, "error": str(e)}
                
                _result_queue.put(result)
                
            except Exception as e:
                _result_queue.put({"success": False, "error": str(e)})
    
    finally:
        # クリーンアップ
        if page:
            await page.close()
        if context:
            await context.close()
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()


def _ensure_browser_thread():
    """ブラウザスレッドを確保"""
    global _browser_thread
    
    if _browser_thread is None or not _browser_thread.is_alive():
        _thread_ready.clear()
        _shutdown_event.clear()
        
        _browser_thread = threading.Thread(target=_browser_thread_main, daemon=True)
        _browser_thread.start()
        
        # スレッドの準備完了を待機
        _thread_ready.wait(timeout=30)


def _send_command(cmd: str, **kwargs) -> dict:
    """コマンドを送信して結果を待機"""
    _ensure_browser_thread()
    
    # 結果キューをクリア
    while not _result_queue.empty():
        try:
            _result_queue.get_nowait()
        except queue.Empty:
            break
    
    _command_queue.put((cmd, kwargs))
    
    try:
        result = _result_queue.get(timeout=60)
        return result
    except queue.Empty:
        return {"success": False, "error": "Command timed out"}


async def get_page():
    """ページを取得（互換性のため）"""
    _ensure_browser_thread()
    return True  # ダミー値を返す


async def page_goto(url: str, wait_until: str = "domcontentloaded", timeout: int = 30000):
    """ページナビゲーション"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _send_command, "goto",
    ) if False else await loop.run_in_executor(
        None, lambda: _send_command("goto", url=url, wait_until=wait_until, timeout=timeout)
    )


async def page_wait_for_load_state(state: str = "domcontentloaded"):
    """ロード状態を待機"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: _send_command("wait_for_load_state", state=state)
    )


async def page_wait_for_timeout(timeout: int):
    """タイムアウト待機（ミリ秒）"""
    await asyncio.sleep(timeout / 1000)


async def page_query_selector(selector: str):
    """要素を検索"""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: _send_command("query_selector", selector=selector)
    )
    return result.get("element")


async def page_query_selector_all(selector: str):
    """複数要素を検索"""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: _send_command("query_selector_all", selector=selector)
    )
    return result.get("elements", [])


async def page_fill(selector: str, value: str):
    """フォーム入力"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: _send_command("fill", selector=selector, value=value)
    )


async def page_click(selector: str):
    """クリック"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: _send_command("click", selector=selector)
    )


async def page_url() -> str:
    """現在のURLを取得"""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: _send_command("get_url")
    )
    return result.get("url", "")


async def page_title() -> str:
    """タイトルを取得"""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: _send_command("get_title")
    )
    return result.get("title", "")


async def page_screenshot(path: str, full_page: bool = True):
    """スクリーンショット"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: _send_command("screenshot", path=path, full_page=full_page)
    )


async def page_evaluate(expression: str):
    """JavaScript実行"""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: _send_command("evaluate", expression=expression)
    )
    return result.get("result")


async def element_fill(element, value: str):
    """要素に入力"""
    if element:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_command("fill", element=element, value=value)
        )


async def element_click(element):
    """要素をクリック"""
    if element:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_command("click", element=element)
        )


async def element_text_content(element):
    """要素のテキストを取得"""
    if element:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_command("text_content", element=element)
        )
        return result.get("text")
    return None


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
        await page_goto(url)
        
        title = await page_title()
        
        # ページの主要なテキストを取得
        content = await page_evaluate("""
            () => {
                const article = document.querySelector('article, main, .content, #content');
                if (article) return article.innerText.substring(0, 5000);
                return document.body.innerText.substring(0, 5000);
            }
        """)
        
        return f"Title: {title}\n\nContent:\n{content}"
    except Exception as e:
        return f"Error: Failed to browse website - {str(e)}"


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
        await page_fill(selector, value)
        return f"Success: Filled '{selector}' with '{value}'"
    except Exception as e:
        return f"Error: Failed to fill form - {str(e)}"


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
        await page_click(selector)
        await page_wait_for_load_state()
        
        new_url = await page_url()
        return f"Success: Clicked '{selector}'. Current URL: {new_url}"
    except Exception as e:
        return f"Error: Failed to click - {str(e)}"


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
        screenshots_dir = os.path.join(os.path.expanduser("~"), ".ai_secretary", "screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)
        
        filepath = os.path.join(screenshots_dir, filename)
        await page_screenshot(filepath, full_page=True)
        
        return f"Screenshot saved: {filepath}"
    except Exception as e:
        return f"Error: Failed to take screenshot - {str(e)}"


async def cleanup_browser():
    """ブラウザリソースをクリーンアップ"""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, lambda: _send_command("shutdown")
    )
