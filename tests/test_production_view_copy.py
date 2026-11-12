"""長い録画だけに画面用の小さい写しを作り、/media の variant=view で配る（2026-11-12）。"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import production_asset_routes as r

ROOM = "viewcopy-test-room"


def _ffmpeg_ok() -> bool:
    return shutil.which("ffmpeg") is not None or Path("/opt/homebrew/bin/ffmpeg").exists()


@pytest.fixture()
def room(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "ASSET_ROOT", tmp_path)
    d = r._room_dir(ROOM)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(d: Path, rows):
    (d / "assets.json").write_text(json.dumps(rows), encoding="utf-8")


def test_needs_view_copy_only_for_long_videos(room):
    proxy = room / "a_proxy.mp4"
    proxy.write_bytes(b"x" * 10)
    short = {"id": "a", "kind": "video", "proxy_path": str(proxy), "metadata": {"duration": 120}}
    long = {**short, "metadata": {"duration": 4956}}
    assert not r._needs_view_copy(short)
    assert r._needs_view_copy(long)
    assert not r._needs_view_copy({**long, "kind": "image"})
    assert not r._needs_view_copy({**long, "proxy_path": str(room / "missing.mp4")})


@pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg missing")
def test_make_view_copy_and_serve_with_range(room):
    proxy = room / "b_proxy.mp4"
    subprocess.run([r._ffmpeg(), "-y", "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(proxy)], check=True, capture_output=True)
    _write(room, [{"id": "b", "room_id": ROOM, "kind": "video", "source_type": "local_path",
                   "original_uri": str(proxy), "proxy_path": str(proxy),
                   "metadata": {"duration": 2, "proxy_fps": 30}}])
    assert r._make_view_copy(ROOM, "b") is None  # 2 seconds: not needed
    out = r._make_view_copy(ROOM, "b", force=True)
    assert out and out.exists()
    row = r._read_assets(ROOM)[0]
    assert row["view_path"] == str(out)
    assert "&asset_id=b&variant=view&v=" in row["view_url"]  # 作り直すと住所が変わる（古い写しを混ぜない）
    w = subprocess.run([r._ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
    assert w == "1280"

    app = FastAPI()
    app.include_router(r.router, prefix="/api/v1")
    client = TestClient(app)
    res = client.get(f"/api/v1/production-assets/media?room_id={ROOM}&asset_id=b&variant=view",
                     headers={"Range": "bytes=0-99"})
    assert res.status_code == 206
    assert len(res.content) == 100
