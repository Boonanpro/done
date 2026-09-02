from pathlib import Path

from app.api.production_asset_routes import (
    _blur_chain_masked,
    _sequence_base_media_clips,
    _sequence_overlay_clips,
    _sequence_video_clips,
)


def test_visual_media_role_comes_from_clip_not_lane_name():
    sequence = {
        "tracks": [
            {"type": "caption", "clips": [{"id": "back", "asset_id": "a", "timeline_start": 0, "timeline_end": 2}]},
            {"type": "effect", "clips": [{"id": "front", "asset_id": "b", "timeline_start": 0, "timeline_end": 2}]},
            {"type": "overlay", "clips": [{"id": "blur", "region": {"x": 0, "y": 0, "width": 1, "height": 1}}]},
            {"type": "audio", "clips": [{"id": "audio", "asset_id": "a", "timeline_start": 0, "timeline_end": 2}]},
        ]
    }

    assert [c["id"] for c in _sequence_video_clips(sequence)] == ["back", "front"]
    assert [c["id"] for c in _sequence_base_media_clips(sequence)] == ["back"]
    assert [c["id"] for c in _sequence_overlay_clips(sequence)] == ["front"]


def test_tracked_blur_prefers_explicit_target_clip_id():
    media = [
        {"id": "wrong", "asset_id": "a", "timeline_start": 20, "timeline_end": 22,
         "source_start": 10, "source_end": 12},
        {"id": "copy", "asset_id": "a", "timeline_start": 20, "timeline_end": 22,
         "source_start": 50, "source_end": 52},
    ]
    masked = _blur_chain_masked(
        "vin", 1, Path("mask.mp4"),
        {"asset_id": "a", "target_clip_id": "copy", "bake_start": 49, "bake_end": 53},
        {"timeline_start": 20, "timeline_end": 22}, media, 1080, 1920, "gaussian", 30,
    )

    assert masked is not None
    graph, _ = masked
    assert "trim=start=1.000:end=3.000" in graph

