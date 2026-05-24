"""Deepgram と Cartesia の signup ページを訪問してフォーム構造を recon する。

screenshot とフォーム要素のダンプを `logs/voice_signup/` に保存し、本番 signup スクリプト
を書く前に何が必要か把握する。
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright

OUT_DIR = Path("logs/voice_signup")
OUT_DIR.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ("deepgram", "https://console.deepgram.com/signup"),
    ("cartesia", "https://play.cartesia.ai/sign-up"),
]


async def dump_form(page, label: str) -> str:
    """ページ上の input / button / link を全列挙して文字列で返す。"""
    out = [f"\n=== {label}  URL={page.url} ==="]
    out.append(f"title: {await page.title()}")

    out.append("\n--- INPUTS ---")
    for i, inp in enumerate(await page.locator("input").all()):
        try:
            t = await inp.get_attribute("type") or ""
            n = await inp.get_attribute("name") or ""
            ph = await inp.get_attribute("placeholder") or ""
            aria = await inp.get_attribute("aria-label") or ""
            out.append(f"  [{i}] type={t!r} name={n!r} placeholder={ph!r} aria={aria!r}")
        except Exception as e:
            out.append(f"  [{i}] (err: {e})")

    out.append("\n--- BUTTONS ---")
    for i, btn in enumerate(await page.locator("button").all()):
        try:
            txt = (await btn.inner_text()).strip()[:60]
            out.append(f"  [{i}] '{txt}'")
        except Exception:
            pass

    out.append("\n--- TEXT LINKS that might be OAuth ('Google','GitHub','SSO','Sign in with') ---")
    for sel in ["a", "button"]:
        for i, el in enumerate(await page.locator(sel).all()):
            try:
                txt = (await el.inner_text()).strip()
                if any(k in txt for k in ("Google", "GitHub", "SSO", "Microsoft", "Continue", "Sign in")):
                    out.append(f"  {sel}[{i}]: '{txt[:80]}'")
            except Exception:
                pass

    # Detect CAPTCHA-like iframes
    out.append("\n--- IFRAMES (capt etc.) ---")
    for fr in page.frames:
        url = (fr.url or "")[:100]
        if any(k in url for k in ("captcha", "turnstile", "hcaptcha", "recaptcha", "cloudflare")):
            out.append(f"  CAPTCHA-LIKE iframe: {url}")
        elif fr is not page.main_frame:
            out.append(f"  iframe: {url}")

    return "\n".join(out)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
        )
        for label, url in TARGETS:
            page = await ctx.new_page()
            try:
                print(f"[{label}] -> {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # 一部の SPA は少し待たないとフォームが出ない
                await page.wait_for_timeout(3500)
                shot = OUT_DIR / f"{label}_signup.png"
                await page.screenshot(path=str(shot), full_page=True)
                dump = await dump_form(page, label)
                (OUT_DIR / f"{label}_signup.txt").write_text(dump, encoding="utf-8")
                print(f"  screenshot -> {shot}")
                print(f"  form-dump -> {OUT_DIR / f'{label}_signup.txt'}")
                print(dump)
            except Exception as e:
                print(f"[{label}] ERROR: {e}")
            finally:
                await page.close()
        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
