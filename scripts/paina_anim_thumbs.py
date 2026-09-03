import asyncio
from PIL import Image
from playwright.async_api import async_playwright

SITES = [
    ("kittoku", "https://kittoku.vercel.app/v2", 1200, 2600),
    ("gojo",    "https://yonago-gojo-done.vercel.app",                1200, 2600),
    ("denki",   "http://localhost:3000/preview/denki-knowledge",      1200, 2400),
]

async def capture_tall(ctx, name, url, width, cap):
    pg = await ctx.new_page()
    await pg.set_viewport_size({"width": width, "height": 900})
    try:
        await pg.goto(url, wait_until="networkidle", timeout=50000)
    except Exception as e:
        print("warn goto", name, e); await pg.wait_for_timeout(3000)
    await pg.wait_for_timeout(2500)
    # lazy load: scroll through
    h = await pg.evaluate("document.body.scrollHeight")
    y = 0
    while y < min(h, cap):
        await pg.evaluate(f"window.scrollTo(0,{y})"); await pg.wait_for_timeout(350); y += 700
    await pg.evaluate("window.scrollTo(0,0); document.querySelectorAll('[data-reveal]').forEach(e=>{e.style.opacity=1;e.style.transform='none'})")
    await pg.wait_for_timeout(700)
    H = min(await pg.evaluate("document.body.scrollHeight"), cap)
    await pg.screenshot(path=f"frontend/public/paina/case-{name}.png", clip={"x":0,"y":0,"width":width,"height":H})
    # to jpg for size
    im = Image.open(f"frontend/public/paina/case-{name}.png").convert("RGB")
    im.save(f"frontend/public/paina/case-{name}.jpg", quality=84)
    import os; os.remove(f"frontend/public/paina/case-{name}.png")
    print("tall", name, im.size)
    await pg.close()

async def capture_styleup(ctx):
    pg = await ctx.new_page()
    await pg.set_viewport_size({"width": 460, "height": 900})
    await pg.goto("http://localhost:3000/preview/salonboard-styleup", wait_until="networkidle", timeout=50000)
    await pg.wait_for_timeout(2000)
    shots = []
    for label, fname in [("初期設定","su1"),("投稿フォーム","su2")]:
        try:
            await pg.click(f"button:has-text('{label}')", timeout=8000)
        except Exception as e:
            print("warn click", label, e)
        await pg.wait_for_timeout(1500)
        await pg.evaluate("var b=document.querySelector('[data-dan-preview-ui]'); if(b)b.style.display='none'")
        await pg.wait_for_timeout(300)
        await pg.screenshot(path=f"frontend/public/paina/{fname}.png", full_page=True)
        await pg.evaluate("var b=document.querySelector('[data-dan-preview-ui]'); if(b)b.style.display=''")
        shots.append(f"frontend/public/paina/{fname}.png")
        print("shot", label)
    # 縦結合
    ims = [Image.open(s).convert("RGB") for s in shots]
    W = min(i.width for i in ims)
    ims = [i.resize((W, int(i.height*W/i.width))) for i in ims]
    gap = 0
    total_h = sum(i.height for i in ims) + gap*(len(ims)-1)
    canvas = Image.new("RGB",(W,total_h),(244,245,247))
    y=0
    for i in ims:
        canvas.paste(i,(0,y)); y += i.height + gap
    canvas.save("frontend/public/paina/case-styleup.jpg", quality=85)
    import os
    for s in shots: os.remove(s)
    print("styleup composite", canvas.size)
    await pg.close()

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context(device_scale_factor=1)
        for name,url,w,cap in SITES:
            await capture_tall(ctx, name, url, w, cap)
        await capture_styleup(ctx)
        await b.close()

asyncio.run(main())
