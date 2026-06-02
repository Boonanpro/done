"""End-to-end test of captcha_solver against a real form (NO final submit).

Proves: detect -> 2captcha solve -> inject -> submit button enabled.
Usage: python scripts/captcha_solve_test.py <url>
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.async_api import async_playwright

from app.tools.captcha_solver import solve_page_captchas, get_balance

OUT = Path(__file__).resolve().parent.parent / ".tmp"
OUT.mkdir(exist_ok=True)
URL = sys.argv[1] if len(sys.argv) > 1 else "https://toaru-d.com/inquiry"


async def main():
    bal = await get_balance()
    print("2captcha balance before:", bal)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 1200}, locale="ja-JP",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"))
        page = await ctx.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(5000)

        print("solving captchas (this can take 15-90s)...")
        summary = await solve_page_captchas(page)
        print("SUMMARY:")
        for s in summary["solved"]:
            print(f"  {s['type']}: injected {s['injected_fields']} field(s)")
        print("tokens:", {k: (v[:18] + '...' + str(len(v))) for k, v in summary["tokens"].items()})

        # verify response fields actually hold the token + submit enabled
        state = await page.evaluate(r"""() => {
          const g = document.querySelector('textarea[id^=g-recaptcha-response],textarea[name=g-recaptcha-response]');
          const t = document.querySelector('input[name=cf-turnstile-response]');
          const submits = [...document.querySelectorAll('form button, form input[type=submit]')]
            .map(b => ({txt:(b.innerText||b.value||'').trim(), disabled:b.disabled}));
          return {
            recaptcha_field_len: g ? (g.value||'').length : null,
            turnstile_field_len: t ? (t.value||'').length : null,
            submits,
          };
        }""")
        print("FIELD/SUBMIT STATE:", state)
        await page.screenshot(path=str(OUT / "captcha_solve_test.png"), full_page=True)
        print("screenshot saved. NOT submitting (no message content yet).")
        await ctx.close(); await browser.close()
    bal2 = await get_balance()
    print("2captcha balance after:", bal2)


asyncio.run(main())
