"""サイトが開いた小窓へ操作対象が移り、閉じたら元へ戻ること（2026-09-28 AdSense 本人確認）。"""
import asyncio
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.tools.browser import _execute_page_command

PAGES = {
    "/start": b"""<button id=b onclick="setTimeout(()=>window.open('/v3/signin/challenge/pwd','p','width=400,height=500'),800)">go</button>""",
    "/v3/signin/challenge/pwd": b"<input type=password><button id=c onclick='window.close()'>next</button>",
}


class _Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        body = PAGES.get(self.path.split("?")[0], b"")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_follows_delayed_popup_and_returns_when_it_closes(server):
    from playwright.async_api import async_playwright

    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            state = {"current": page, "all_pages": [page], "unchecked": [], "openers": {}, "notice": None}

            def on_new_page(p):
                state["all_pages"].append(p)
                state["unchecked"].append(p)

            context.on("page", on_new_page)
            await page.goto(server + "/start")

            # A tab nobody on the page opened (the user's or Dan's own) is not a popup and is not followed.
            await context.new_page()
            info = await _execute_page_command(state, context, "window_info", {})
            assert info["url"].endswith("/start") and not info["popup"] and info["notice"] is None

            # A popup opened late by script (not a target=_blank link) becomes the target.
            box = await page.locator("#b").bounding_box()
            await page.mouse.click(box["x"] + 5, box["y"] + 5)
            await page.wait_for_timeout(1500)
            info = await _execute_page_command(state, context, "window_info", {})
            assert "/signin/" in info["url"] and info["popup"] and "小窓" in info["notice"]
            assert (await _execute_page_command(state, context, "window_info", {}))["notice"] is None

            # The popup closes itself after sign-in; the next command is back on the opener, not "browser closed".
            await state["current"].click("#c")
            await page.wait_for_timeout(300)
            info = await _execute_page_command(state, context, "window_info", {})
            assert info["url"].endswith("/start") and not info["popup"] and "戻しました" in info["notice"]
            assert state["current"] is page
            await browser.close()

    asyncio.run(run())
