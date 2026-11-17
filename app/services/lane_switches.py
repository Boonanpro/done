"""エディターの段ごとの「表示・非表示」「音を出す・出さない」のスイッチ（2026-11-17）。

本人「プレミアやダヴィンチのように、段ごとに表示・非表示、音を出す・出さないのボタンを付けてほしい」。
エディターの段（映像1・音声2…）はデータの track とは1対1でなく、クリップごとに決まる（frontend の
video-review-editor.tsx computeClipLanes）。スイッチは画面の段の名前で覚える:

    sequence["lane_switches"] = {"visual-3": {"hidden": true}, "audio-0": {"muted": true}}

drop_switched_off() が、切った段のクリップを抜いた写しを返す。書き出し・ダンのコマの絵・音の確認は
全部これを通るので、プレビュー（frontend の lane-switches.ts、同じ決め方）と同じ物が出る。
"""
from __future__ import annotations

from typing import Any

KEY = "lane_switches"


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def clip_lanes(tracks: list[dict[str, Any]]) -> dict[str, tuple[str, float]]:
    """clip id → (zone, layer)。computeClipLanes（frontend）と同じ決め方。"""
    out: dict[str, tuple[str, float]] = {}
    visual_index = -1
    pending: list[tuple[dict[str, Any], int, int]] = []
    busy: dict[float, list[tuple[float, float]]] = {}

    def occupy(layer: float, a: float, b: float) -> None:
        busy.setdefault(layer, []).append((a, b))

    def free(layer: float, a: float, b: float) -> bool:
        return not any(b > x + 0.001 and a < y - 0.001 for x, y in busy.get(layer, []))

    order = 0
    for track in tracks:
        if not isinstance(track, dict):
            continue
        ttype = track.get("type")
        if ttype != "audio":
            visual_index += 1
        for clip in track.get("clips") or []:
            if not isinstance(clip, dict) or clip.get("id") is None:
                continue
            cid = str(clip["id"])
            a, b = float(clip.get("timeline_start") or 0), float(clip.get("timeline_end") or 0)
            own = _num(clip.get("layer"))
            if ttype == "audio":
                if own is not None:
                    out[cid] = ("audio", own)
                    occupy(own, a, b)
                else:
                    role = str(clip.get("role") or "")
                    group = 0 if role in ("", "dialogue", "voice") else 1 if role in ("sfx", "se") else 2 if role in ("music", "bgm") else 3
                    pending.append((clip, group, order))
                    order += 1
                continue
            if own is not None:
                layer = own
            elif ttype == "caption" or clip.get("track") == "caption":
                layer = float(max(2, visual_index))
            elif ttype == "effect":
                layer = 3.0
            elif ttype == "overlay":
                layer = 1.0
            else:
                layer = 1.0 if clip.get("composition") in ("pip", "overlay") else float(visual_index)
            out[cid] = ("visual", layer)
    pending.sort(key=lambda p: (p[1], float(p[0].get("timeline_start") or 0), p[2]))
    floor, group, top = 0.0, -1, -1.0
    for clip, g, _ in pending:
        if g != group:
            if top >= 0:
                floor = top + 1
            group, top = g, -1.0
        a, b = float(clip.get("timeline_start") or 0), float(clip.get("timeline_end") or 0)
        layer = floor
        while not free(layer, a, b):
            layer += 1
        occupy(layer, a, b)
        top = max(top, layer)
        out[str(clip["id"])] = ("audio", layer)
    return out


def lane_key(zone: str, layer: float) -> str:
    return f"{zone}-{int(layer) if float(layer).is_integer() else layer}"


def switched_off(sequence: dict[str, Any] | None) -> set[str]:
    """切ってある段の名前（visual-3 は非表示、audio-0 は消音）。"""
    sw = (sequence or {}).get(KEY) if isinstance(sequence, dict) else None
    if not isinstance(sw, dict):
        return set()
    off = set()
    for key, v in sw.items():
        if not isinstance(v, dict):
            continue
        if str(key).startswith("visual-") and v.get("hidden"):
            off.add(str(key))
        if str(key).startswith("audio-") and v.get("muted"):
            off.add(str(key))
    return off


def drop_switched_off(sequence: dict[str, Any] | None) -> dict[str, Any] | None:
    """切った段のクリップを抜いた写し（スイッチの印も外すので、2回通しても同じ）。スイッチが無ければそのまま。"""
    if not isinstance(sequence, dict) or KEY not in sequence:
        return sequence
    off = switched_off(sequence)
    seq = {k: v for k, v in sequence.items() if k != KEY}
    if not off:
        return seq
    tracks = [t for t in (sequence.get("tracks") or []) if isinstance(t, dict)]
    lanes = clip_lanes(tracks)
    new_tracks = []
    for t in sequence.get("tracks") or []:
        if not isinstance(t, dict):
            new_tracks.append(t)
            continue
        keep = [c for c in (t.get("clips") or [])
                if not (isinstance(c, dict) and c.get("id") is not None and str(c["id"]) in lanes
                        and lane_key(*lanes[str(c["id"])]) in off)]
        new_tracks.append({**t, "clips": keep})
    seq["tracks"] = new_tracks
    return seq


def describe(sequence: dict[str, Any] | None) -> str:
    """ダンの見るタイムラインの一行（切ってある段）。"""
    off = sorted(switched_off(sequence))
    if not off:
        return ""
    names = []
    for k in off:
        zone, _, layer = k.partition("-")
        names.append(f"{'映像' if zone == 'visual' else '音声'}の段 layer {layer}（{'非表示' if zone == 'visual' else '消音'}）")
    return "本人が切っている段: " + "、".join(names) + "。書き出し・コマの絵にも出ない。"
