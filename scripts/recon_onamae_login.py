"""お名前.com ログイン画面のDOM調査（③代理ログイン自動化のセレクタ焼き込み前調査）。

CLAUDE.md の規律: セレクタを焼き込むスキルは実装前に実サイトを調査する。
本スクリプトはログイン画面の input/button/form を列挙し、スクショを保存するだけ。
口座不要・公開ページのみ。
"""
from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

LOGIN_URLS = [
    "https://navi.onamae.com/login",
    "https://www.onamae.com/navi/login/",
]
OUT_SHOT = "D:/done/.gojo_chunks/onamae_login.png"


def dump(page) -> dict:
    info = {"url": page.url, "title": page.title()}
    info["inputs"] = page.eval_on_selector_all(
        "input",
        "els => els.map(e => ({name:e.name, id:e.id, type:e.type, placeholder:e.placeholder, autocomplete:e.autocomplete, visible:!!(e.offsetWidth||e.offsetHeight)}))",
    )
    info["buttons"] = page.eval_on_selector_all(
        "button, input[type=submit], a[role=button]",
        "els => els.map(e => ({tag:e.tagName, id:e.id, name:e.name, type:e.type, text:(e.innerText||e.value||'').trim().slice(0,40)})).filter(b=>b.text||b.id||b.name)",
    )
    info["forms"] = page.eval_on_selector_all(
        "form", "els => els.map(e => ({id:e.id, name:e.name, action:e.action, method:e.method}))"
    )
    return info


def main() -> int:
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
        )
        page = ctx.new_page()
        for url in LOGIN_URLS:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(2500)
                info = dump(page)
                info["requested"] = url
                results.append(info)
                if url == LOGIN_URLS[0]:
                    try:
                        page.screenshot(path=OUT_SHOT, full_page=True)
                        info["screenshot"] = OUT_SHOT
                    except Exception as e:  # noqa: BLE001
                        info["screenshot_error"] = str(e)
            except Exception as e:  # noqa: BLE001
                results.append({"requested": url, "error": repr(e)})
        browser.close()
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
