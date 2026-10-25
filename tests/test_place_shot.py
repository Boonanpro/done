"""撮る道具（scripts/place_shot.py）: 見本だけでなく、着いたか・本物の画面も測り、どれかが NG なら全体が NG（2026-10-25）。

確かめ役の再現: 吹き出しを .md{opacity:0} にした画面、台本室の「画面の表示でエラーが続いています」、/collab に移された
チャットが、どれも OK になっていた。本物のブラウザ（Playwright）で、手元の小さな画面のサーバーを開いて確かめる。
"""
import functools
import http.server
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytest.importorskip("playwright")

CSS = """
.style_app__a1 :where(ul,ol){list-style:none}
.style_md__b2 ol{list-style:decimal}.style_md__b2 ul{list-style:disc}
.style_md__b2 td,.style_md__b2 th{border:1px solid #ccc}.style_md__b2 strong,.style_md__b2 h3{font-weight:800}
.style_md__b2 code{background:#eee}
"""
BOARD = '<div class="style_app__a1"><div class="style_canvas__c3">ボード</div><div class="style_md__b2">こんにちは</div></div>'
PAGES = {
    "ok": f"<style>{CSS}</style>{BOARD}",
    "hidden": f"<style>{CSS}.style_md__b2{{opacity:0!important}}</style>{BOARD}",
    "error": f"<style>{CSS}</style>{BOARD}<p>画面の表示でエラーが続いています</p>",
    "away": "<script>location.replace('/collab')</script>",
    "nomarker": f"<style>{CSS.replace('.style_md__b2 ol{list-style:decimal}.style_md__b2 ul{list-style:disc}', '')}</style>{BOARD}",
    "blank": "<style>body{margin:0;background:#fff}</style>",
}


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    web = tmp_path_factory.mktemp("web")
    for name, html in PAGES.items():
        (web / "preview" / name).mkdir(parents=True)
        (web / "preview" / name / "index.html").write_text(f"<!doctype html><meta charset=utf-8><body>{html}</body>", encoding="utf-8")
    (web / "collab").mkdir()
    (web / "collab" / "index.html").write_text("<!doctype html><meta charset=utf-8><body><p>外の人の窓口</p></body>", encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(web))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    arts = tmp_path_factory.mktemp("tree") / "frontend" / "src" / "app" / "artifacts"
    for name in PAGES:
        (arts / name).mkdir(parents=True)
        ready = "" if name == "blank" else "ready: '[class*=\"_canvas__\"]'\n"
        probe = "" if name == "blank" else "probe: {module: style, scope: app, bubble: md, real: '[class*=\"_md__\"]'}\nshows: [番号の並び, 点の並び, 表, 太字, コード]\n"
        (arts / name / "MAP.md").write_text(f"---\nplace: artifact:{name}\nopen: /preview/{name}/\n{ready}{probe}---\n# {name}\n", encoding="utf-8")
    places = tmp_path_factory.mktemp("places")
    yield f"http://127.0.0.1:{server.server_address[1]}", arts, places
    server.shutdown()


def shoot(site, name, tmp_path):
    base, arts, places = site
    env = {**os.environ, "DAN_ARTIFACTS_DIR": str(arts), "DAN_PLACES_DIR": str(places)}
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "place_shot.py"), name, "--base", base, "--no-login",
                        "--out", str(tmp_path / name)], capture_output=True, text=True, env=env, timeout=180)
    return p.returncode, p.stdout


def test_working_screen_is_ok(site, tmp_path):
    code, out = shoot(site, "ok", tmp_path)
    assert code == 0 and "result=OK" in out, out
    assert "○ 着いたか" in out and "○ 本物の画面" in out and "○ 見本" in out


def test_transparent_bubble_is_ng(site, tmp_path):
    code, out = shoot(site, "hidden", tmp_path)
    assert code == 1 and "result=NG" in out, out
    assert "透けている" in out


def test_error_message_on_screen_is_ng(site, tmp_path):
    code, out = shoot(site, "error", tmp_path)
    assert code == 1 and "× 本物の画面" in out and "エラーが続いています" in out, out


def test_moved_away_is_ng(site, tmp_path):
    code, out = shoot(site, "away", tmp_path)
    assert code == 1 and "× 着いたか" in out and "/collab" in out, out


def test_missing_list_marker_is_ng(site, tmp_path):
    code, out = shoot(site, "nomarker", tmp_path)
    assert code == 1 and "× 見本" in out and "番号の並びが見えない" in out, out


def test_blank_screen_is_ng(site, tmp_path):
    code, out = shoot(site, "blank", tmp_path)
    assert code == 1 and "白紙" in out, out


def test_result_line_names_the_tree(site, tmp_path):
    _, out = shoot(site, "ok", tmp_path)
    tree = site[1].parents[3].as_posix()
    assert f"[place_shot] place=artifact:ok covers= tag=now result=OK root={tree}" in out
