"""お名前.com の最安TLDと初年度価格を調べる（検索のみ・カートに入れない）。

ランダムな空きドメイン名で検索し、表示される TLD/価格グリッドを読み取る。
申込/カートボタンは一切押さない（カート汚染防止）。
"""
from __future__ import annotations

import json

from playwright.sync_api import sync_playwright

# 実在しなさそうなテスト文字列（購入はしない・空き確認の価格表示のため）
QUERY = "dantest9z3k20260612"
SEARCH_URL = f"https://www.onamae.com/search/result/?searchWord={QUERY}"


def main() -> int:
    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="ja-JP")
        page = ctx.new_page()
        try:
            page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=40000)
            page.wait_for_timeout(6000)  # 価格テーブルは遅延描画
            # TLD と価格らしきテキストを総当りで拾う
            rows = page.eval_on_selector_all(
                "li, tr, [class*='price'], [class*='domain']",
                """els => els.map(e => (e.innerText||'').replace(/\\s+/g,' ').trim())
                       .filter(t => /\\.[a-z]{2,}/i.test(t) && /(円|\\u00a5|\\d)/.test(t))
                       .slice(0,120)""",
            )
        except Exception as e:  # noqa: BLE001
            rows = [f"ERROR: {e!r}"]
        finally:
            browser.close()
    # 重複除去しつつ '円' を含む短い行を優先表示
    seen = set()
    picked = []
    for r in rows:
        if r in seen:
            continue
        seen.add(r)
        if "円" in r and len(r) < 80:
            picked.append(r)
    print(json.dumps(picked[:60], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
