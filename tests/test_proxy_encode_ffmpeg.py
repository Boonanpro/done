"""The proxy encode must work with the FFmpeg installed on this machine (FFmpeg 8+ removed -vsync)."""
import subprocess
from pathlib import Path

from app.api import production_asset_routes as m


def test_proxy_encode_runs_on_installed_ffmpeg(tmp_path, monkeypatch):
    src = tmp_path / "src.mov"
    subprocess.run(
        [m._ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=60000/1001:duration=1",
         "-f", "lavfi", "-i", "sine=duration=1", "-c:v", "libx264", "-c:a", "pcm_s16be", "-shortest", str(src)],
        check=True,
    )
    out = tmp_path / "room"
    out.mkdir()
    monkeypatch.setattr(m, "_room_dir", lambda rid: out)
    monkeypatch.setattr(m, "_room_frame_rate", lambda rid: 30.0)
    m._run_proxy_job("test-room", "a1", str(src))
    proxy = out / "a1_proxy.mp4"
    assert proxy.exists() and proxy.stat().st_size > 0
