"""
Browser Automation Tools using Playwright
Uses a dedicated thread with its own event loop to avoid Windows asyncio issues
"""
from typing import Optional, Any
import asyncio
import logging
import os
import threading
import queue

logger = logging.getLogger(__name__)


# ===== Executor用: 専用スレッドでPlaywrightを実行 =====

_executor_thread: Optional[threading.Thread] = None
_executor_command_queue: queue.Queue = queue.Queue()
_executor_result_queue: queue.Queue = queue.Queue()
_executor_ready = threading.Event()
_executor_shutdown = threading.Event()
_executor_page_proxy = None
_executor_browser_alive = threading.Event()  # ブラウザ生存フラグ


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

    # ページ状態を管理（複数タブ対応）
    pages_state = {
        "current": None,  # 現在アクティブなページ
        "all_pages": [],  # 全てのページ
    }

    def on_new_page(new_page):
        """新しいタブ/ページが開かれた時のハンドラ"""
        print(f"[EXECUTOR_BROWSER] New tab opened: {new_page.url}")
        pages_state["all_pages"].append(new_page)

    try:
        print("[EXECUTOR_BROWSER] Starting Playwright...")
        playwright = await async_playwright().start()

        user_data_dir = os.path.join(os.path.expanduser("~"), ".ai_secretary", "browser_data")
        os.makedirs(user_data_dir, exist_ok=True)

        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            slow_mo=100,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        browser = context  # persistent contextではcontextがbrowser相当

        # 新しいタブを検知するリスナーを登録
        context.on("page", on_new_page)

        # persistent contextは最初のページを自動作成する
        if context.pages:
            page = context.pages[0]
        else:
            page = await context.new_page()
        pages_state["current"] = page
        pages_state["all_pages"].append(page)

        print("[EXECUTOR_BROWSER] Browser ready")
        _executor_ready.set()
        _executor_browser_alive.set()  # ブラウザ生存フラグをセット

        # コマンドループ
        while not _executor_shutdown.is_set():
            try:
                cmd, args, result_future = _executor_command_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                result = await _execute_page_command(pages_state, context, cmd, args)
                _executor_result_queue.put(("success", result))
            except Exception as e:
                error_str = str(e).lower()
                # ブラウザクローズエラーを検出
                if "closed" in error_str or "target" in error_str or "disposed" in error_str:
                    print(f"[EXECUTOR_BROWSER] Browser has been closed: {e}")
                    _executor_browser_alive.clear()  # ブラウザ死亡をマーク
                    _executor_result_queue.put(("browser_closed", str(e)))
                    break  # ワーカーループを終了してスレッドを終了させる
                _executor_result_queue.put(("error", str(e)))

    finally:
        _executor_browser_alive.clear()  # ブラウザ死亡をマーク
        try:
            if page:
                await page.close()
        except Exception:
            pass
        try:
            if context:
                await context.close()
        except Exception:
            pass
        try:
            if browser:
                await browser.close()
        except Exception:
            pass
        try:
            if playwright:
                await playwright.stop()
        except Exception:
            pass
        print("[EXECUTOR_BROWSER] Browser closed")


async def _execute_page_command(pages_state: dict, context, cmd: str, args: dict):
    """ページコマンドを実行"""
    page = pages_state["current"]

    # タブ管理コマンド
    if cmd == "switch_to_latest_tab":
        # 最新のタブに切り替え
        all_pages = pages_state["all_pages"]
        if len(all_pages) > 1:
            # 閉じられたページを除外
            valid_pages = [p for p in all_pages if not p.is_closed()]
            pages_state["all_pages"] = valid_pages

            if valid_pages:
                latest = valid_pages[-1]
                if latest != pages_state["current"]:
                    pages_state["current"] = latest
                    await latest.bring_to_front()
                    await latest.wait_for_load_state("domcontentloaded")
                    print(f"[EXECUTOR_BROWSER] Switched to tab: {latest.url}")
                    return {"switched": True, "url": latest.url, "tab_count": len(valid_pages)}
        return {"switched": False, "url": page.url, "tab_count": len(pages_state["all_pages"])}

    elif cmd == "get_tab_count":
        # 有効なタブ数を取得
        valid_pages = [p for p in pages_state["all_pages"] if not p.is_closed()]
        pages_state["all_pages"] = valid_pages
        return {"count": len(valid_pages), "current_url": page.url}

    elif cmd == "close_current_tab":
        # 現在のタブを閉じて前のタブに切り替え
        all_pages = pages_state["all_pages"]
        if len(all_pages) > 1:
            current = pages_state["current"]
            all_pages.remove(current)
            await current.close()
            pages_state["current"] = all_pages[-1]
            await pages_state["current"].bring_to_front()
            return {"closed": True, "url": pages_state["current"].url}
        return {"closed": False, "url": page.url}

    elif cmd == "goto":
        await page.goto(args["url"], wait_until=args.get("wait_until", "domcontentloaded"))
        return {"url": page.url}

    elif cmd == "get_url":
        return {"url": page.url}

    elif cmd == "save_image":
        # URLから画像をダウンロードしてファイルに保存
        url = args["url"]
        save_path = args["path"]
        response = await context.request.get(url)
        body = await response.body()
        import pathlib
        pathlib.Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(body)
        return {"saved": save_path, "size": len(body)}

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
        timeout = args.get("timeout")
        if timeout:
            await page.wait_for_load_state(args.get("state", "domcontentloaded"), timeout=timeout)
        else:
            await page.wait_for_load_state(args.get("state", "domcontentloaded"))
        return {}

    elif cmd == "wait_for_timeout":
        await page.wait_for_timeout(args["timeout"])
        return {}

    elif cmd == "keyboard_press":
        await page.keyboard.press(args["key"])
        return {}

    elif cmd == "keyboard_type":
        # テキストを入力（一文字ずつではなく一括）
        await page.keyboard.type(args["text"], delay=args.get("delay", 50))
        return {}

    elif cmd == "screenshot":
        await page.screenshot(path=args["path"], full_page=args.get("full_page", True))
        return {"path": args["path"]}

    elif cmd == "screenshot_base64":
        import base64
        screenshot_bytes = await page.screenshot(full_page=args.get("full_page", False))
        base64_str = base64.b64encode(screenshot_bytes).decode('utf-8')
        return {"base64": base64_str, "media_type": "image/png"}

    elif cmd == "mouse_click":
        await page.mouse.click(args["x"], args["y"])
        return {}

    elif cmd == "mouse_move":
        await page.mouse.move(args["x"], args["y"])
        return {}

    elif cmd == "go_back":
        await page.go_back()
        return {"url": page.url}

    elif cmd == "go_forward":
        await page.go_forward()
        return {"url": page.url}

    elif cmd == "reload":
        await page.reload()
        return {"url": page.url}

    elif cmd == "content":
        html = await page.content()
        return {"content": html}

    elif cmd == "evaluate":
        result = await page.evaluate(args["expression"])
        return {"result": result}

    elif cmd == "wait_for_selector":
        try:
            element = await page.wait_for_selector(
                args["selector"],
                timeout=args.get("timeout", 30000),
                state=args.get("state", "visible")
            )
            return {"found": element is not None}
        except Exception:
            return {"found": False}

    elif cmd == "query_selector":
        element = await page.query_selector(args["selector"])
        return {"found": element is not None}

    elif cmd == "query_selector_all":
        elements = await page.query_selector_all(args["selector"])
        return {"count": len(elements)}

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

    elif cmd == "aria_snapshot":
        # Playwrightのアクセシビリティツリーを取得
        snapshot = await page.accessibility.snapshot()
        return {"snapshot": snapshot}

    elif cmd == "get_interactive_elements":
        # インタラクティブ要素のリストを取得（ダンの視覚用）
        # JavaScriptで要素を列挙し、ref IDを振る
        script = """
        () => {
            const interactiveSelectors = [
                'a[href]', 'button', 'input', 'select', 'textarea',
                '[role="button"]', '[role="link"]', '[role="checkbox"]',
                '[role="radio"]', '[role="combobox"]', '[role="textbox"]',
                '[role="searchbox"]', '[role="listbox"]', '[role="option"]',
                '[tabindex]:not([tabindex="-1"])', '[onclick]'
            ];

            const elements = [];
            const seen = new Set();
            let refId = 1;

            for (const selector of interactiveSelectors) {
                for (const el of document.querySelectorAll(selector)) {
                    if (seen.has(el)) continue;
                    seen.add(el);

                    // 表示されている要素のみ
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) continue;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') continue;

                    // data-ref属性を付与
                    const ref = `e${refId++}`;
                    el.setAttribute('data-dan-ref', ref);

                    // 要素情報を収集
                    const tagName = el.tagName.toLowerCase();
                    const type = el.getAttribute('type') || '';
                    const role = el.getAttribute('role') || tagName;
                    const text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().slice(0, 50);
                    const name = el.getAttribute('name') || '';
                    const id = el.id || '';

                    // ARIA状態を収集
                    const states = [];
                    if (el.disabled || el.getAttribute('aria-disabled') === 'true') states.push('disabled');
                    if (el.getAttribute('aria-checked') === 'true') states.push('checked');
                    if (el.getAttribute('aria-expanded') === 'true') states.push('expanded');
                    if (el.getAttribute('aria-expanded') === 'false') states.push('collapsed');
                    if (el.getAttribute('aria-selected') === 'true') states.push('selected');
                    if (el.required || el.getAttribute('aria-required') === 'true') states.push('required');

                    elements.push({
                        ref: '@' + ref,
                        tag: tagName,
                        role: role,
                        type: type,
                        text: text,
                        name: name,
                        id: id,
                        states: states,
                        rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) }
                    });
                }
            }

            return elements;
        }
        """
        elements = await page.evaluate(script)
        return {"elements": elements, "count": len(elements)}

    elif cmd == "click_by_ref":
        # data-dan-ref属性でクリック
        ref = args["ref"].replace("@", "")
        timeout = args.get("timeout", 30000)
        await page.locator(f'[data-dan-ref="{ref}"]').click(force=args.get("force", False), timeout=timeout)
        return {}

    elif cmd == "fill_by_ref":
        # data-dan-ref属性で入力
        ref = args["ref"].replace("@", "")
        await page.locator(f'[data-dan-ref="{ref}"]').fill(args["value"])
        return {}

    elif cmd == "get_page_summary":
        # ページの要約情報を取得（タイトル、URL、主要なテキスト）
        title = await page.title()
        url = page.url

        # 主要なテキストを取得
        main_text_script = """
        () => {
            const mainSelectors = ['main', 'article', '#content', '.content', '#main', '.main'];
            for (const sel of mainSelectors) {
                const el = document.querySelector(sel);
                if (el) return el.innerText.slice(0, 1000);
            }
            return document.body.innerText.slice(0, 1000);
        }
        """
        main_text = await page.evaluate(main_text_script)

        return {
            "title": title,
            "url": url,
            "main_text": main_text
        }

    elif cmd == "get_page_context":
        # ページ状態の汎用スナップショット（OpenClaw方式）
        script = """
        () => {
            const ctx = {};

            // 1. 見出し（ページの文脈理解）
            ctx.headings = [...document.querySelectorAll('h1, h2, h3')]
                .slice(0, 5)
                .map(el => ({ level: el.tagName, text: el.innerText.trim().slice(0, 80) }))
                .filter(h => h.text);

            // 2. フィードバックメッセージ（成功/エラー/警告/情報）
            const feedbackSelectors = [
                '[role="alert"]', '[role="status"]',
                '[class*="error"]', '[class*="success"]', '[class*="warning"]', '[class*="info"]',
                '[class*="notification"]', '[class*="toast"]', '[class*="banner"]', '[class*="message"]'
            ];
            const feedbackEls = document.querySelectorAll(feedbackSelectors.join(','));
            const seen = new Set();
            ctx.feedback = [];
            feedbackEls.forEach(el => {
                const text = (el.innerText || '').trim().slice(0, 120);
                if (text && !seen.has(text) && text.length > 2) {
                    seen.add(text);
                    ctx.feedback.push(text);
                }
            });
            ctx.feedback = ctx.feedback.slice(0, 5);

            // 3. モーダル/ダイアログの有無と内容
            const modal = document.querySelector('dialog[open], [role="dialog"], [class*="modal"][class*="show"]');
            if (modal) {
                ctx.modal = (modal.innerText || '').trim().slice(0, 200);
            } else {
                ctx.modal = null;
            }

            // 4. ローディング状態
            ctx.isLoading = document.querySelectorAll(
                '[class*="spinner"], [class*="loading"], [aria-busy="true"], [class*="skeleton"]'
            ).length > 0;

            // 5. バッジ/カウンター
            const badges = [];
            document.querySelectorAll('[class*="badge"], [class*="count"], [class*="cart-count"]')
                .forEach(el => {
                    const text = (el.innerText || '').trim();
                    const parent = el.closest('a, button, [role="link"]');
                    const context = parent ? (parent.getAttribute('aria-label') || parent.innerText || '').trim().slice(0, 30) : '';
                    if (text && /^\\d+$/.test(text)) {
                        badges.push({ value: text, context: context || 'unknown' });
                    }
                });
            ctx.badges = badges.slice(0, 5);

            // 6. 入力済みフォーム値（パスワードは除外）
            const filledInputs = [];
            document.querySelectorAll('input, textarea, select').forEach(el => {
                if (el.type === 'password' || el.type === 'hidden') return;
                const val = el.value || '';
                if (!val) return;
                const label = el.getAttribute('aria-label') || el.placeholder
                    || (el.labels && el.labels[0] ? el.labels[0].innerText : '') || el.name || '';
                filledInputs.push({ label: label.trim().slice(0, 40), value: val.trim().slice(0, 50) });
            });
            ctx.filledInputs = filledInputs.slice(0, 10);

            return ctx;
        }
        """
        result = await page.evaluate(script)
        return {"context": result}

    else:
        raise ValueError(f"Unknown command: {cmd}")


def _ensure_executor_thread():
    """Executor用スレッドを確保（ブラウザ生存チェック付き）"""
    global _executor_thread, _executor_command_queue, _executor_result_queue

    # スレッドが生きていてもブラウザが死んでいれば再起動が必要
    need_restart = (
        _executor_thread is None or
        not _executor_thread.is_alive() or
        not _executor_browser_alive.is_set()  # ブラウザ死亡チェック
    )

    if need_restart:
        # 既存スレッドが生きている場合はシャットダウンを待つ
        if _executor_thread is not None and _executor_thread.is_alive():
            print("[EXECUTOR_BROWSER] Browser died, shutting down old thread...")
            _executor_shutdown.set()
            _executor_thread.join(timeout=5)

        _executor_ready.clear()
        _executor_shutdown.clear()
        _executor_browser_alive.clear()

        # キューをクリア（古いセッションのゴミを除去）
        _executor_command_queue = queue.Queue()
        _executor_result_queue = queue.Queue()

        _executor_thread = threading.Thread(target=_executor_thread_main, daemon=True)
        _executor_thread.start()

        print("[EXECUTOR_BROWSER] Waiting for browser to be ready...")

        # 準備完了を待機
        if not _executor_ready.wait(timeout=30):
            raise RuntimeError("Executor browser failed to start")


def _send_executor_command(cmd: str, **args) -> dict:
    """Executorスレッドにコマンドを送信（ブラウザクローズ時は自動再起動、キャンセル対応）"""
    from app.services.cancellation import CancellationRegistry, CancelledError

    max_retries = 2  # ブラウザクローズ時のリトライ回数

    # コマンド送信前にキャンセルチェック
    if CancellationRegistry.check_cancelled():
        session_id = CancellationRegistry.get_current_session()
        print(f"[EXECUTOR_BROWSER] Command cancelled before execution: {cmd}")
        raise CancelledError(session_id or "unknown", "ブラウザ操作がキャンセルされました")

    for attempt in range(max_retries):
        _ensure_executor_thread()

        # 結果キューをクリア
        while not _executor_result_queue.empty():
            try:
                _executor_result_queue.get_nowait()
            except queue.Empty:
                break

        _executor_command_queue.put((cmd, args, None))

        # 結果を待機（短いタイムアウトでループし、キャンセルをチェック）
        wait_timeout = 2.0  # 2秒ごとにキャンセルチェック
        total_timeout = 60.0  # 全体のタイムアウト
        elapsed = 0.0

        while elapsed < total_timeout:
            # キャンセルチェック
            if CancellationRegistry.check_cancelled():
                session_id = CancellationRegistry.get_current_session()
                print(f"[EXECUTOR_BROWSER] Command cancelled during execution: {cmd}")
                raise CancelledError(session_id or "unknown", "ブラウザ操作がキャンセルされました")

            try:
                status, result = _executor_result_queue.get(timeout=wait_timeout)
                if status == "error":
                    raise RuntimeError(result)
                elif status == "browser_closed":
                    # ブラウザが閉じられた - 再起動してリトライ
                    if attempt < max_retries - 1:
                        print(f"[EXECUTOR_BROWSER] Browser was closed, restarting... (attempt {attempt + 1})")
                        _executor_browser_alive.clear()  # 再起動をトリガー
                        break  # 内側ループを抜けてリトライ
                    else:
                        raise RuntimeError(f"Browser was closed and failed to recover: {result}")
                return result
            except queue.Empty:
                elapsed += wait_timeout
                continue

        # ここに来たらタイムアウト（browser_closedでbreakした場合は除く）
        if elapsed >= total_timeout:
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

    async def wait_for_load_state(self, state: str = "domcontentloaded", timeout: int = None):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("wait_for_load_state", state=state, timeout=timeout)
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

    async def screenshot_base64(self, full_page: bool = False) -> dict:
        """スクリーンショットをbase64で取得（Vision API用）"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("screenshot_base64", full_page=full_page)
        )
        return result  # {"base64": "...", "media_type": "image/png"}

    async def content(self) -> str:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("content")
        )
        return result.get("content", "")

    async def evaluate(self, expression: str, arg=None):
        """JavaScriptを実行"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("evaluate", expression=expression, arg=arg)
        )
        return result.get("result")

    async def save_image(self, url: str, path: str):
        """URLから画像をダウンロードしてファイルに保存"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("save_image", url=url, path=path)
        )

    async def wait_for_selector(self, selector: str, timeout: int = 30000, state: str = "visible"):
        """セレクタが表示されるまで待機"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("wait_for_selector", selector=selector, timeout=timeout, state=state)
        )
        return ExecutorLocatorProxy(selector) if result.get("found") else None

    async def query_selector(self, selector: str):
        """セレクタで要素を取得"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("query_selector", selector=selector)
        )
        return ExecutorLocatorProxy(selector) if result.get("found") else None

    async def query_selector_all(self, selector: str):
        """セレクタで全要素を取得"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("query_selector_all", selector=selector)
        )
        count = result.get("count", 0)
        return [ExecutorLocatorProxy(selector, i) for i in range(count)]

    async def go_back(self):
        """ブラウザの戻るボタン"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("go_back")
        )
        return result

    async def inner_text(self, selector: str) -> str:
        """要素のテキストを取得"""
        result = await self.evaluate(f'document.querySelector("{selector}")?.innerText || ""')
        return result or ""

    async def go_forward(self):
        """ブラウザの進むボタン"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("go_forward")
        )
        return result

    async def reload(self):
        """ページを再読み込み"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("reload")
        )
        return result

    @property
    def keyboard(self):
        return ExecutorKeyboardProxy()

    @property
    def mouse(self):
        return ExecutorMouseProxy()

    # ========================================
    # タブ管理
    # ========================================

    async def switch_to_latest_tab(self) -> dict:
        """
        最新のタブ（新しく開いたタブ）に切り替え

        Returns:
            {"switched": bool, "url": str, "tab_count": int}
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("switch_to_latest_tab")
        )

    async def get_tab_count(self) -> dict:
        """
        開いているタブ数を取得

        Returns:
            {"count": int, "current_url": str}
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("get_tab_count")
        )

    async def close_current_tab(self) -> dict:
        """
        現在のタブを閉じて前のタブに切り替え

        Returns:
            {"closed": bool, "url": str}
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("close_current_tab")
        )

    # ========================================
    # ダン視覚機能（Vision for Dan）
    # ========================================

    async def get_aria_snapshot(self) -> dict:
        """
        ページのアクセシビリティスナップショットを取得

        Returns:
            dict: Playwrightのアクセシビリティツリー
        """
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("aria_snapshot")
        )
        return result.get("snapshot", {})

    async def get_interactive_elements(self) -> list:
        """
        インタラクティブ要素のリストを取得（data-dan-ref属性付き）

        各要素には @e1, @e2 のような参照IDが振られる。
        click_by_ref(), fill_by_ref() でこの参照を使って操作可能。

        Returns:
            list: [{"ref": "@e1", "tag": "button", "role": "button", "text": "カートに入れる", ...}, ...]
        """
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("get_interactive_elements")
        )
        return result.get("elements", [])

    async def click_by_ref(self, ref: str, force: bool = False, timeout: int = 30000):
        """
        data-dan-ref属性でクリック

        Args:
            ref: 参照ID（@e1 形式）
            force: 強制クリック
            timeout: タイムアウト（ミリ秒）
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("click_by_ref", ref=ref, force=force, timeout=timeout)
        )

    async def fill_by_ref(self, ref: str, value: str):
        """
        data-dan-ref属性で入力

        Args:
            ref: 参照ID（@e1 形式）
            value: 入力値
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("fill_by_ref", ref=ref, value=value)
        )

    async def get_page_summary(self) -> dict:
        """
        ページの要約情報を取得

        Returns:
            dict: {"title": "...", "url": "...", "main_text": "..."}
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("get_page_summary")
        )

    async def get_page_context(self) -> dict:
        """
        ページ状態の汎用スナップショット（OpenClaw方式）

        見出し、フィードバックメッセージ、モーダル、ローディング状態、
        バッジ、入力済みフォーム値を収集する。

        Returns:
            dict: {headings, feedback, modal, isLoading, badges, filledInputs}
        """
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _send_executor_command("get_page_context")
        )
        return result.get("context", {})

    async def get_page_state(self) -> dict:
        """
        ダンがページ状態を理解するための包括的な情報を取得

        Returns:
            dict: {
                "summary": {"title": "...", "url": "...", "main_text": "..."},
                "interactive_elements": [...],
                "element_count": N
            }
        """
        summary = await self.get_page_summary()
        elements = await self.get_interactive_elements()

        return {
            "summary": summary,
            "interactive_elements": elements[:50],  # 最大50要素
            "element_count": len(elements),
        }


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

    async def type(self, text: str, delay: int = 50):
        """テキストを入力（一括）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("keyboard_type", text=text, delay=delay)
        )


class ExecutorMouseProxy:
    """Mouse Proxy for coordinate-based clicks"""

    async def click(self, x: float, y: float):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("mouse_click", x=x, y=y)
        )

    async def move(self, x: float, y: float):
        """マウスを指定座標に移動（ホバー用）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _send_executor_command("mouse_move", x=x, y=y)
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


def abort_executor_session():
    """
    実行中のブラウザセッションを中断

    - コマンドキューをクリアして待機中のコマンドを破棄
    - 結果キューもクリア
    - ブラウザ自体は閉じない（次回再利用可能）

    重要: 進行中のPlaywrightコマンドは完了まで待つ必要がある。
    ただし、_send_executor_command内のキャンセルチェックにより、
    次のコマンドは実行されない。
    """
    global _executor_command_queue, _executor_result_queue

    cleared_commands = 0
    cleared_results = 0

    # コマンドキューをクリア
    while not _executor_command_queue.empty():
        try:
            _executor_command_queue.get_nowait()
            cleared_commands += 1
        except queue.Empty:
            break

    # 結果キューもクリア
    while not _executor_result_queue.empty():
        try:
            _executor_result_queue.get_nowait()
            cleared_results += 1
        except queue.Empty:
            break

    logger.info("[EXECUTOR_BROWSER] Session aborted - cleared %d commands, %d results", cleared_commands, cleared_results)
