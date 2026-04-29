"""dan-notionのフォルダグリッドビューでファイルホバー時に全文ツールチップが出ることを確認"""
from pathlib import Path
from playwright.sync_api import sync_playwright
import requests

PROFILE = str(Path(r"D:\done\.playwright-hover-tooltip").absolute())
OUT = Path(r"D:\done\.playwright-dan-notion")

FRONTEND = "http://localhost:3000"
BACKEND = "http://localhost:8000"

def main():
    tok = requests.post(f"{BACKEND}/api/v1/chat/login",
        json={"email":"dan-test@example.com","password":"DanTest2026x"}).json()["access_token"]
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE, headless=False,
            viewport={"width": 1400, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"{FRONTEND}/", wait_until="domcontentloaded")
        page.evaluate(f"localStorage.setItem('done-token','{tok}')")
        page.goto(f"{FRONTEND}/dan-notion", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        page.wait_for_timeout(3000)
        page.screenshot(path=str(OUT / "hover-01-home.png"))

        # ホバーテスト folder をクリック
        try:
            page.get_by_text("ホバーテスト", exact=False).first.click(timeout=5000)
            page.wait_for_timeout(1500)
        except Exception as e:
            print("[warn]", e)
        page.screenshot(path=str(OUT / "hover-02-folder.png"))

        # カードを探してホバー
        cards = page.locator("div.group.relative.rounded-lg")
        n = cards.count()
        print(f"cards: {n}")
        if n > 0:
            cards.first.hover()
            page.wait_for_timeout(800)
            page.screenshot(path=str(OUT / "hover-04-tooltip.png"))
            tip = cards.first.locator("div.pointer-events-none.absolute").first
            op = tip.evaluate("el => getComputedStyle(el).opacity")
            txt = tip.inner_text()
            print(f"opacity={op} text='{txt}'")

        ctx.close()

main()
