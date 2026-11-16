"""透明な映像（ProRes 4444）: 見るための写しは上に色・下に透明度、書き出しは透けた所から下の段が見える（2026-11-16）。"""
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import app.api.production_asset_routes as r

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")


def _make_media(d: Path) -> tuple[Path, Path]:
    base = d / "base.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=30:d=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(base)], check=True)
    im = Image.new("RGBA", (640, 360), (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle([40, 40, 240, 200], fill=(255, 0, 0, 255))
    im.save(d / "ov.png")
    ov = d / "ov.mov"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", "30", "-t", "2", "-i", str(d / "ov.png"),
                    "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", str(ov)], check=True)
    return base, ov


def _asset(room, aid, p):
    return {"id": aid, "room_id": room, "kind": "video", "source_type": "local_path", "original_uri": str(p),
            "local_path": str(p), "filename": aid, "status": "ready", "metadata": r._probe_video(p),
            "created_at": "x", "updated_at": "x"}


def test_alpha_view_copy_and_export(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "ASSET_ROOT", tmp_path)
    base, ov = _make_media(tmp_path)
    room = "alpharoom"
    r._room_dir(room)
    r._write_assets(room, [_asset(room, "b", base), _asset(room, "o", ov)])
    assets = {a["id"]: a for a in r._read_assets(room)}
    assert not r._asset_has_alpha(assets["b"]) and r._asset_has_alpha(assets["o"])
    assert r._needs_view_copy(assets["o"])

    view = r._make_view_copy(room, "o")
    a = next(x for x in r._read_assets(room) if x["id"] == "o")
    assert a["view_alpha"] == "stacked" and a["has_alpha"] is True
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(view), "-frames:v", "1", str(tmp_path / "v.png")], check=True)
    v = Image.open(tmp_path / "v.png").convert("RGB")
    assert v.size == (640, 720)  # colour over alpha
    assert v.getpixel((100, 100))[0] > 200          # red on top
    assert v.getpixel((100, 360 + 100))[0] > 200    # alpha 255 below it
    assert v.getpixel((500, 360 + 300))[0] < 30     # transparent elsewhere

    seq = {"format": "16:9", "frame_rate": 30, "duration": 2, "tracks": [
        {"id": "l0", "type": "video", "clips": [{"id": "c0", "asset_id": "b", "timeline_start": 0, "timeline_end": 2, "source_start": 0, "source_end": 2}]},
        {"id": "l1", "type": "video", "clips": [{"id": "c1", "asset_id": "o", "timeline_start": 0, "timeline_end": 2, "source_start": 0, "source_end": 2, "fit": "contain"}]}]}
    jd = tmp_path / "job"
    jd.mkdir()
    out = tmp_path / "out.mp4"
    assert r._render_sequence_pass(room, "j", {"timeline": {"sequence": seq, "format": "16:9"}}, jd, out, video_only=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1", "-i", str(out), "-frames:v", "1", str(tmp_path / "e.png")], check=True)
    e = Image.open(tmp_path / "e.png").convert("RGB")
    W, H = e.size
    red = e.getpixel((int(140 / 640 * W), int(120 / 360 * H)))
    blue = e.getpixel((int(500 / 640 * W), int(300 / 360 * H)))
    assert red[0] > 200 and red[2] < 60, red     # the overlay's opaque part
    assert blue[2] > 200 and blue[0] < 60, blue  # the lane below shows where it is transparent
