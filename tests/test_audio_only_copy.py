"""プレビュー用の音だけの写し（/production-assets/media?variant=audio）の試験。"""
import asyncio
import json
import shutil
import subprocess

import pytest

from app.api import production_asset_routes as par

FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(not FFMPEG, reason="ffmpeg が要る")


def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,start_time:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True).stdout
    return json.loads(out)


def _make(path, args):
    subprocess.run([FFMPEG, "-y", "-v", "error", *args, str(path)], check=True)


def test_audio_copy_from_video_and_wav(tmp_path, monkeypatch):
    monkeypatch.setattr(par, "_room_dir", lambda room_id: tmp_path)
    video = tmp_path / "v.mp4"
    _make(video, ["-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=3", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                  "-c:v", "libx264", "-c:a", "aac", "-shortest"])
    wav = tmp_path / "s.wav"
    _make(wav, ["-f", "lavfi", "-i", "sine=frequency=880:duration=2"])
    silent = tmp_path / "n.mp4"
    _make(silent, ["-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=1", "-c:v", "libx264"])

    out = asyncio.run(par._audio_only_copy("room", {"id": "a1", "view_path": str(video)}))
    info = _probe(out)
    assert [s["codec_type"] for s in info["streams"]] == ["audio"]
    assert info["streams"][0]["codec_name"] == "aac"
    assert abs(float(info["format"]["duration"]) - 3.0) < 0.1
    # 2回目は作り直さない
    mtime = out.stat().st_mtime_ns
    assert asyncio.run(par._audio_only_copy("room", {"id": "a1", "view_path": str(video)})) == out
    assert out.stat().st_mtime_ns == mtime

    out2 = asyncio.run(par._audio_only_copy("room", {"id": "a2", "local_path": str(wav)}))
    info2 = _probe(out2)
    assert info2["streams"][0]["codec_name"] == "aac"   # wav は AAC にして軽くする
    assert abs(float(info2["format"]["duration"]) - 2.0) < 0.1

    # 音の無い映像は写しを作らない（画面は音無しとして扱う）
    assert asyncio.run(par._audio_only_copy("room", {"id": "a3", "proxy_path": str(silent)})) is None
    assert not (tmp_path / "a3_audio.m4a").exists()
