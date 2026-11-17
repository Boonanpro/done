"""段の表示・消音スイッチと、世代の写しの住所の読み替え（2026-11-17）。"""
from __future__ import annotations

from app.paths import DAN_WORKSPACE, LIVE_ROOT, local_file
from app.services import lane_switches as ls


def _seq(switches=None):
    seq = {
        "tracks": [
            {"id": "v0", "type": "video", "clips": [{"id": "base", "asset_id": "A", "timeline_start": 0, "timeline_end": 10}]},
            {"id": "a0", "type": "audio", "clips": [
                {"id": "voice", "asset_id": "A", "timeline_start": 0, "timeline_end": 10},
                {"id": "bgm", "asset_id": "M", "role": "bgm", "timeline_start": 0, "timeline_end": 10},
            ]},
            {"id": "v1", "type": "video", "clips": [{"id": "open", "asset_id": "O", "timeline_start": 0, "timeline_end": 5}]},
        ]
    }
    if switches is not None:
        seq["lane_switches"] = switches
    return seq


def test_lanes_match_editor_rule():
    lanes = ls.clip_lanes(_seq()["tracks"])
    assert lanes["base"] == ("visual", 0.0)
    assert lanes["open"] == ("visual", 1.0)  # 音声の track は数えない
    assert lanes["voice"] == ("audio", 0.0)
    assert lanes["bgm"] == ("audio", 1.0)


def test_hidden_visual_lane_is_not_drawn():
    from app.api.production_asset_routes import _sequence_audio_clips, _sequence_z_items
    seq = _seq({"visual-1": {"hidden": True}})
    base, z = _sequence_z_items(seq)
    assert [c["id"] for c in base] == ["base"]
    assert all(c["id"] != "open" for _, c in z)
    # 音は映像の段を隠しても鳴る
    assert {c["id"] for c in _sequence_audio_clips(seq)} == {"voice", "bgm"}
    # スイッチが無ければ出る
    _, z2 = _sequence_z_items(_seq())
    assert any(c["id"] == "open" for _, c in z2)


def test_muted_audio_lane_is_not_heard():
    from app.api.production_asset_routes import _sequence_audio_clips
    seq = _seq({"audio-1": {"muted": True}})
    assert [c["id"] for c in _sequence_audio_clips(seq)] == ["voice"]


def test_render_sequence_drops_switched_off_and_is_idempotent():
    from app.services.clip_placement import render_sequence
    out = render_sequence(_seq({"visual-1": {"hidden": True}}), {})
    assert "lane_switches" not in out
    assert out["tracks"][2]["clips"] == []
    assert ls.drop_switched_off(out) is out


def test_switch_off_flag_false_keeps_clips():
    out = ls.drop_switched_off(_seq({"visual-1": {"hidden": False}, "audio-1": {}}))
    assert [len(t["clips"]) for t in out["tracks"]] == [1, 2, 1]


def test_release_paths_map_to_live_uploads():
    p = f"{DAN_WORKSPACE.as_posix()}/releases/db23980566c8-c975ac/uploads/production-assets/r/x_view.mp4"
    assert local_file(p) == str(LIVE_ROOT / "uploads/production-assets/r/x_view.mp4")
    # 写しの中のコード・ほかの場所はそのまま
    code = f"{DAN_WORKSPACE.as_posix()}/releases/abc/app/x.py"
    assert local_file(code) == code
    assert local_file("/tmp/releases/abc/uploads/x") == "/tmp/releases/abc/uploads/x"
