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


# ===== Executor用: 専用スレッドでPlaywrightを実行 =====

_executor_thread: Optional[threading.Thread] = None
_executor_command_queue: queue.Queue = queue.Queue()
_executor_result_queue: queue.Queue = queue.Queue()
_executor_ready = threading.Event()
_executor_shutdown = threading.Event()
_executor_page_proxy = None


def _executor_thread_main():
    """Executor用Playwright専用スレッド"""
    # Windows用のProactorEventLoopを設定
    if hasattr(asyncio, 'WindowsProactorEventLoopPolicy'):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(_executor_worker())
    finally:
        loop.close()


async def _executor_worker():
    """Executor用ブラウザワーカー"""
    from playwright.async_api import async_playwright

    playwright = None
    browser = None
    context = None
    page = None

    try:
        print("[EXECUTOR_BROWSER] Starting Playwright...")
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=False, slow_mo=100)

        user_data_dir = os.path.join(os.path.expanduser("~"), ".ai_secretary", "browser_data")
        os.makedirs(user_data_dir, exist_ok=True)

        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        page = await context.new_page()

        print("[EXECUTOR_BROWSER] Browser ready")
        _executor_ready.set()

        # コマンドループ
        while not _executor_shutdown.is_set():
            try:
                cmd, args, result_future = _executor_command_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                result = await _execute_page_command(page, cmd, args)
                _executor_result_queue.put(("success", result))
            except Exception as e:
                _executor_result_queue.put(("error", str(e)))

    finally:
        if page:
            await page.close()
        if context:
            await context.close()
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()
        print("[EXECUTOR_BROWSER] Browser closed")


async def _execute_page_command(page, cmd: str, args: dict):
    """ページコマンドを実行"""
    if cmd == "goto":
        await page.goto(args["url"], wait_until=args.get("wait_until", "domcontentloaded"))
        return {"url": page.url}

    elif cmd == "get_url":
        return {"url": page.url}

    elif cmd == "locator_count":
        count = await page.locator(args["selector"]).count()
        return {"count": count}

    elif cmd == "locator_fill":
        await page.locator(args["selector"]).fill(args["value"])
        return {}

    elif cmd == "locator_click":
        await page.locator(args["selector"]).click(force=args.get("force", False))
        return {}

    elif cmd == "locator_select_option":
        await page.locator(args["selector"]).select_option(value=args.get("value"))
        return {}

    elif cmd == "wait_for_load_state":
        await page.wait_for_load_state(args.get("state", "domcontentloaded"))
        return {}

    elif cmd == "wait_for_timeout":
        await page.wait_for_timeout(args["timeout"])
        return {}

    elif cmd == "keyboard_press":
        await page.keyboard.press(args["key"])
        return {}

    elif cmd == "screenshot":
        await page.screenshot(path=args["path"], full_page=args.get("full_page", True))
        return {"path": args["path"]}

    elif cmd == "content":
        html = await page.content()
        return {"content": html}

    elif cmd == "evaluate":
        result = await page.evaluate(args["expression"])
        return {"result": result}

    elif cmd == "locator_is_visible":
        locator = page.locator(args["selector"])
        if args.get("index") is not None:
            locator = locator.nth(args["index"])
        visible = await locator.is_visible()
        return {"visible": visible}

    elif cmd == "locator_text_content":
        locator = page.locator(args["selector"])
        if args.get("index") is not None:
            locator = locator.nth(args["index"])
        text = await locator.text_content()
        return {"text": text or ""}

    elif cmd == "locator_get_attribute":
        locator = page.locator(args["selector"])
        if args.get("index") is not None:
            locator = locator.nth(args["index"])
        value = await locator.get_attribute(args["name"])
        return {"value": value}

    elif cmd == "locator_evaluate":
        locator = page.locator(args["selector"])
        if args.get("index") is not None:
            locator = locator.nth(args["index"])
        result = await locator.evaluate(args["expression"])
        return {"result": result}

    elif cmd == "locator_is_enabled":
        locator = page.locator(args["selector"])
        if args.get("index") is not None:
            locator = locator.nth(args["index"])
        enabled = await locator.is_enabled()
        return {"enabled": enabled}

    elif cmd == "locator_click_nth":
        await page.locator(args["selector"]).nth(args["index"]).click(force=args.get("force", False))
        return {}

    else:
        raise ValueError(f"Unknown command: {cmd}")


def _ensure_executor_thread():
    """Executor用スレッドを確保"""
    global _executor_thread

    if _executor_thread is None or not _executor_thread.is_alive():
        _executor_ready.clear()
        _executor_shutdown.clear()

        _executor_thread = threading.Thread(target=_executor_thread_main, daemon=True)
        _executor_thread.start()

        # 準備完了を待機
        if not _executor_ready.wait(timeout=30):
            raise RuntimeError("Executor browser failed to start")


def _send_executor_command(cmd: str, **args) -> dict:
    """Executorスレッドにコマンドを送信"""
    _ensure_executor_thread()

    # 結果キューをクリア
    while not _executor_result_queue.empty():
        try:
            _executor_result_queue.get_nowait()
        except queue.Empty:
            break

    _executor_command_queue.put((cmd, args, None))

    try:
        status, result = _executor_result_queue.get(timeout=120)
        if status == "error":
            raise RuntimeError(result)
        return result
    except queue.Empty:
        raise RuntimeError("Executor command timed out")


class ExecutorPageProxy:
    """
    Executor用のPage Proxy

    本物のPlaywright Pageと同じインターフェースを提供するが、
    実際の操作は専用スレッドで実行される。
    """

    def __init__(self):
        _ensure_executor_thread()

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 30000):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("goto", url=url, wait_until=wait_until)
        )

    @property
    def url(self) -> str:
        result = _send_executor_command("get_url")
        return result.get("url", "")

    def locator(self, selector: str):
        return ExecutorLocatorProxy(selector)

    async def wait_for_load_state(self, state: str = "domcontentloaded"):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("wait_for_load_state", state=state)
        )

    async def wait_for_timeout(self, timeout: int):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("wait_for_timeout", timeout=timeout)
        )

    async def screenshot(self, path: str, full_page: bool = True):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("screenshot", path=path, full_page=full_page)
        )

    async def content(self) -> str:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("content")
        )
        return result.get("content", "")

    @property
    def keyboard(self):
        return ExecutorKeyboardProxy()


class ExecutorLocatorProxy:
    """Locator Proxy"""

    def __init__(self, selector: str, index: int = None):
        self._selector = selector
        self._index = index  # nth element index (0-based)

    async def count(self) -> int:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("locator_count", selector=self._selector)
        )
        return result.get("count", 0)

    async def fill(self, value: str):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("locator_fill", selector=self._selector, value=value)
        )

    async def click(self, force: bool = False, timeout: int = 30000):
        loop = asyncio.get_event_loop()
        if self._index is not None:
            return await loop.run_in_executor(
                None, lambda: _send_executor_command("locator_click_nth", selector=self._selector, index=self._index, force=force)
            )
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("locator_click", selector=self._selector, force=force)
        )

    async def select_option(self, value: str = None, label: str = None):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("locator_select_option", selector=self._selector, value=value)
        )

    async def all(self):
        """全要素をリストで取得"""
        count = await self.count()
        # 各要素用のLocatorProxyを返す（indexを使用）
        return [ExecutorLocatorProxy(self._selector, index=i) for i in range(count)]

    async def is_visible(self) -> bool:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("locator_is_visible", selector=self._selector, index=self._index)
        )
        return result.get("visible", False)

    async def text_content(self) -> str:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("locator_text_content", selector=self._selector, index=self._index)
        )
        return result.get("text", "")

    async def get_attribute(self, name: str) -> Optional[str]:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("locator_get_attribute", selector=self._selector, name=name, index=self._index)
        )
        return result.get("value")

    async def evaluate(self, expression: str):
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("locator_evaluate", selector=self._selector, expression=expression, index=self._index)
        )
        return result.get("result")

    async def is_enabled(self) -> bool:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("locator_is_enabled", selector=self._selector, index=self._index)
        )
        return result.get("enabled", False)

    @property
    def first(self):
        return ExecutorLocatorProxy(self._selector, index=0)

    def nth(self, index: int):
        """n番目の要素を取得（0-based）"""
        return ExecutorLocatorProxy(self._selector, index=index)


class ExecutorKeyboardProxy:
    """Keyboard Proxy"""

    async def press(self, key: str):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("keyboard_press", key=key)
        )


async def get_executor_page():
    """Executor用のPage Proxyを返す"""
    return ExecutorPageProxy()


async def close_executor_browser():
    """Executor用ブラウザを閉じる"""
    global _executor_thread
    _executor_shutdown.set()
    if _executor_thread and _executor_thread.is_alive():
        _executor_thread.join(timeout=10)
    _executor_thread = None


# ===== 専用スレッドでPlaywrightを実行（旧方式、互換性のため残す） =====

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

                    elif cmd == "select_option":
                        selector = args.get("selector", "")
                        value = args.get("value")
                        label = args.get("label")
                        if value:
                            await page.select_option(selector, value=value)
                        elif label:
                            await page.select_option(selector, label=label)

                    elif cmd == "is_visible":
                        selector = args.get("selector", "")
                        elem = await page.query_selector(selector)
                        result["visible"] = elem is not None and await elem.is_visible()

                    elif cmd == "wait_for_selector":
                        selector = args.get("selector", "")
                        state = args.get("state", "visible")
                        timeout = args.get("timeout", 30000)
                        await page.wait_for_selector(selector, state=state, timeout=timeout)

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


class BrowserPage:
    """Playwright Page互換のラッパークラス"""

    def __init__(self):
        _ensure_browser_thread()

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 30000):
        """ページナビゲーション"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_command("goto", url=url, wait_until=wait_until, timeout=timeout)
        )

    async def wait_for_load_state(self, state: str = "domcontentloaded"):
        """ロード状態を待機"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_command("wait_for_load_state", state=state)
        )

    async def wait_for_timeout(self, timeout: int):
        """タイムアウト待機（ミリ秒）"""
        await asyncio.sleep(timeout / 1000)

    def locator(self, selector: str):
        """Locatorを返す"""
        return BrowserLocator(selector)

    async def query_selector(self, selector: str):
        """要素を検索"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_command("query_selector", selector=selector)
        )
        return result.get("element")

    async def fill(self, selector: str, value: str):
        """フォーム入力"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_command("fill", selector=selector, value=value)
        )

    async def click(self, selector: str, **kwargs):
        """クリック"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_command("click", selector=selector)
        )

    async def screenshot(self, path: str = "screenshot.png", full_page: bool = True):
        """スクリーンショット"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_command("screenshot", path=path, full_page=full_page)
        )

    async def content(self) -> str:
        """HTML内容を取得"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_command("evaluate", expression="document.documentElement.outerHTML")
        )
        return result.get("result", "")

    @property
    def url(self) -> str:
        """現在のURL（同期的に取得）"""
        result = _send_command("get_url")
        return result.get("url", "")


class BrowserLocator:
    """Playwright Locator互換のラッパークラス"""

    def __init__(self, selector: str):
        self._selector = selector

    async def count(self) -> int:
        """要素数を取得"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_command("query_selector_all", selector=self._selector)
        )
        return result.get("count", 0)

    async def click(self, **kwargs):
        """クリック"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_command("click", selector=self._selector)
        )

    async def fill(self, value: str):
        """入力"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_command("fill", selector=self._selector, value=value)
        )

    async def select_option(self, value: str = None, label: str = None):
        """セレクトオプションを選択"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_command("select_option", selector=self._selector, value=value, label=label)
        )

    async def is_visible(self) -> bool:
        """可視性チェック"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_command("is_visible", selector=self._selector)
        )
        return result.get("visible", False)

    async def wait_for(self, state: str = "visible", timeout: int = 30000):
        """要素の状態を待機"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_command("wait_for_selector", selector=self._selector, state=state, timeout=timeout)
        )

    async def all(self):
        """全要素をリストで取得"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_command("query_selector_all", selector=self._selector)
        )
        count = result.get("count", 0)
        # 各要素用のLocatorを返す
        return [BrowserLocator(f"{self._selector}:nth-child({i+1})") for i in range(count)]


async def get_page():
    """ページを取得（Page互換オブジェクトを返す）"""
    _ensure_browser_thread()
    return BrowserPage()


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
