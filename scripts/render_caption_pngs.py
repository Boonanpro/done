"""Render designed captions to transparent PNGs by screenshotting the Next.js /caption-frame
route. Called by the export pipeline (app/api/production_asset_routes.py) as a subprocess so
Playwright runs fully isolated from the render thread / asyncio loop.

Usage:  python scripts/render_caption_pngs.py <spec.json>

spec.json = {
  "outW": 1080, "outH": 1920,
  "web_base": "http://127.0.0.1:3000",
  "items": [ {"png": "C:/abs/path/cap0.png", "text": "...", "time": 0.0, "design": {...}}, ... ]
}

Each item is screenshotted with a transparent background at outW x outH. Because the route
renders the SAME <CaptionLayer> as the live editor preview, the PNG matches the timeline.
Prints one line per item: "OK <png>" or "FAIL <png> <error>". Exit 0 if all succeeded.
"""
import base64
import json
import sys
from pathlib import Path


def payload_url(web_base: str, out_w: int, out_h: int, item: dict) -> str:
    payload = {
        "outW": out_w,
        "outH": out_h,
        "time": float(item.get("time") or 0.0),
        "captions": [{
            "text": str(item.get("text") or ""),
            "start": 0.0,
            "end": 1e9,
            "design": item.get("design") or {},
        }],
    }
    # URL-SAFE base64: a '+' in a normal base64 query value is decoded as a space by the browser's
    # URLSearchParams, corrupting any payload (e.g. kanji) whose base64 contains '+' or '/'.
    raw = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return f"{web_base.rstrip('/')}/caption-frame?p={raw}"


def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out_w = int(spec["outW"])
    out_h = int(spec["outH"])
    web_base = str(spec.get("web_base") or "http://127.0.0.1:3000")
    items = spec.get("items") or []

    from playwright.sync_api import sync_playwright

    failures = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, channel="chrome")
        page = browser.new_page(viewport={"width": out_w, "height": out_h}, device_scale_factor=1)
        for item in items:
            png = item["png"]
            try:
                page.goto(payload_url(web_base, out_w, out_h, item), wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_selector("body[data-caption-ready='1']", timeout=9000)
                except Exception:
                    pass  # render anyway; fonts use font-display:block so glyphs are present
                page.wait_for_timeout(120)
                Path(png).parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=png, omit_background=True,
                                clip={"x": 0, "y": 0, "width": out_w, "height": out_h})
                print(f"OK {png}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL {png} {exc}")
        browser.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
