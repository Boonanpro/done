"""段の上下 = 画面の前後（2026-11-18 本人「上の段が前。テロップに限らず必ず守る仕組みに」）。
書き出しの重ね順（_sequence_z_items）が、エディターの段（lane-order.ts の visualLane）と同じであること。"""
import json
import re
import subprocess
from pathlib import Path

from app.api.production_asset_routes import _sequence_z_items, visual_lane

ROOT = Path(__file__).resolve().parents[1]


def _seq():
    return {"tracks": [
        {"type": "video", "clips": [{"id": "base", "asset_id": "a", "timeline_start": 0, "timeline_end": 10}]},
        {"type": "video", "clips": [{"id": "pic_lane1", "asset_id": "b", "timeline_start": 0, "timeline_end": 10}]},
        {"type": "caption", "clips": [
            # 作品に入った順は先でも、段は上（5）
            {"id": "cap_up", "text": "上", "timeline_start": 0, "timeline_end": 10, "layer": 5},
            # 段2（字幕のトラックの既定）
            {"id": "cap_mid", "text": "中", "timeline_start": 0, "timeline_end": 10},
        ]},
        {"type": "video", "clips": [
            # 後から入ったが、下の段（0.5）へ動かした絵
            {"id": "pic_low", "asset_id": "c", "timeline_start": 0, "timeline_end": 10, "layer": 0.5},
            # テロップ2つの間の段（3）の絵
            {"id": "pic_between", "asset_id": "d", "timeline_start": 0, "timeline_end": 10, "layer": 3},
        ]},
        {"type": "caption", "clips": [
            # 作品に入った順は最後でも、段は一番下のテロップ（下へ動かした）
            {"id": "cap_low", "text": "下", "timeline_start": 0, "timeline_end": 10, "layer": 1.5},
        ]},
        {"type": "audio", "clips": [{"id": "voice", "asset_id": "v", "timeline_start": 0, "timeline_end": 10}]},
    ]}


def test_every_visual_item_stacks_by_its_lane():
    base, z = _sequence_z_items(_seq())
    assert [c["id"] for c in base] == ["base"]
    order = [c["id"] for _k, c in z]
    # 後ろ → 前。テロップも絵も、入った順ではなく段の順
    assert order == ["pic_low", "pic_lane1", "cap_low", "cap_mid", "pic_between", "cap_up"]


def test_lane_rule_matches_the_editor():
    """Python の visual_lane と画面の lane-order.ts の visualLane が同じ答えを出す。"""
    cases = [
        ("video", {}, 0), ("video", {}, 4), ("video", {"layer": 7}, 1), ("video", {"composition": "pip"}, 3),
        ("overlay", {}, 5), ("caption", {}, 0), ("caption", {}, 6), ("video", {"track": "caption"}, 1),
        ("effect", {}, 2), ("caption", {"layer": 0}, 4), ("caption", {"layer": 2.5}, 9),
    ]
    py = [visual_lane({"type": t}, c, i) for t, c, i in cases]
    src = (ROOT / "frontend/src/components/video-review/lane-order.ts").read_text(encoding="utf-8")
    body = re.search(r"export function visualLane[\s\S]*?\n}\n", src).group(0)
    js = body.replace("export function", "function")
    js = re.sub(r"\(trackType: [^)]*\): number", "(trackType, clip, visualIndex)", js)
    js = re.sub(r"\s*const own = clip\.layer;", " const own = clip.layer;", js)
    script = js + f"\nconsole.log(JSON.stringify({json.dumps(cases)}.map(([t, c, i]) => visualLane(t, c, i))));"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == py
