"""作品の絵の時刻の選び方と、画面用の写しが要る動画の見分け（2026-11-15）。"""
from pathlib import Path

from app.api import production_asset_routes as par


def test_cover_time_is_just_after_first_picture():
    seq = {"tracks": [
        {"type": "video", "clips": [{"asset_id": "a", "timeline_start": 2.0, "timeline_end": 10.0}]},
        {"type": "audio", "clips": [{"asset_id": "s", "timeline_start": 0.0, "timeline_end": 10.0}]},
        {"type": "overlay", "clips": [{"asset_id": "b", "timeline_start": 1.0, "timeline_end": 3.0}]},
    ]}
    times = par._cover_times(seq)
    assert times[0] == 1.5          # 最初に絵が出てから0.5秒
    assert 2.5 in times             # 一番下の段の最初のクリップも候補
    assert len(times) == len(set(times))


def test_short_full_hd_video_without_proxy_needs_view_copy(tmp_path: Path):
    f = tmp_path / "agent_x.mp4"
    f.write_bytes(b"0" * 1000)
    big = {"kind": "video", "local_path": str(f), "metadata": {"duration": 18.3, "width": 1920, "height": 1080}}
    small = {"kind": "video", "local_path": str(f), "metadata": {"duration": 18.3, "width": 1280, "height": 720}}
    assert par._needs_view_copy(big)
    assert not par._needs_view_copy(small)
    assert not par._needs_view_copy({**big, "kind": "image"})
    assert not par._needs_view_copy({**big, "local_path": str(tmp_path / "missing.mp4")})
