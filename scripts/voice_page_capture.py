"""音声エージェント(チャット統合)の「目」— 成果物ページの撮影・状態取得・可読性検査。

scratch実験ページで実証した機構(fullpage.py / canvas色解析つきcheck_contrast)の本番移植。
サンドボックスの /api/v1/voicelog/capture から subprocess で呼ばれる。

modes:
  tiles    — 全域を高解像度タイル(幅1024, 各≤110KB)で撮影  → {"tiles": [絶対パス,...]}
  section  — data-edit-id 要素を原寸撮影                    → {"image": 絶対パス}
  state    — 編集可能要素の一覧(テキスト/スタイル)          → {"state": [...]}
  contrast — 全テキスト要素のWCAGコントラスト機械検査       → {"contrast": {...}}

usage: python voice_page_capture.py --slug voice-playground --mode tiles \
         [--token JWT] [--element-id te-h1] [--out-dir D:/done/logs/realtime-voice/shots]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FORCE_FINAL_CSS = (
    "*{opacity:1 !important; transform:none !important; "
    "animation:none !important; transition:none !important;}"
)

STATE_JS = """() => {
  const els = Array.from(document.querySelectorAll('[data-edit-id]')).slice(0, 100);
  return els.map((el) => ({
    id: el.getAttribute('data-edit-id'),
    tag: el.tagName.toLowerCase(),
    text: (el.textContent || '').trim().slice(0, 80),
    style: (el.getAttribute('style') || '').slice(0, 120),
  }));
}"""

# canvas 1px 塗り読み方式: lab()/oklch() などトークン由来の色形式も解析できる
# (rgb専用正規表現は黙って要素を捨て「0件」と嘘をつく — 2026-08-22 実証)
CONTRAST_JS = """() => {
  const canvas = document.createElement('canvas'); canvas.width = 1; canvas.height = 1;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const toRgb = (s) => { if (!s || !ctx) return null; ctx.clearRect(0,0,1,1); ctx.fillStyle = s; ctx.fillRect(0,0,1,1); const d = ctx.getImageData(0,0,1,1).data; return [d[0], d[1], d[2], d[3]/255]; };
  const lum = (c) => { const f = (v) => { const x = v/255; return x <= 0.03928 ? x/12.92 : Math.pow((x+0.055)/1.055, 2.4); }; return 0.2126*f(c[0]) + 0.7152*f(c[1]) + 0.0722*f(c[2]); };
  let checked = 0, skippedImg = 0; const fails = [];
  for (const el of Array.from(document.body.querySelectorAll('*'))) {
    const hasText = Array.from(el.childNodes).some((n) => n.nodeType === 3 && (n.textContent || '').trim());
    if (!hasText) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const fg = toRgb(cs.color); if (!fg) continue;
    let bg = null, hasImage = false, cur = el;
    while (cur && cur !== document.documentElement) {
      const ccs = getComputedStyle(cur);
      if (ccs.backgroundImage && ccs.backgroundImage !== 'none') { hasImage = true; break; }
      const b = toRgb(ccs.backgroundColor);
      if (b && b[3] > 0.01) { bg = b; break; }
      cur = cur.parentElement;
    }
    if (hasImage) { skippedImg += 1; continue; }
    if (!bg) bg = [255, 255, 255, 1];
    checked += 1;
    const ratio = (Math.max(lum(fg), lum(bg)) + 0.05) / (Math.min(lum(fg), lum(bg)) + 0.05);
    const fs = parseFloat(cs.fontSize) || 16;
    const threshold = fs >= 24 ? 3 : 4.5;
    if (ratio < threshold) {
      fails.push({
        id: el.dataset.editId || null,
        where: el.dataset.editId ? undefined : `${el.tagName.toLowerCase()}「${(el.textContent||'').trim().slice(0,20)}」`,
        ratio: Math.round(ratio * 10) / 10,
        required: threshold,
        text: (el.textContent || '').trim().slice(0, 40),
      });
    }
  }
  return { checked, skipped_image_background: skippedImg, failures: fails.slice(0, 30) };
}"""


def _shrink_to_fit(path: str, max_bytes: int) -> None:
    if os.path.getsize(path) <= max_bytes:
        return
    from PIL import Image

    img = Image.open(path).convert("RGB")
    for width, quality in [(800, 60), (720, 50), (640, 45), (560, 40), (480, 35)]:
        resized = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS) if img.width > width else img
        resized.save(path, "JPEG", quality=quality, optimize=True)
        if os.path.getsize(path) <= max_bytes:
            return


def _slice_tiles(path: str, max_tiles: int) -> list[str]:
    from PIL import Image

    img = Image.open(path).convert("RGB")
    width = 1024
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    tile_h = 1100
    n = min(max_tiles, max(1, -(-img.height // tile_h)))
    tile_h = -(-img.height // n)
    outs = []
    for i in range(n):
        top = i * tile_h
        tile = img.crop((0, top, img.width, min(top + tile_h, img.height)))
        out = f"{path}.tile{i + 1:02d}.jpg"
        for q in (75, 60, 50, 40):
            tile.save(out, "JPEG", quality=q, optimize=True)
            if os.path.getsize(out) <= 110_000:
                break
        outs.append(out)
    return outs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--mode", required=True, choices=["tiles", "section", "state", "contrast"])
    ap.add_argument("--token", default="")
    ap.add_argument("--element-id", default="")
    ap.add_argument("--out-dir", default=str(Path("D:/done/logs/realtime-voice/shots")))
    args = ap.parse_args()

    url = f"http://localhost:3000/artifacts/{args.slug}?dan_preview=1"
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        if args.token:
            context.add_cookies(
                [{"name": "done_access_token", "value": args.token, "url": "http://localhost:3000"}]
            )
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=25000)
        page.wait_for_timeout(1500)  # InspectorRuntime の draft 適用待ち

        if args.mode == "state":
            print(json.dumps({"state": page.evaluate(STATE_JS)}, ensure_ascii=False))
        elif args.mode == "contrast":
            print(json.dumps({"contrast": page.evaluate(CONTRAST_JS)}, ensure_ascii=False))
        elif args.mode == "section":
            if not args.element_id:
                print(json.dumps({"error": "element-id が必要です"}))
                return
            el = page.locator(f'[data-edit-id="{args.element_id}"]').first
            el.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            out = str(out_dir / f"chat-{args.slug}-{int(time.time())}-section.jpg")
            el.screenshot(path=out, type="jpeg", quality=85)
            _shrink_to_fit(out, 110_000)
            print(json.dumps({"image": out}))
        else:  # tiles
            page.add_style_tag(content=FORCE_FINAL_CSS)
            page.wait_for_timeout(400)
            out = str(out_dir / f"chat-{args.slug}-{int(time.time())}.jpg")
            page.screenshot(path=out, full_page=True, type="jpeg", quality=80)
            tiles = _slice_tiles(out, 8)
            print(json.dumps({"tiles": tiles}))
        browser.close()


if __name__ == "__main__":
    main()
