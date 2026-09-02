"""チャレンジ表示中の canvas を原寸で取り出し、描画命令の記録も回収する。

読み取り専用。パズルには一切触らない。
inspect_hcaptcha_dom.py が仕掛けた drawImage フックの記録（window.__hcapDraws）が
あれば併せて保存する。
"""
import asyncio
import base64
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.async_api import async_playwright

ROOM_PROFILE = Path.home() / ".ai_secretary" / "browser_data--38461f5a-6ded-464a-adb9-92a7de46b288-96152237"
OUT = Path(__file__).resolve().parent.parent / ".tmp" / "hcap"
OUT.mkdir(parents=True, exist_ok=True)

JS = r"""
() => {
  const out = {href: location.href};
  const c = document.querySelector('canvas');
  if (c) {
    const r = c.getBoundingClientRect();
    out.canvas = {w: c.width, h: c.height, css: [r.x, r.y, r.width, r.height]};
    try { out.dataUrl = c.toDataURL('image/png'); out.canvas.readable = true; }
    catch (e) { out.canvas.readable = false; out.canvas.err = String(e).slice(0, 100); }
  }
  if (window.__hcapDraws) out.draws = window.__hcapDraws;
  const std = new Set(Object.getOwnPropertyNames(Object.getPrototypeOf(window)));
  out.globals = Object.keys(window).filter(k => !std.has(k)).slice(0, 200);
  // 画面上の <img> （タイル素材が img として読まれていないか）
  out.imgs = [...document.querySelectorAll('img')].map(im => ({
    src: (im.currentSrc || im.src || '').slice(0, 160),
    w: im.naturalWidth, h: im.naturalHeight
  })).slice(0, 40);
  return out;
}
"""


async def main():
    port = int((ROOM_PROFILE / "dan_cdp_port.txt").read_text(encoding="utf-8").strip())
    stamp = int(time.time())
    async with async_playwright() as p:
        b = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        pages = [pg for c in b.contexts for pg in c.pages]
        page = next((pg for pg in pages if "epicgames" in pg.url), pages[0])
        for i, fr in enumerate(page.frames):
            try:
                d = await fr.evaluate(JS)
            except Exception as exc:
                print(f"frame{i}: eval failed {str(exc)[:80]}")
                continue
            href = d.get("href", "")
            has_canvas = "canvas" in d
            draws = d.get("draws") or []
            print(f"--- frame{i} {href[:80]!r} canvas={has_canvas} draws={len(draws)}")
            if has_canvas:
                cv = d["canvas"]
                print(f"    canvas {cv['w']}x{cv['h']} css={[round(v) for v in cv['css']]} readable={cv.get('readable')} {cv.get('err','')}")
                if d.get("dataUrl"):
                    path = OUT / f"canvas_{stamp}_f{i}.png"
                    path.write_bytes(base64.b64decode(d["dataUrl"].split(",", 1)[1]))
                    print(f"    saved {path.name} ({path.stat().st_size} bytes)")
            if draws:
                path = OUT / f"draws_{stamp}_f{i}.json"
                path.write_text(json.dumps(draws, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"    saved {path.name}")
            if d.get("imgs"):
                print(f"    imgs: {d['imgs'][:6]}")
            if has_canvas and d.get("globals"):
                path = OUT / f"globals_{stamp}_f{i}.json"
                path.write_text(json.dumps(d["globals"], ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"    globals({len(d['globals'])}) -> {path.name}")
        await b.close()


asyncio.run(main())
