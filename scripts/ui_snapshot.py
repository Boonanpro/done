# -*- coding: utf-8 -*-
"""ダンのUIを毎日スクショして物語の素材にする。

「どんなUIを試したか」は文章(commit/会話)には残るが見た目は残らない。
後から動画にする時に当時の画面を再現できるよう、その日のUIをそのまま保存する。

  python scripts/ui_snapshot.py            # pages.json の全ページを撮影
  python scripts/ui_snapshot.py --page /xx # 1ページだけ今すぐ撮影 (UI実験中に手動で)

出力: D:/dan-archive/story/shots/<YYYY-MM-DD>/<名前>.png
      (story/index.html から相対 "shots/..." で参照できる位置)
対象: D:/dan-archive/story/shots/pages.json (無ければ既定で作る。自由に追記してよい)
      [{"name":"chat","path":"/chat"}, ...]  path はダンのフロント(3000)のパス
毎日 21:00 にタスク DanUiSnapshot が実行 (run_hidden.vbs 経由)。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

JST = timezone(timedelta(hours=9))
SHOTS_DIR = Path(os.environ.get("DAN_ARCHIVE_ROOT") or "D:/dan-archive") / "story" / "shots"
PAGES_PATH = SHOTS_DIR / "pages.json"
BASE = os.environ.get("DAN_FRONT_URL", "http://127.0.0.1:3000")
OWNER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"
OWNER_EMAIL = "0aw325171@gmail.com"

DEFAULT_PAGES = [
    {"name": "chat", "path": "/chat"},
    {"name": "today", "path": "/today"},
]


def log(msg: str) -> None:
    print(f"[ui-shot] {datetime.now():%H:%M:%S} {msg}", flush=True)


def load_pages() -> list[dict]:
    if not PAGES_PATH.exists():
        SHOTS_DIR.mkdir(parents=True, exist_ok=True)
        PAGES_PATH.write_text(json.dumps(DEFAULT_PAGES, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        return [p for p in json.loads(PAGES_PATH.read_text(encoding="utf-8")) if p.get("path")]
    except Exception as e:
        log(f"pages.json broken: {e}")
        return DEFAULT_PAGES


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", help="このパスだけ撮る (例: /today)")
    ap.add_argument("--name", help="--page 時の保存名 (省略時はパスから生成)")
    args = ap.parse_args()

    from app.services.auth_service import create_access_token
    from playwright.sync_api import sync_playwright

    tok = create_access_token(OWNER_ID, OWNER_EMAIL)
    day = datetime.now(JST).strftime("%Y-%m-%d")
    out_dir = SHOTS_DIR / day
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.page:
        pages = [{"name": args.name or args.page.strip("/").replace("/", "_") or "root", "path": args.page}]
    else:
        pages = load_pages()

    ok = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1500, "height": 950})
        ctx.add_cookies([{"name": "done_access_token", "value": tok, "domain": "127.0.0.1", "path": "/"}])
        ctx.add_init_script(f"localStorage.setItem('done-token','{tok}')")
        pg = ctx.new_page()
        for item in pages:
            name = str(item.get("name") or item["path"].strip("/").replace("/", "_") or "root")
            stamp = datetime.now(JST).strftime("%H%M") if args.page else ""
            fname = f"{name}-{stamp}.png" if stamp else f"{name}.png"
            try:
                pg.goto(BASE + item["path"], wait_until="networkidle", timeout=90_000)
                pg.wait_for_timeout(2500)
                pg.screenshot(path=str(out_dir / fname))
                log(f"{item['path']} -> {day}/{fname}")
                ok += 1
            except Exception as e:
                log(f"{item['path']} FAILED: {str(e)[:160]}")
        browser.close()
    log(f"done {ok}/{len(pages)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
