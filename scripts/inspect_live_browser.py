"""Read-only inspection of the live dedicated browser (CDP 9223).

Attaches to the already-running Chrome that Dan left open, prints the current
URL/title, dumps body text + screenshot, and classifies any captcha present.
Does NOT click/submit/navigate. Safe to run while Dan is stopped.
"""
import asyncio
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.async_api import async_playwright
from app.tools.captcha_solver import detect_captchas

OUT = Path(__file__).resolve().parent.parent / ".tmp"
OUT.mkdir(exist_ok=True)
CDP = "http://127.0.0.1:9223"


async def main():
    try:
        socket.create_connection(("127.0.0.1", 9223), timeout=1).close()
    except OSError:
        print("CDP 9223 NOT available — dedicated browser is not running.")
        return
    async with async_playwright() as p:
        b = await p.chromium.connect_over_cdp(CDP)
        pages = []
        for c in b.contexts:
            pages += c.pages
        print("open pages:")
        for pg in pages:
            print("  -", pg.url)
        target = next((pg for pg in pages if "line" in pg.url.lower()), None) or (pages[0] if pages else None)
        if not target:
            print("no pages open")
            await b.close()
            return
        print("\n=== ACTIVE PAGE ===")
        print("URL  :", target.url)
        print("TITLE:", await target.title())
        try:
            txt = await target.inner_text("body")
        except Exception as e:
            txt = f"(inner_text failed: {e})"
        (OUT / "line_live_text.txt").write_text(txt, encoding="utf-8")
        print("body text -> .tmp/line_live_text.txt (chars:", len(txt), ")")
        try:
            await target.screenshot(path=str(OUT / "line_live.png"), full_page=False)
            print("screenshot -> .tmp/line_live.png")
        except Exception as e:
            print("screenshot failed:", e)
        try:
            det = await detect_captchas(target)
            print("captchas on page:", [(d.type, d.sitekey[:12]) for d in det])
        except Exception as e:
            print("detect failed:", e)
        # quick signal scan in body text
        low = txt.lower()
        signals = {
            "再captcha/画像認証": any(s in txt for s in ["画像", "文字", "認証コード"]) or "captcha" in low,
            "2段階/デバイス/本人確認": any(s in txt for s in ["本人確認", "認証番号", "デバイス", "2段階", "コードを入力", "通知"]),
            "ロック/試行超過": any(s in txt for s in ["ロック", "試行", "しばらく", "制限", "ブロック"]) or "locked" in low or "too many" in low,
            "ログイン失敗文言": any(s in txt for s in ["誤り", "正しくありません", "失敗"]),
        }
        print("text signals:", signals)
        await b.close()  # detaches CDP only; Chrome keeps running


asyncio.run(main())
