"""長い録画の高画質の写し（proxy）を持たず、書き出しは元の録画から読む（2026-11-18 本人承認）。

- 画面用の写しがあり、元の録画が読める長い録画だけ、写しを消して記録から外す。
- 書き出しの音は、大きい元の録画を丸ごと読まず、使う所の前後だけを取り出す。取り出した音は
  丸ごと取り出した時と同じ位置に来る（NAS の上の37GBの録画を全部読んで、12秒の書き出しに3分かかった）。
- 家の中かどうかの返事（/home-route）は、端末のインターネット側の住所が家と同じ時だけ直通の住所を返す。
"""
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import production_asset_routes as r

ROOM = "noproxy-test-room"
pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None and not Path("/opt/homebrew/bin/ffmpeg").exists(),
                                reason="ffmpeg missing")


@pytest.fixture()
def room(tmp_path, monkeypatch):
    root = tmp_path / "uploads"
    monkeypatch.setattr(r, "UPLOADS_DIR", root)
    monkeypatch.setattr(r, "ASSET_ROOT", root / "production-assets")
    d = r._room_dir(ROOM)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _video(path: Path, seconds: int, size: str = "640x360") -> Path:
    subprocess.run([r._ffmpeg(), "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=30:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=330:beep_factor=4:duration={seconds}",
                    "-c:v", "libx264", "-g", "15", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
                   check=True, capture_output=True)
    return path


def _rows(room: Path, rows):
    (room / "assets.json").write_text(json.dumps(rows), encoding="utf-8")


def _asset(room: Path, tmp_path: Path, *, original=True, view=True):
    orig = _video(tmp_path / "orig.mp4", 6, "1280x720")
    proxy = _video(room / "a1_proxy.mp4", 6)
    (room / "a1_proxy.pts.json").write_text("{}")
    v = _video(room / "a1_view.mp4", 6) if view else None
    row = {"id": "a1", "kind": "video", "local_path": str(orig) if original else str(tmp_path / "gone.mp4"),
           "proxy_path": str(proxy), "view_path": str(v) if v else None,
           "metadata": {"duration": 6.0, "width": 1280, "height": 720}}
    _rows(room, [row])
    return orig, proxy


def test_long_recording_proxy_is_dropped_and_export_reads_original(room, tmp_path, monkeypatch):
    monkeypatch.setattr(r, "PROXY_DROP_MIN_SECONDS", 5.0)
    orig, proxy = _asset(room, tmp_path)
    got = r.drop_export_proxy(ROOM, "a1")
    assert got["dropped"] is True
    assert not proxy.exists() and not proxy.with_suffix(".pts.json").exists()
    row = r._read_assets(ROOM)[0]
    assert row["proxy_path"] is None and row["proxy_dropped"]["bytes"] > 0
    # 書き出しは元の録画を読む
    assert r._asset_source_path(row) == orig.resolve()


def test_proxy_kept_without_original_or_view(room, tmp_path, monkeypatch):
    monkeypatch.setattr(r, "PROXY_DROP_MIN_SECONDS", 5.0)
    _orig, proxy = _asset(room, tmp_path, original=False)
    assert r.drop_export_proxy(ROOM, "a1") == {"dropped": False, "why": "original missing"}
    assert proxy.exists()
    _orig, proxy = _asset(room, tmp_path, view=False)
    assert r.drop_export_proxy(ROOM, "a1")["why"] == "no usable view copy"
    assert proxy.exists()


def test_short_recording_keeps_proxy(room, tmp_path):
    _orig, proxy = _asset(room, tmp_path)
    assert r.drop_export_proxy(ROOM, "a1")["why"] == "short"
    assert proxy.exists()


def _wav(path: Path) -> np.ndarray:
    raw = subprocess.run([r._ffmpeg(), "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def test_span_decoded_audio_matches_whole_decode(room, tmp_path, monkeypatch):
    src = _video(tmp_path / "long.mp4", 90)
    asset = {"id": "s1", "kind": "video", "local_path": str(src), "proxy_path": None,
             "metadata": {"duration": 90.0, "has_audio": True, "audio_codec": "aac"}}
    _rows(room, [asset])
    clips = [{"id": "c1", "asset_id": "s1", "timeline_start": 0.0, "timeline_end": 3.0, "source_start": 10.25, "source_end": 13.25},
             {"id": "c2", "asset_id": "s1", "timeline_start": 3.0, "timeline_end": 6.0, "source_start": 70.5, "source_end": 73.5}]
    seq = {"duration": 6.0, "tracks": [{"id": "a", "type": "audio", "clips": clips}]}

    out = {}
    for mode, limit in (("whole", 10**12), ("span", 0)):
        monkeypatch.setattr(r, "_DECODE_WHOLE_MAX_BYTES", limit)
        folder = tmp_path / mode
        folder.mkdir()
        decoded = r._decoded_audio_sources(clips, r._assets_by_id(ROOM), folder)
        if mode == "span":
            wavs = sorted(p.name for p in folder.glob("*.wav"))
            assert len(wavs) == 2, wavs   # 2つの離れた所だけを取り出した
        r._render_audio_window(ROOM, seq, 0.0, 6.0, folder / "mix.wav", decoded)
        out[mode] = _wav(folder / "mix.wav")
    a, b = out["whole"], out["span"]
    assert len(a) == len(b)
    assert float(np.max(np.abs(a - b))) < 1e-4


def test_home_route_only_for_the_home_address(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".dan/lan-media").mkdir(parents=True)
    (home / ".dan/lan-media/route.json").write_text(json.dumps({"base": "https://dan-home.paina.info", "alive": True}))
    monkeypatch.setattr(r.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(r, "_home_public_ip", lambda: "203.0.113.5")
    app = FastAPI()
    app.include_router(r.router, prefix="/api/v1")
    c = TestClient(app)
    url = "/api/v1/production-assets/home-route"
    assert c.get(url, headers={"cf-connecting-ip": "203.0.113.5"}).json() == {"base": "https://dan-home.paina.info"}
    assert c.get(url, headers={"cf-connecting-ip": "198.51.100.7"}).json() == {"base": None}
    assert c.get(url).json() == {"base": None}
