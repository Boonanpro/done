"""A picture's linked sound can be replaced by a processed voice file (2026-11-25)."""
from app.services import timeline_commands as tc

ASSETS = {
    "cam": {"id": "cam", "kind": "video", "metadata": {"duration": 100}},
    "voice": {"id": "voice", "kind": "audio", "metadata": {"duration": 100}},
    "img": {"id": "img", "kind": "image", "metadata": {"width": 10, "height": 10}},
}


def _seq():
    v = {"id": "v1", "asset_id": "cam", "link_id": "lk", "timeline_start": 0, "timeline_end": 2,
         "source_start": 10, "source_end": 12}
    a = {"id": "a1", "asset_id": "cam", "link_id": "lk", "timeline_start": 0, "timeline_end": 2,
         "source_start": 10, "source_end": 12, "volume": 0}
    return {"format": "16:9", "frame_rate": 30, "tracks": [
        {"id": "tv", "type": "video", "clips": [v]}, {"id": "ta", "type": "audio", "clips": [a]}]}


def test_linked_camera_sound_takes_the_voice_file_and_stays_linked():
    seq = _seq()
    r = tc.set_clip_props(seq, ASSETS, clip_id="a1", props={"asset_id": "voice", "source_start": 10, "volume": 0.85})
    assert r["ok"] is not False
    a = seq["tracks"][1]["clips"][0]
    v = seq["tracks"][0]["clips"][0]
    assert a["asset_id"] == "voice" and a["link_id"] == "lk" and a["volume"] == 0.85
    assert (a["source_start"], a["source_end"]) == (10, 12)
    assert v["asset_id"] == "cam" and (v["source_start"], v["source_end"]) == (10, 12)
    assert tc.validate_sequence(seq, ASSETS) == []


def test_picture_clip_still_cannot_become_audio_and_audio_lane_cannot_take_an_image():
    seq = _seq()
    assert tc.set_clip_props(seq, ASSETS, clip_id="v1", props={"asset_id": "voice"})["ok"] is False
    assert tc.set_clip_props(seq, ASSETS, clip_id="a1", props={"asset_id": "img"})["ok"] is False
