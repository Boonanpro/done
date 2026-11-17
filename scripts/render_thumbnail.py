"""部品で持つサムネを PNG にする。エディターと同じ描き方（Next.js の /thumbnail-frame、<ThumbCanvas>）を
headless Chromium で開いて撮るので、書き出しは画面で見た物と同じになる。

使い方:  python scripts/render_thumbnail.py <spec.json>
spec = {"doc": {...}, "marks": [...], "outW": 1280, "out": "/abs/out.png", "web_base": "http://127.0.0.1:3000"}
成功したら "OK <out>" と出して 0 で終わる。
"""
import json
import os
import sys
from pathlib import Path


def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    doc = spec["doc"]
    out_w = int(spec.get("outW") or 1280)
    out_h = round(out_w * float(doc.get("height") or 1080) / float(doc.get("width") or 1920))
    web_base = str(spec.get("web_base") or os.environ.get("DAN_THUMB_RENDER_BASE") or "http://127.0.0.1:3000").rstrip("/")
    out = Path(spec["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, channel="chrome", args=["--mute-audio"])
        try:
            page = browser.new_page(viewport={"width": out_w, "height": out_h}, device_scale_factor=1)
            page.goto(f"{web_base}/thumbnail-frame", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_function("() => typeof window.__setThumbPayload === 'function'", timeout=60000)
            page.evaluate("(p) => window.__setThumbPayload(p)", {"doc": doc, "marks": spec.get("marks") or [], "outW": out_w})
            page.wait_for_selector('[data-thumb-ready="true"]', state="attached", timeout=45000)
            page.wait_for_timeout(150)
            page.screenshot(path=str(out), clip={"x": 0, "y": 0, "width": out_w, "height": out_h})
        finally:
            browser.close()
    print(f"OK {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
