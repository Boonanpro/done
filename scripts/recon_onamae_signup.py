"""お名前.com の口座作成(新規登録)の入口を調査する。

「ドメイン購入なしで無料の口座を作れるか」を判定するため、ログイン画面と
トップから '新規登録 / アカウント作成 / 会員登録' 系の導線を洗い出す。
"""
from __future__ import annotations

import json

from playwright.sync_api import sync_playwright

URLS = [
    "https://navi.onamae.com/login",
    "https://www.onamae.com/",
]
KEYWORDS = ["新規", "登録", "アカウント", "会員", "作成", "regist", "signup", "account", "申込"]


def grab_links(page):
    return page.eval_on_selector_all(
        "a, button",
        """els => els.map(e => ({
            tag: e.tagName,
            text: (e.innerText||e.value||'').trim().slice(0,40),
            href: e.getAttribute('href') || ''
        })).filter(x => x.text || x.href)""",
    )


def main() -> int:
    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="ja-JP")
        page = ctx.new_page()
        for url in URLS:
            entry = {"url": url, "matches": []}
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2500)
                for ln in grab_links(page):
                    blob = (ln["text"] + " " + ln["href"]).lower()
                    if any(k.lower() in blob for k in KEYWORDS):
                        entry["matches"].append(ln)
            except Exception as e:  # noqa: BLE001
                entry["error"] = repr(e)
            out.append(entry)
        browser.close()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
