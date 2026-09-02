import asyncio, os, glob
from playwright.async_api import async_playwright

OUT = "scripts/_paina_hero"
os.makedirs(OUT, exist_ok=True)
SITES = [
    ("kittoku", "https://kittoku.vercel.app/v2"),
    ("gojo",    "https://yonago-gojo-done.vercel.app"),
]

async def rec(name, url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--autoplay-policy=no-user-gesture-required"])
        ctx = await browser.new_context(
            viewport={"width":1280,"height":800},
            record_video_dir=OUT,
            record_video_size={"width":1280,"height":800},
        )
        page = await ctx.new_page()
        await page.goto(url, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(1500)
        # ensure at very top (hero)
        await page.evaluate("window.scrollTo(0,0)")
        await page.wait_for_timeout(8000)
        await ctx.close()
        await browser.close()
        # rename the produced webm
        vids = sorted(glob.glob(os.path.join(OUT,"*.webm")), key=os.path.getmtime)
        latest = vids[-1]
        dst = os.path.join(OUT, f"{name}.webm")
        if os.path.exists(dst): os.remove(dst)
        os.rename(latest, dst)
        print(name, "->", dst, os.path.getsize(dst))

async def main():
    for n,u in SITES:
        await rec(n,u)

asyncio.run(main())
