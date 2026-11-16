"""One set of numbers for a picture's size/place (clip_placement)."""
import copy

from app.services import clip_placement as cp
from app.services import timeline_commands as tc
from app.services import timeline_motion as tm

W, H = cp.canvas_px("16:9")
VIDEO = {"id": "v", "kind": "video", "metadata": {"width": 1920, "height": 1080, "duration": 14.4}}
IMAGE = {"id": "i", "kind": "image", "metadata": {"width": 600, "height": 300}}
ASSETS = {"v": VIDEO, "i": IMAGE}


def _seq(clip, lane="video"):
    return {"format": "16:9", "frame_rate": 30, "tracks": [{"id": "t", "type": lane, "clips": [clip]}]}


def test_punch_in_box_becomes_size_and_offset():
    # X固定ポストの本編: 頭を切るために 122% に寄せた枠
    clip = {"id": "c", "asset_id": "v", "timeline_start": 0, "timeline_end": 2, "source_start": 0, "source_end": 2,
            "position": {"x": -0.11, "y": -0.22, "width": 1.22, "height": 1.22}}
    f = cp.to_canonical(clip, 1920, 1080, W, H)
    assert f["transform"] == {"scale": 1.22, "x": 0.0, "y": -0.11}
    assert f["crop"] is None
    cp.apply_canonical(clip, f)
    assert "position" not in clip
    # the export draws the same box back
    r = cp.render_fields(clip, 1920, 1080, W, H)
    assert all(abs(r["position"][k] - v) < 1e-6 for k, v in {"x": -0.11, "y": -0.22, "width": 1.22, "height": 1.22}.items())


def test_pip_box_with_other_shape_keeps_what_showed_as_crop():
    # a square wipe on 16:9 footage: cover crops the sides → the same look as size + crop
    clip = {"id": "c", "asset_id": "v", "timeline_start": 0, "timeline_end": 2, "source_start": 0, "source_end": 2,
            "position": {"x": 0.6, "y": 0.1, "width": 0.3, "height": 0.3 * 16 / 9}, "shape": "circle"}
    f = cp.to_canonical(clip, 1920, 1080, W, H)
    assert f is not None and f["crop"]["left"] > 0.1 and abs(f["crop"]["left"] - f["crop"]["right"]) < 1e-3
    n = copy.deepcopy(clip)
    cp.apply_canonical(n, f)
    P = cp.picture_rect(n, 0, 1920, 1080, W, H)
    V = cp._visible(P, cp._crop(n), None)
    assert abs(V[0] - 0.6 * W) < 1 and abs(V[2] - 0.9 * W) < 1 and abs(V[1] - 0.1 * H) < 1


def test_dense_eased_keys_become_few_keys_with_curves():
    seq = _seq({"id": "c", "asset_id": "v", "timeline_start": 0, "timeline_end": 3, "source_start": 0, "source_end": 3})
    poses = [{"t": 0, "x": 0, "y": 0, "w": 1, "h": 1}, {"t": 1, "x": -0.1, "y": -0.1, "w": 1.2, "h": 1.2},
             {"t": 2.5, "x": -0.1, "y": -0.1, "w": 1.2, "h": 1.2}]
    r = tm.animate(seq, ASSETS, "c", poses, easing="cubic_out")
    assert r["ok"], r
    clip = seq["tracks"][0]["clips"][0]
    assert "transform_keys" not in clip and "position" not in clip
    keys = clip["motion_keys"]
    assert len(keys) == 3, keys
    assert keys[0]["ease"] == "ease_out" and abs(keys[1]["scale"] - 1.2) < 1e-3 and abs(keys[1]["t"] - 1) < 1e-3
    s, x, y = cp.motion_at(clip, 0.5)
    assert abs(s - (1 + 0.2 * (1 - 0.5 ** 3))) < 2e-3


def test_set_clip_props_position_is_stored_as_numbers():
    seq = _seq({"id": "c", "asset_id": "i", "kind": "image", "timeline_start": 0, "timeline_end": 2,
                "source_start": 0, "source_end": 2, "fit": "contain"})
    r = tc.set_clip_props(seq, ASSETS, clip_id="c", props={"position": {"x": 0.1, "y": 0.1, "width": 0.25, "height": 0.25 * 9 / 8}})
    assert r["ok"], r
    clip = seq["tracks"][0]["clips"][0]
    assert "position" not in clip and clip["transform"]["scale"] == 0.25
    assert r["changed"]["transform"] == clip["transform"]


def test_motion_keys_prop_and_split_keep_the_move():
    seq = _seq({"id": "c", "asset_id": "v", "timeline_start": 0, "timeline_end": 4, "source_start": 0, "source_end": 4})
    r = tc.set_clip_props(seq, ASSETS, clip_id="c", props={"motion_keys": [
        {"t": 0, "scale": 1, "x": 0, "y": 0, "ease": "ease_in_out"}, {"t": 3, "scale": 1.5, "x": 0.1, "y": 0}]})
    assert r["ok"], r
    before = cp.motion_at(seq["tracks"][0]["clips"][0], 2.0)
    assert tc.split_clip(seq, clip_id="c", at=1.5)["ok"]
    second = [c for c in seq["tracks"][0]["clips"] if c["id"] != "c"][0]
    after = cp.motion_at(second, 0.5)
    assert all(abs(a - b) < 1e-6 for a, b in zip(before, after))
    assert tc.set_clip_props(seq, ASSETS, clip_id="c", props={"motion_keys": [{"t": i / 30, "scale": 1, "x": 0, "y": 0} for i in range(90)]})["ok"] is False


def test_normalize_contents_converts_old_and_keeps_scenes():
    clip = {"id": "c", "asset_id": "v", "timeline_start": 0, "timeline_end": 2, "source_start": 0, "source_end": 2,
            "position": {"x": -0.1, "y": -0.1, "width": 1.2, "height": 1.2}}
    pop = {"id": "p", "asset_id": "v", "timeline_start": 0, "timeline_end": 2, "position": {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.3},
           "effects": [{"type": "popout"}]}
    contents = [{"id": "w", "timeline": {"sequence": {"format": "16:9", "tracks": [{"type": "video", "clips": [clip, pop]}]}}}]
    n = cp.normalize_contents(contents, lambda: [VIDEO])
    assert n == 1 and "position" not in clip and clip["transform"]["scale"] == 1.2
    assert "position" in pop  # pop-outs keep their own box
    assert cp.normalize_contents(contents, lambda: (_ for _ in ()).throw(AssertionError("no read"))) == 0


def test_render_sequence_moves_and_negative_keys():
    clip = {"id": "c", "asset_id": "v", "timeline_start": 0, "timeline_end": 2, "source_start": 0, "source_end": 2,
            "motion_keys": [{"t": -1, "scale": 1, "x": 0, "y": 0}, {"t": 1, "scale": 2, "x": 0, "y": 0}]}
    out = cp.render_sequence(_seq(clip), ASSETS)
    c = out["tracks"][0]["clips"][0]
    assert "motion_keys" not in c and c["transform_keys"][0]["t"] == 0
    assert abs(c["position"]["width"] - 1.5) < 1e-6  # half way through the move at the clip head
    assert abs(c["transform_keys"][-1]["w"] - 2 / 1.5) < 1e-4
    # idempotent: box-form clips pass through
    again = cp.render_sequence(out, ASSETS)
    assert again["tracks"][0]["clips"][0] == c
