# -*- coding: utf-8 -*-
"""ダンのUIを毎日スクショして物語の素材にする。

「どんなUIを試したか」は文章(commit/会話)には残るが見た目は残らない。
後から動画にする時に当時の画面を再現できるよう、その日のUIをそのまま保存する。

  python scripts/ui_snapshot.py            # 全ページ撮影 (ルート自動発見)
  python scripts/ui_snapshot.py --auto     # 全ページ撮影し、見た目が変わったものだけ保存 (ウォッチャーが使う)
  python scripts/ui_snapshot.py --page /xx # 1ページだけ今すぐ撮影

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

# 撮らないルート (成果物・実験場・認証画面・動画用オーバーレイなど)
EXCLUDE_ROUTES = {"api", "artifacts", "demo", "scratch", "login", "register",
                  "caption-frame", "native-caption-overlay", "test-inspector"}


def discover_routes() -> list[dict]:
    """frontend/src/app 直下の page.tsx からダンのダッシュボード画面を自動発見。
    ユーザーが何もしなくても、新しいUIページを作れば翌回から自動で撮られる。"""
    app_dir = PROJECT_ROOT / "frontend" / "src" / "app"
    out = []
    for d in sorted(app_dir.iterdir()):
        if not d.is_dir() or d.name in EXCLUDE_ROUTES:
            continue
        if (d / "page.tsx").exists() or (d / "page.ts").exists():
            out.append({"name": d.name, "path": f"/{d.name}"})
    return out


DEFAULT_PAGES: list[dict] = []  # pages.json は追加分だけ (自動発見に足したい特殊URLがあれば書く)


def log(msg: str) -> None:
    print(f"[ui-shot] {datetime.now():%H:%M:%S} {msg}", flush=True)


def load_pages() -> list[dict]:
    """自動発見 + pages.json の追加分 (同名は追加分が勝つ)。"""
    pages = {p["name"]: p for p in discover_routes()}
    if PAGES_PATH.exists():
        try:
            for p in json.loads(PAGES_PATH.read_text(encoding="utf-8")):
                if p.get("path"):
                    pages[str(p.get("name") or p["path"].strip("/"))] = p
        except Exception as e:
            log(f"pages.json broken (ignored): {e}")
    return list(pages.values())


def _latest_prev_shot(name: str, exclude: Path) -> Path | None:
    """このページの直近の保存済みスクショ (今撮ったファイル自身は除く)。"""
    for day_dir in sorted(SHOTS_DIR.iterdir(), reverse=True):
        if not day_dir.is_dir():
            continue
        cands = [c for c in sorted(day_dir.glob(f"{name}-*.png")) + sorted(day_dir.glob(f"{name}.png")) if c != exclude]
        if cands:
            return cands[-1]
    return None


def _same_image(a: Path, b: Path, threshold: float = 2.0) -> bool:
    """縮小グレースケールの平均差で「見た目が同じ」判定 (微小な描画ゆらぎは無視)。"""
    try:
        from PIL import Image
        ia = Image.open(a).convert("L").resize((48, 48))
        ib = Image.open(b).convert("L").resize((48, 48))
        diff = sum(abs(x - y) for x, y in zip(ia.getdata(), ib.getdata())) / (48 * 48)
        return diff < threshold
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", help="このパスだけ撮る (例: /today)")
    ap.add_argument("--name", help="--page 時の保存名 (省略時はパスから生成)")
    ap.add_argument("--auto", action="store_true", help="全ページ撮影し、前回から見た目が変わったものだけ保存")
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
            stamp = datetime.now(JST).strftime("%H%M") if (args.page or args.auto) else ""
            fname = f"{name}-{stamp}.png" if stamp else f"{name}.png"
            try:
                pg.goto(BASE + item["path"], wait_until="networkidle", timeout=90_000)
                pg.wait_for_timeout(2500)
                target = out_dir / fname
                pg.screenshot(path=str(target))
                if args.auto:
                    prev = _latest_prev_shot(name, target)
                    if prev is not None and prev != target and _same_image(prev, target):
                        target.unlink(missing_ok=True)
                        log(f"{item['path']} unchanged (skip)")
                        continue
                log(f"{item['path']} -> {day}/{fname}")
                ok += 1
            except Exception as e:
                log(f"{item['path']} FAILED: {str(e)[:160]}")
        browser.close()
    log(f"done {ok}/{len(pages)}")
    return 0 if (ok or args.auto) else 1


if __name__ == "__main__":
    sys.exit(main())
