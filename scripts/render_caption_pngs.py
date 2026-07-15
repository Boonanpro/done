"""Render designed captions to transparent PNGs by screenshotting the Next.js /caption-frame
route. Called by the export pipeline (app/api/production_asset_routes.py) as a subprocess so
Playwright runs fully isolated from the render thread / asyncio loop.

Usage:  python scripts/render_caption_pngs.py <spec.json>

spec.json = {
  "outW": 1080, "outH": 1920,
  "web_base": "http://127.0.0.1:3000",
  "items": [
    # static caption -> single PNG
    {"png": "C:/abs/cap0.png", "text": "...", "time": 0.0, "design": {...}, "words": [...]},
    # animated caption -> PNG sequence 00000.png.. in seq_dir, sampled at fps over [start,end]
    {"seq_dir": "C:/abs/cap1_seq", "text": "...", "start": 1.0, "end": 3.5, "fps": 20,
     "design": {...}, "words": [...]}
  ]
}

Because the route renders the SAME <CaptionLayer> as the live editor preview, the PNGs match the
timeline. Prints one line per item: "OK ..." or "FAIL ...". Exit 0 if all succeeded.
"""
import base64
import json
import os
import sys
import time
from pathlib import Path

_DBG_PATH = os.environ.get("RENDER_CAPTION_DEBUG_LOG") or ""
_T0 = time.time()


def _dbg(msg: str) -> None:
    """Stage log for hang forensics (in-job bakes stalled at an unknown step for
    180s while the same spec finished in 2s from a shell). Enabled via env only."""
    if not _DBG_PATH:
        return
    try:
        with open(_DBG_PATH, "a", encoding="utf-8") as f:
            f.write(f"+{time.time() - _T0:7.2f}s {msg}\n")
    except OSError:
        pass


def payload_url(web_base: str, out_w: int, out_h: int, item: dict, time_val: float) -> str:
    payload = {
        "outW": out_w,
        "outH": out_h,
        "time": float(time_val),
        "captions": [{
            "text": str(item.get("text") or ""),
            "start": float(item.get("start") or 0.0),
            "end": float(item.get("end") or 1e9),
            "design": item.get("design") or {},
            "words": item.get("words") or [],
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
    clip = {"x": 0, "y": 0, "width": out_w, "height": out_h}

    _dbg("spec loaded; importing playwright")
    from playwright.sync_api import sync_playwright

    failures = 0
    _dbg("starting playwright driver")
    with sync_playwright() as pw:
        _dbg("driver up; launching chromium (channel=chrome)")
        browser = pw.chromium.launch(headless=True, channel="chrome")
        _dbg("browser up; opening page")
        page = browser.new_page(viewport={"width": out_w, "height": out_h}, device_scale_factor=1)
        _dbg("page open; rendering items")
        for item in items:
            try:
                if item.get("seq_dir"):
                    start = float(item.get("start") or 0.0)
                    end = max(start + 0.05, float(item.get("end") or start + 1.0))
                    fps = float(item.get("fps") or 20)
                    n = max(1, round((end - start) * fps))
                    seq = Path(item["seq_dir"])
                    seq.mkdir(parents=True, exist_ok=True)
                    page.goto(payload_url(web_base, out_w, out_h, item, start),
                              wait_until="domcontentloaded", timeout=30000)
                    try:
                        page.wait_for_selector("body[data-caption-ready='1']", timeout=9000)
                        page.wait_for_function("() => typeof window.__renderCaptionAt === 'function'", timeout=4000)
                    except Exception:
                        pass
                    for f in range(n):
                        t = start + (f + 0.5) / fps  # sample mid-frame
                        try:
                            page.evaluate("(t) => window.__renderCaptionAt(t)", t)
                        except Exception:
                            page.wait_for_timeout(16)
                        page.screenshot(path=str(seq / f"{f:05d}.png"), omit_background=True, clip=clip)
                    print(f"OK {seq} ({n} frames @ {fps}fps)")
                else:
                    png = item["png"]
                    page.goto(payload_url(web_base, out_w, out_h, item, float(item.get("time") or 0.0)),
                              wait_until="domcontentloaded", timeout=30000)
                    _dbg("goto done")
                    try:
                        page.wait_for_selector("body[data-caption-ready='1']", timeout=9000)
                    except Exception:
                        pass
                    page.wait_for_timeout(120)
                    _dbg("ready; screenshotting")
                    Path(png).parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=png, omit_background=True, clip=clip)
                    _dbg("screenshot done")
                    print(f"OK {png}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL {item.get('seq_dir') or item.get('png')} {exc}")
        browser.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
