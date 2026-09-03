import asyncio, os
from PIL import Image
from playwright.async_api import async_playwright

OUT = "scripts/_paina_hero"
os.makedirs(OUT, exist_ok=True)
URL = "http://localhost:3000/preview/salonboard-styleup"
VW, VH = 440, 900

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context(viewport={"width":VW,"height":VH}, device_scale_factor=2)
        page = await ctx.new_page()
        await page.goto(URL, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(1500)
        # --- setup screen ---
        await page.wait_for_selector("text=最初の設定", timeout=15000)
        await page.screenshot(path=f"{OUT}/su_setup.png")
        # fill setup
        await page.fill('input[placeholder*="お名前"]', "デモ 美咲")
        await page.fill('input[placeholder*="ログインID"]', "demo_user")
        await page.fill('input[type="password"]', "demo-pass-123")
        cb = page.locator('input[type="checkbox"]').first
        if not await cb.is_checked():
            await cb.click()
        await page.get_by_role("button", name="保存して始める").click()
        # --- intro: pick sample ---
        await page.wait_for_selector("text=ベージュのボブ", timeout=15000)
        await page.get_by_role("button", name="ベージュのボブ").click()
        # --- wait for form to finish AI fill ---
        await page.wait_for_selector("text=スタイル登録", timeout=60000)
        for _ in range(60):
            await page.wait_for_timeout(1000)
            body = await page.inner_text("body")
            if "AIが入力中" not in body and "AIが解析中" not in body and "AIが写真を見て" not in body:
                break
        await page.wait_for_timeout(800)
        await page.evaluate("window.scrollTo(0,0)")
        await page.wait_for_timeout(300)
        await page.screenshot(path=f"{OUT}/su_form.png")
        await ctx.close()
        await b.close()
    print("setup", os.path.getsize(f"{OUT}/su_setup.png"), "form", os.path.getsize(f"{OUT}/su_form.png"))

asyncio.run(main())
