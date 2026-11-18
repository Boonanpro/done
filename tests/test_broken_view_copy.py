"""壊れた画面用の写しを配らない・作り直す・2つの処理が同時に作らない（2026-11-18 スヤさん2本目）。

2本目の録画の画面用の写しは、2つの処理が同じ一時ファイルに同時に書いて、映像も音も無いファイルに
なっていた。ファイルがあるので /media はそれを配り続け、画面は真っ黒、音の写しとタイムラインの絵も
そこから作ろうとして失敗していた。"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import production_asset_routes as r

ROOM = "brokenview-test-room"
pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None and not Path("/opt/homebrew/bin/ffmpeg").exists(),
                                reason="ffmpeg missing")


@pytest.fixture()
def room(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "ASSET_ROOT", tmp_path)
    d = r._room_dir(ROOM)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _clip(path: Path, seconds: int = 2) -> Path:
    subprocess.run([r._ffmpeg(), "-y", "-f", "lavfi", "-i", f"testsrc=size=640x360:rate=30:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
                   check=True, capture_output=True)
    return path


def _broken_like_suya(src: Path, out: Path) -> Path:
    """本番で見つかった形: moov は先頭にあるが、中の最初の箱の大きさが mdat の値で上書きされている。"""
    data = bytearray(src.read_bytes())
    # ftyp の後の moov の中、最初の子（mvhd）の大きさを壊す
    i = data.find(b"moov")
    data[i + 4:i + 8] = (0x3D000000).to_bytes(4, "big")
    out.write_bytes(bytes(data))
    return out


def _rows(room: Path, rows):
    (room / "assets.json").write_text(json.dumps(rows), encoding="utf-8")


def _client():
    app = FastAPI()
    app.include_router(r.router, prefix="/api/v1")
    return TestClient(app)


def test_broken_copy_is_detected(room):
    good = _clip(room / "good.mp4")
    bad = _broken_like_suya(good, room / "bad.mp4")
    assert r._media_ok(good)
    assert not r._media_ok(bad)
    assert not r._media_ok(room / "missing.mp4")


def test_media_serves_proxy_instead_of_broken_view_and_rebuilds(room, monkeypatch):
    proxy = _clip(room / "a_proxy.mp4")
    view = _broken_like_suya(proxy, room / "a_view.mp4")
    _rows(room, [{"id": "a", "room_id": ROOM, "kind": "video", "source_type": "local_path", "status": "proxy_ready",
                  "original_uri": str(proxy), "proxy_path": str(proxy), "view_path": str(view),
                  "view_error_at": 9e12,  # 失敗の印が付いていても、壊れた写しは作り直す
                  "metadata": {"duration": 700, "proxy_fps": 30}}])
    started = []
    monkeypatch.setattr(r, "_make_view_copy", lambda room_id, aid, **k: started.append(aid))
    res = _client().get(f"/api/v1/production-assets/media?room_id={ROOM}&asset_id=a&variant=view",
                        headers={"Range": "bytes=0-0"})
    assert res.status_code == 206
    assert res.headers["content-range"].endswith(f"/{proxy.stat().st_size}")  # 壊れた写しではなく再生用の写し
    for _ in range(50):
        if started:
            break
        import time; time.sleep(0.05)
    assert started == ["a"]
    assert not view.exists() and (room / "a_view.broken.mp4").exists()


def test_audio_copy_is_made_from_a_readable_copy(room):
    proxy = _clip(room / "b_proxy.mp4")
    view = _broken_like_suya(proxy, room / "b_view.mp4")
    _rows(room, [{"id": "b", "room_id": ROOM, "kind": "video", "source_type": "local_path",
                  "original_uri": str(proxy), "proxy_path": str(proxy), "view_path": str(view), "metadata": {}}])
    res = _client().get(f"/api/v1/production-assets/media?room_id={ROOM}&asset_id=b&variant=audio",
                        headers={"Range": "bytes=0-0"})
    assert res.status_code == 206
    assert r._media_ok(room / "b_audio.m4a")


def test_second_process_does_not_encode_the_same_copy(room):
    proxy = _clip(room / "c_proxy.mp4")
    _rows(room, [{"id": "c", "room_id": ROOM, "kind": "video", "source_type": "local_path",
                  "original_uri": str(proxy), "proxy_path": str(proxy), "metadata": {"duration": 2, "proxy_fps": 30}}])
    (room / "c_view.lock").write_text("12345 0")  # 別の本体が作っている最中
    assert r._make_view_copy(ROOM, "c", force=True) is None
    assert not (room / "c_view.mp4").exists()
    (room / "c_view.lock").unlink()
    out = r._make_view_copy(ROOM, "c", force=True)
    assert out and r._media_ok(out)
    assert not (room / "c_view.lock").exists()
    assert not list(room.glob("c_view.*.tmp.mp4"))


def test_broken_encode_is_not_put_in_place(room, monkeypatch):
    proxy = _clip(room / "d_proxy.mp4")
    _rows(room, [{"id": "d", "room_id": ROOM, "kind": "video", "source_type": "local_path",
                  "original_uri": str(proxy), "proxy_path": str(proxy), "metadata": {"duration": 2, "proxy_fps": 30}}])
    real_run = subprocess.run

    def fake_run(cmd, *a, **k):
        res = real_run(cmd, *a, **k)
        if cmd and "libx264" in cmd:  # 書き終わった写しを、本番で起きた形に壊す
            out = Path(cmd[-1])
            _broken_like_suya(out, out)
        return res
    monkeypatch.setattr(r.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        r._make_view_copy(ROOM, "d", force=True)
    assert not (room / "d_view.mp4").exists()
