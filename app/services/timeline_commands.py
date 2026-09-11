"""Timeline command layer — the ONLY way the agent mutates a draft.

Every command takes the draft's sequence dict, applies one validated operation
and returns {"ok": bool, "error": str|None, ...}. The LLM never writes raw
JSON: parameters are narrow, every write is clamped/checked here, and
validate_sequence() re-checks the WHOLE draft before commit (per-track overlap
rules, asset existence/duration, id uniqueness, A/V link integrity).

Lane semantics (same rule as the native editor):
  A lane is either AUDIO or VISUAL — nothing else. Visual lanes are pure layers:
  lane array order = stacking (index 0 = backmost, higher = drawn in front).
  A visual lane may hold video/image clips, region effects (blur / mosaic /
  frame / marker / spotlight) and captions; what a clip IS comes from its fields
  (asset_id → media, region → effect, text → caption), never from the lane.
  New visual lanes are written as type "video" (the type string is only a label;
  "caption" lanes are kept for the caption tooling that looks them up).
  Clips may not overlap within one lane; anything may coexist ACROSS lanes.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus"}
MIN_CLIP = 0.05


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _tracks(seq: dict[str, Any]) -> list[dict[str, Any]]:
    return seq.setdefault("tracks", [])


def _track_of_type(seq: dict[str, Any], kind: str, create: bool = True) -> dict[str, Any] | None:
    for t in _tracks(seq):
        if t.get("type") == kind:
            return t
    if not create:
        return None
    t = {"id": _new_id("lane"), "type": kind, "clips": []}
    tracks = _tracks(seq)
    if kind == 'video':
        # A caption can be prepared while its footage is still generating.
        # Creating the first footage lane must not put that footage over it.
        above = next((i for i, existing in enumerate(tracks) if existing.get('type') == 'caption'), len(tracks))
        tracks.insert(above, t)
    else:
        tracks.append(t)
    return t


def _all_clips(seq: dict[str, Any]):
    for ti, t in enumerate(_tracks(seq)):
        for c in t.get("clips") or []:
            yield ti, t, c


def _find_clip(seq: dict[str, Any], clip_id: str):
    for ti, t, c in _all_clips(seq):
        if str(c.get("id")) == clip_id:
            return ti, t, c
    return None, None, None


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _span_free(track: dict[str, Any], ts: float, te: float, ignore: set[str] | None = None) -> bool:
    for c in track.get("clips") or []:
        if ignore and str(c.get("id")) in ignore:
            continue
        if _f(c.get("timeline_start")) < te - 1e-6 and _f(c.get("timeline_end")) > ts + 1e-6:
            return False
    return True


def _is_audio_lane(track: dict[str, Any]) -> bool:
    return str(track.get("type") or "") == "audio"


def _media_top_lane(seq: dict[str, Any], ts: float, te: float) -> int:
    """Highest lane index holding a picture (media/image) clip overlapping [ts,te)."""
    top = -1
    for ti, track, c in _all_clips(seq):
        if _is_audio_lane(track) or c.get("asset_id") is None:
            continue
        if _f(c.get("timeline_start")) < te - 1e-6 and _f(c.get("timeline_end")) > ts + 1e-6:
            top = max(top, ti)
    return top


def _place_visual(seq: dict[str, Any], ts: float, te: float, *, lane: int | None = None,
                  above: bool = True, min_lane: int = 0) -> tuple[int, dict[str, Any]] | tuple[None, str]:
    """Front-most (display top) visual lane whose [ts,te) span is free; when every
    lane is occupied, open a new "video" lane in front (= the editor's ◱ rule).
    `lane` pins an explicit lane index (must be visual and free)."""
    tracks = _tracks(seq)
    if lane is not None:
        if lane == len(tracks):
            t = {"id": _new_id("lane_v"), "type": "video", "clips": []}
            tracks.append(t)
            return lane, t
        if lane < 0 or lane >= len(tracks):
            return None, f"lane {lane} does not exist (0..{len(tracks) - 1})"
        t = tracks[lane]
        if _is_audio_lane(t):
            return None, f"lane {lane} is an audio lane"
        if t.get('locked') or t.get('hidden'):
            return None, f"lane {lane} is locked or hidden"
        if not _span_free(t, ts, te):
            return None, f"lane {lane} not free at {ts:.2f}-{te:.2f}"
        return lane, t
    order = range(len(tracks) - 1, -1, -1) if above else range(len(tracks))
    for i in order:
        t = tracks[i]
        if i < min_lane or _is_audio_lane(t) or t.get("locked") or t.get("hidden"):
            continue
        if str(t.get("type") or "") == "caption":
            continue  # caption lanes stay caption-only for the caption tooling
        if _span_free(t, ts, te):
            return i, t
    # new layer goes in front of the picture lanes but stays BELOW caption lanes
    # (captions must never be blurred/covered by a region or an overlay)
    front = max((i for i, t in enumerate(tracks)
                 if not _is_audio_lane(t) and str(t.get("type") or "") != "caption"), default=-1)
    t = {"id": _new_id("lane_v"), "type": "video", "clips": []}
    tracks.insert(front + 1, t)
    return front + 1, t


def _place_on_lane(seq: dict[str, Any], kind: str, ts: float, te: float) -> dict[str, Any]:
    """First lane of `kind` where [ts,te) is free; appends a new lane when none is.
    Visual kinds other than caption go through _place_visual (no overlay/effect lanes)."""
    if kind not in {"audio", "caption"}:
        _, t = _place_visual(seq, ts, te)
        return t
    for t in _tracks(seq):
        if t.get("type") == kind and _span_free(t, ts, te):
            return t
    t = {"id": _new_id("lane_" + kind[0]), "type": kind, "clips": []}
    _tracks(seq).append(t)
    return t


def _asset(assets: dict[str, dict[str, Any]], asset_id: str) -> dict[str, Any] | None:
    return assets.get(str(asset_id))


def _asset_duration(asset: dict[str, Any] | None) -> float:
    if not isinstance(asset, dict):
        return 0.0
    meta = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
    return _f(meta.get("duration"))


def _asset_is_image(asset: dict[str, Any] | None) -> bool:
    if not isinstance(asset, dict):
        return False
    if asset.get("kind") == "image":
        return True
    p = str(asset.get("local_path") or asset.get("filename") or "")
    return Path(p).suffix.lower() in IMAGE_EXTS


def _asset_is_audio(asset: dict[str, Any] | None) -> bool:
    if not isinstance(asset, dict):
        return False
    if asset.get("kind") == "audio":
        return True
    p = str(asset.get("local_path") or asset.get("filename") or "")
    return Path(p).suffix.lower() in AUDIO_EXTS


def _sorted(track: dict[str, Any]) -> None:
    (track.get("clips") or []).sort(key=lambda c: _f(c.get("timeline_start")))


# ---------------------------------------------------------------- commands

def append_clip(seq: dict[str, Any], assets: dict, *, asset_id: str, source_start: float,
                duration: float, at: float | None = None) -> dict[str, Any]:
    """Append a video (or image) clip on the base lane at `at` (default: timeline end).
    Video gets a linked audio clip; image gets none."""
    a = _asset(assets, asset_id)
    if a is None:
        hint = ", ".join(f"{k}({v.get('filename')})" for k, v in list(assets.items())[:12])
        return {"ok": False, "error": f"asset not found: {asset_id}. available: {hint}"}
    if _asset_is_audio(a):
        return {"ok": False, "error": "audio assets belong on an audio lane; use add_audio"}
    duration = max(MIN_CLIP, _f(duration))
    is_image = _asset_is_image(a)
    if not is_image:
        adur = _asset_duration(a)
        source_start = max(0.0, _f(source_start))
        if adur > 0:
            duration = min(duration, max(MIN_CLIP, adur - source_start))
            if duration <= MIN_CLIP and source_start >= adur:
                return {"ok": False, "error": f"source_start {source_start} beyond asset duration {adur}"}
    ts = _f(at) if at is not None else max(
        [_f(c.get("timeline_end")) for _, _, c in _all_clips(seq)] or [0.0]
    )
    te = ts + duration
    base = _track_of_type(seq, "video")
    if not _span_free(base, ts, te):
        return {"ok": False, "error": f"base lane not free at {ts:.2f}-{te:.2f} (use insert_clip mode=ripple, or another time)"}
    vid = _new_id("clip_ag_v")
    clip: dict[str, Any] = {
        "id": vid, "asset_id": asset_id,
        "timeline_start": round(ts, 3), "timeline_end": round(te, 3),
        # 素材本来のフレーム全体を保持（キャンバス形状に切り抜かない）— D&D/生成配置と同じ規約
        "fit": "contain",
    }
    if is_image:
        clip["kind"] = "image"
        clip["source_start"] = 0.0
        clip["source_end"] = round(duration, 3)
    else:
        clip["source_start"] = round(source_start, 3)
        clip["source_end"] = round(source_start + duration, 3)
        link = _new_id("lk_ag")
        clip["link_id"] = link
        atrack = _track_of_type(seq, "audio")
        atrack.setdefault("clips", []).append({
            "id": _new_id("clip_ag_a"), "asset_id": asset_id, "link_id": link,
            "timeline_start": round(ts, 3), "timeline_end": round(te, 3),
            "source_start": round(source_start, 3), "source_end": round(source_start + duration, 3),
        })
        _sorted(atrack)
    base.setdefault("clips", []).append(clip)
    _sorted(base)
    _recompute_duration(seq)
    return {"ok": True, "clip_id": vid, "timeline_start": clip["timeline_start"], "timeline_end": clip["timeline_end"]}


def add_audio(seq: dict[str, Any], assets: dict, *, asset_id: str, source_start: float,
              duration: float, at: float = 0.0, volume: float = 0.22,
              role: str = "music") -> dict[str, Any]:
    """Place any registered audio asset on the first free audio lane.

    This deliberately has no BGM-specific knowledge: music, SFX, voiceovers and
    externally created audio all use the same validated media-placement command.
    """
    asset = _asset(assets, asset_id)
    if asset is None:
        return {"ok": False, "error": f"asset not found: {asset_id}"}
    if _asset_is_image(asset):
        return {"ok": False, "error": f"asset {asset_id} is an image (no audio)"}
    # a VIDEO asset is a valid audio source: its soundtrack plays from the audio lane
    # (narration cut out of the original recording stays a source range = extendable)
    source_start = max(0.0, _f(source_start))
    duration = max(MIN_CLIP, _f(duration))
    available = _asset_duration(asset)
    if available > 0:
        if source_start >= available:
            return {"ok": False, "error": "source_start is beyond audio duration"}
        duration = min(duration, available - source_start)
    ts = max(0.0, _f(at))
    te = ts + duration
    track = _place_on_lane(seq, "audio", ts, te)
    clip = {
        "id": _new_id("clip_ag_audio"), "asset_id": asset_id,
        "timeline_start": round(ts, 3), "timeline_end": round(te, 3),
        "source_start": round(source_start, 3), "source_end": round(source_start + duration, 3),
        "volume": max(0.0, min(2.0, _f(volume, 0.22))), "role": str(role or "audio"),
    }
    track.setdefault("clips", []).append(clip)
    _sorted(track)
    _recompute_duration(seq)
    return {"ok": True, "clip_id": clip["id"], "timeline_start": clip["timeline_start"], "timeline_end": clip["timeline_end"]}


def insert_clip(seq: dict[str, Any], assets: dict, *, asset_id: str, source_start: float,
                duration: float, at: float, mode: str = "ripple") -> dict[str, Any]:
    """Insert on the base lane at `at`. mode=ripple shifts everything at/after `at`
    (all lanes, keeping sync); mode=overwrite requires the span to be free."""
    if mode not in {"ripple", "overwrite"}:
        return {"ok": False, "error": "mode must be ripple|overwrite"}
    duration = max(MIN_CLIP, _f(duration))
    if mode == "ripple":
        d = duration
        at = _f(at)
        for _, _, c in _all_clips(seq):
            if _f(c.get("timeline_start")) >= at - 1e-6:
                c["timeline_start"] = round(_f(c.get("timeline_start")) + d, 3)
                c["timeline_end"] = round(_f(c.get("timeline_end")) + d, 3)
    return append_clip(seq, assets, asset_id=asset_id, source_start=source_start, duration=duration, at=at)


def remove_clip(seq: dict[str, Any], *, clip_id: str, linked: bool = True) -> dict[str, Any]:
    _, track, clip = _find_clip(seq, clip_id)
    if clip is None:
        return {"ok": False, "error": f"clip not found: {clip_id}"}
    doomed = {clip_id}
    if linked and clip.get("link_id"):
        for _, _, c in _all_clips(seq):
            if c.get("link_id") == clip.get("link_id"):
                doomed.add(str(c.get("id")))
    for t in _tracks(seq):
        t["clips"] = [c for c in (t.get("clips") or []) if str(c.get("id")) not in doomed]
    _recompute_duration(seq)
    return {"ok": True, "removed": sorted(doomed)}


def trim_clip(seq: dict[str, Any], assets: dict, *, clip_id: str, edge: str, new_time: float) -> dict[str, Any]:
    """Move one edge (left|right) of a clip (and its A/V twin) to `new_time`."""
    _, _, clip = _find_clip(seq, clip_id)
    if clip is None:
        return {"ok": False, "error": f"clip not found: {clip_id}"}
    if edge not in {"left", "right"}:
        return {"ok": False, "error": "edge must be left|right"}
    targets = [clip]
    if clip.get("link_id"):
        targets = [c for _, _, c in _all_clips(seq) if c.get("link_id") == clip.get("link_id")]
    for c in targets:
        ts, te = _f(c.get("timeline_start")), _f(c.get("timeline_end"))
        ss = _f(c.get("source_start"))
        has_src = c.get("source_end") is not None and not c.get("freeze") and str(c.get("kind")) != "image"
        if edge == "left":
            nt = min(max(0.0, _f(new_time)), te - MIN_CLIP)
            d = nt - ts
            if has_src and ss + d < 0:
                d = -ss
                nt = ts + d
            c["timeline_start"] = round(nt, 3)
            if has_src:
                c["source_start"] = round(ss + d, 3)
        else:
            nt = max(_f(new_time), ts + MIN_CLIP)
            if has_src:
                a = _asset(assets, str(c.get("asset_id")))
                adur = _asset_duration(a)
                se = ss + (nt - ts)
                if adur > 0 and se > adur:
                    se = adur
                    nt = ts + (se - ss)
                c["source_end"] = round(se, 3)
            c["timeline_end"] = round(nt, 3)
    _recompute_duration(seq)
    return {"ok": True, "timeline_start": targets[0]["timeline_start"], "timeline_end": targets[0]["timeline_end"]}


def move_clip(seq: dict[str, Any], *, clip_id: str, new_start: float) -> dict[str, Any]:
    _, track, clip = _find_clip(seq, clip_id)
    if clip is None:
        return {"ok": False, "error": f"clip not found: {clip_id}"}
    targets = [clip]
    if clip.get("link_id"):
        targets = [c for _, _, c in _all_clips(seq) if c.get("link_id") == clip.get("link_id")]
    d = max(0.0, _f(new_start)) - _f(clip.get("timeline_start"))
    ids = {str(c.get("id")) for c in targets}
    for c in targets:
        nts = _f(c.get("timeline_start")) + d
        nte = _f(c.get("timeline_end")) + d
        # destination must be free on that clip's own lane
        for t in _tracks(seq):
            if any(str(x.get("id")) == str(c.get("id")) for x in t.get("clips") or []):
                if not _span_free(t, nts, nte, ignore=ids):
                    return {"ok": False, "error": f"destination not free on {t.get('type')} lane at {nts:.2f}-{nte:.2f}"}
    for c in targets:
        c["timeline_start"] = round(_f(c.get("timeline_start")) + d, 3)
        c["timeline_end"] = round(_f(c.get("timeline_end")) + d, 3)
    _recompute_duration(seq)
    return {"ok": True}


def add_overlay(seq: dict[str, Any], assets: dict, *, asset_id: str, timeline_start: float,
                timeline_end: float, x: float, y: float, width: float, height: float,
                source_start: float = 0.0) -> dict[str, Any]:
    """PiP video or IMAGE overlay at a normalized canvas box."""
    a = _asset(assets, asset_id)
    if a is None:
        hint = ", ".join(f"{k}({v.get('filename')})" for k, v in list(assets.items())[:12])
        return {"ok": False, "error": f"asset not found: {asset_id}. available: {hint}"}
    ts, te = _f(timeline_start), _f(timeline_end)
    if te - ts < MIN_CLIP:
        return {"ok": False, "error": "overlay span too short"}
    is_image = _asset_is_image(a)
    if not is_image:
        adur = _asset_duration(a)
        if adur > 0 and _f(source_start) + (te - ts) > adur + 0.001:
            return {"ok": False, "error": f"overlay exceeds asset duration ({adur:.2f}s)"}
    lane = _place_on_lane(seq, "overlay", ts, te)
    cid = _new_id("clip_ag_ov")
    clip = {
        "id": cid, "asset_id": asset_id,
        "timeline_start": round(ts, 3), "timeline_end": round(te, 3),
        "source_start": round(_f(source_start), 3),
        "source_end": round(_f(source_start) + (te - ts), 3),
        "position": {"x": round(_f(x), 4), "y": round(_f(y), 4),
                     "width": round(max(0.02, _f(width)), 4), "height": round(max(0.02, _f(height)), 4)},
    }
    if is_image:
        clip["kind"] = "image"
    lane.setdefault("clips", []).append(clip)
    _sorted(lane)
    _recompute_duration(seq)
    return {"ok": True, "clip_id": cid}


_CAPTION_STYLE_KEYS = {"font", "fontSize", "maxWidth", "textAlign", "color", "outlineColor", "outlineWidth", "x", "y"}


def _sanitize_caption_style(style: dict[str, Any] | None) -> dict[str, Any] | None:
    """The caption renderer uses RELATIVE units (fontSize ~1.0) and a fixed key set.
    An agent once wrote fontSize:64 + strokeColor — the design renderer produced a
    fully TRANSPARENT png and the caption silently vanished. Whitelist + clamp."""
    if not isinstance(style, dict):
        return None
    out: dict[str, Any] = {}
    for k, v in style.items():
        if k not in _CAPTION_STYLE_KEYS:
            continue
        if k == "fontSize":
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv > 8.0:  # px指定と思われる値は相対単位へ換算（64px ≈ 1.0）
                fv = fv / 64.0
            out[k] = max(0.0, min(3.0, fv))
        elif k == "maxWidth":
            try:
                out[k] = max(0.05, min(2.0, float(v)))
            except (TypeError, ValueError):
                continue
        elif k == "textAlign":
            if v in {"left", "center", "right"}:
                out[k] = v
        else:
            out[k] = v
    return out or None


def add_caption(seq: dict[str, Any], *, text: str, timeline_start: float, timeline_end: float,
                style: dict[str, Any] | None = None, lane: int | None = None) -> dict[str, Any]:
    text = str(text or "").strip()
    if not text:
        return {"ok": False, "error": "empty text"}
    ts, te = _f(timeline_start), _f(timeline_end)
    if te - ts < MIN_CLIP:
        return {"ok": False, "error": "caption span too short"}
    if lane is None:
        lane_obj = _place_on_lane(seq, "caption", ts, te)
    else:
        idx, lane_obj = _place_visual(seq, ts, te, lane=lane)
        if idx is None:
            return {"ok": False, "error": str(lane_obj)}
    cid = _new_id("clip_ag_c")
    lane_obj.setdefault("clips", []).append({
        "id": cid, "track": "caption", "text": text,
        "timeline_start": round(ts, 3), "timeline_end": round(te, 3),
        **({"style": _sanitize_caption_style(style)} if _sanitize_caption_style(style) else {}),
    })
    _sorted(lane_obj)
    _recompute_duration(seq)
    return {"ok": True, "clip_id": cid}


def insert_freeze(seq: dict[str, Any], assets: dict, *, source_clip_id: str, at_source_time: float | None,
                  timeline_start: float, duration: float) -> dict[str, Any]:
    """Freeze a frame of an existing clip's asset as a base-lane still for `duration`."""
    _, _, src = _find_clip(seq, source_clip_id)
    if src is None or not src.get("asset_id"):
        return {"ok": False, "error": f"source clip not found or not asset-backed: {source_clip_id}"}
    ts = _f(timeline_start)
    te = ts + max(MIN_CLIP, _f(duration))
    base = _track_of_type(seq, "video")
    if not _span_free(base, ts, te):
        return {"ok": False, "error": f"base lane not free at {ts:.2f}-{te:.2f}"}
    fs = _f(at_source_time) if at_source_time is not None else _f(src.get("source_end")) - 0.05
    cid = _new_id("clip_ag_fz")
    base.setdefault("clips", []).append({
        "id": cid, "asset_id": src.get("asset_id"), "freeze": True,
        "source_start": round(max(0.0, fs), 3), "source_end": round(max(0.0, fs), 3),
        "timeline_start": round(ts, 3), "timeline_end": round(te, 3),
    })
    _sorted(base)
    _recompute_duration(seq)
    return {"ok": True, "clip_id": cid}


def set_clip(seq: dict[str, Any], *, clip_id: str, text: str | None = None,
             style: dict[str, Any] | None = None) -> dict[str, Any]:
    _, _, clip = _find_clip(seq, clip_id)
    if clip is None:
        return {"ok": False, "error": f"clip not found: {clip_id}"}
    if style is not None:
        if not isinstance(style, dict) or set(style) - _CAPTION_STYLE_KEYS:
            return {"ok": False, "error": "Invalid caption style. Use fontSize (number, normalized scale), not font_size."}
        for key in ('fontSize', 'maxWidth', 'outlineWidth', 'x', 'y'):
            if key in style:
                try:
                    value = float(style[key])
                    if not math.isfinite(value) or (key == 'fontSize' and value <= 0):
                        raise ValueError()
                except (TypeError, ValueError):
                    return {'ok': False, 'error': f'Invalid numeric caption style: {key}'}
        cleaned = _sanitize_caption_style(style) or {}
        if set(cleaned) != set(style):
            return {"ok": False, "error": "Invalid caption style value; no changes applied."}
        style = cleaned
    if text is not None:
        if clip.get("text") is None:
            return {"ok": False, "error": "clip has no text field (not a caption)"}
        clip["text"] = str(text)
    if isinstance(style, dict):
        style = _sanitize_caption_style(style) or {}
        merged = dict(clip.get("style") or {})
        merged.update(style)
        clip["style"] = merged
    return {"ok": True}


# ---------------------------------------------------------------- region effects / generic clip ops

REGION_STYLES = {"gaussian", "soft", "mosaic", "frame", "marker", "spotlight", "solid", "zoom"}


def _clamp01(v: float, lo: float = -1.0, hi: float = 2.0) -> float:
    return max(lo, min(hi, v))


def _parse_region_keys(keys: Any, dur: float) -> tuple[list[dict[str, float]] | None, str | None]:
    """Clip-relative keyframes [{t, x, y, w?, h?}] (t in seconds from the clip head,
    normalized canvas coords). Sorted, de-duplicated, t clamped into [0, dur]."""
    if keys is None:
        return None, None
    if not isinstance(keys, list):
        return None, "keys must be a list of {t,x,y,w,h}"
    out: list[dict[str, float]] = []
    for k in keys:
        if not isinstance(k, dict) or "t" not in k or "x" not in k or "y" not in k:
            return None, "each key needs t, x, y (w/h optional)"
        if any(not isinstance(k[n], (int,float)) or not math.isfinite(k[n]) for n in ('t','x','y')):
            return None, 'region keys need finite t,x,y'
        if any(n in k and (not isinstance(k[n], (int,float)) or not math.isfinite(k[n]) or k[n]<=0) for n in ('w','h')):
            return None, 'region key w/h must be positive'
        item = {"t": round(max(0.0, min(dur, _f(k["t"]))), 3),
                "x": round(_f(k["x"]), 4), "y": round(_f(k["y"]), 4)}
        if k.get("w") is not None:
            item["w"] = round(max(0.0002, _f(k["w"])), 4)
        if k.get("h") is not None:
            item["h"] = round(max(0.0002, _f(k["h"])), 4)
        out.append(item)
    out.sort(key=lambda k: k["t"])
    dedup: list[dict[str, float]] = []
    for k in out:
        if dedup and abs(dedup[-1]["t"] - k["t"]) < 0.004:
            dedup[-1] = k
        else:
            dedup.append(k)
    return dedup, None


def _check_color(color: Any) -> str | None:
    cs = str(color or "").strip()
    if cs.startswith("#") and len(cs) in (4, 7):
        return cs
    return None


def add_region(seq: dict[str, Any], *, timeline_start: float, timeline_end: float,
               x: float, y: float, width: float, height: float, style: str = "gaussian",
               strength: float | None = None, color: str | None = None,
               opacity: float | None = None, rotation: float | None = None,
               keys: Any = None, lane: int | None = None) -> dict[str, Any]:
    """Region effect clip on a visual lane: blur (gaussian/soft), mosaic, frame
    (rectangle outline = the "yellow frame" highlight), marker, spotlight, solid, zoom.
    The rect is normalized canvas coords (0-1, origin top-left). It processes/draws
    over EVERYTHING composited below its lane, so it goes on a lane above the picture
    it should affect. Moving targets: `keys` = clip-relative keyframes."""
    style = str(style or "gaussian").strip().lower()
    if style not in REGION_STYLES:
        return {"ok": False, "error": f"style must be one of {sorted(REGION_STYLES)}"}
    ts, te = _f(timeline_start), _f(timeline_end)
    if te - ts < MIN_CLIP:
        return {"ok": False, "error": "region span too short"}
    w, h = max(0.0002, min(1.0, _f(width))), max(0.0002, min(1.0, _f(height)))
    # an effect only touches what is BELOW it: land above every picture active in the span
    idx, lane_obj = _place_visual(seq, ts, te, lane=lane, min_lane=_media_top_lane(seq, ts, te) + 1)
    if idx is None:
        return {"ok": False, "error": str(lane_obj)}
    cid = _new_id("fx_ag")
    clip: dict[str, Any] = {
        "id": cid, "timeline_start": round(ts, 3), "timeline_end": round(te, 3),
        "style": style,
        "region": {"x": round(_clamp01(_f(x)), 4), "y": round(_clamp01(_f(y)), 4),
                   "width": round(w, 4), "height": round(h, 4)},
    }
    if strength is not None:
        clip["effect_strength"] = round(max(2.0, min(64.0, _f(strength))), 2)
    if color:
        cs = _check_color(color)
        if not cs:
            return {"ok": False, "error": "color must be #rgb or #rrggbb"}
        clip["effect_color"] = cs
    if opacity is not None:
        clip["effect_opacity"] = round(max(0.0, min(1.0, _f(opacity))), 3)
    if rotation is not None:
        clip["effect_rot"] = round(_f(rotation), 2)
    parsed, err = _parse_region_keys(keys, te - ts)
    if err:
        return {"ok": False, "error": err}
    if parsed:
        clip["region_keys"] = parsed
    lane_obj.setdefault("clips", []).append(clip)
    _sorted(lane_obj)
    _recompute_duration(seq)
    return {"ok": True, "clip_id": cid, "lane": idx, "timeline_start": clip["timeline_start"],
            "timeline_end": clip["timeline_end"]}


def set_region(seq: dict[str, Any], *, clip_id: str, x: float | None = None, y: float | None = None,
               width: float | None = None, height: float | None = None, style: str | None = None,
               strength: float | None = None, color: str | None = None, opacity: float | None = None,
               rotation: float | None = None, keys: Any = None, clear_keys: bool = False) -> dict[str, Any]:
    """Change an existing region effect's rect / style / keyframes (keys replaces all)."""
    _, _, clip = _find_clip(seq, clip_id)
    if clip is None:
        return {"ok": False, "error": f"clip not found: {clip_id}"}
    if not isinstance(clip.get("region"), dict):
        return {"ok": False, "error": "clip is not a region effect"}
    rg = clip["region"]
    if x is not None:
        rg["x"] = round(_clamp01(_f(x)), 4)
    if y is not None:
        rg["y"] = round(_clamp01(_f(y)), 4)
    if width is not None:
        rg["width"] = round(max(0.0002, min(1.0, _f(width))), 4)
    if height is not None:
        rg["height"] = round(max(0.0002, min(1.0, _f(height))), 4)
    if style is not None:
        st = str(style).strip().lower()
        if st not in REGION_STYLES:
            return {"ok": False, "error": f"style must be one of {sorted(REGION_STYLES)}"}
        clip["style"] = st
    if strength is not None:
        clip["effect_strength"] = round(max(2.0, min(64.0, _f(strength))), 2)
    if color is not None:
        cs = _check_color(color)
        if not cs:
            return {"ok": False, "error": "color must be #rgb or #rrggbb"}
        clip["effect_color"] = cs
    if opacity is not None:
        clip["effect_opacity"] = round(max(0.0, min(1.0, _f(opacity))), 3)
    if rotation is not None:
        clip["effect_rot"] = round(_f(rotation), 2)
    if clear_keys:
        clip.pop("region_keys", None)
    if keys is not None:
        dur = _f(clip.get("timeline_end")) - _f(clip.get("timeline_start"))
        parsed, err = _parse_region_keys(keys, dur)
        if err:
            return {"ok": False, "error": err}
        if parsed:
            clip["region_keys"] = parsed
        else:
            clip.pop("region_keys", None)
    return {"ok": True, "region": rg, "style": clip.get("style")}


_PROP_KEYS = {"position", "fit", "opacity", "volume", "speed", "keep_duration", "crop", "transform_keys",
              "video_enabled", "role", "asset_id", "source_start", "grade", "muted"}


def set_clip_props(seq: dict[str, Any], assets: dict, *, clip_id: str, props: dict[str, Any]) -> dict[str, Any]:
    """Generic, whitelisted property edit for media/image clips.

    position {x,y,width,height}   display box (normalized; may exceed 0-1 to crop-zoom)
    fit cover|contain|stretch     how the picture fills the box
    crop {left,top,right,bottom}  trims the DISPLAY box edges (fractions of the box)
    transform_keys [{t,x,y,w,h}]  animated box (clip-relative t): pans / push-ins
    opacity 0-1 / volume 0-2 / speed 0.25-4 (preserves source, changes duration)
    keep_duration bool           with speed: explicitly trim/extend source instead
    video_enabled bool            keep audio, hide picture
    asset_id (+source_start)      swap the picture, timing unchanged
    source_start                  slide the source window, timing unchanged
    """
    _, _, clip = _find_clip(seq, clip_id)
    if clip is None:
        return {"ok": False, "error": f"clip not found: {clip_id}"}
    if not isinstance(props, dict) or not props:
        return {"ok": False, "error": "props must be a non-empty object"}
    if clip.get('text') is not None and set(props) <= {'text', 'style'}:
        return set_clip(seq, clip_id=clip_id, **props)
    bad = [k for k in props if k not in _PROP_KEYS]
    if bad:
        return {"ok": False, "error": f"unknown props {bad}; allowed: {sorted(_PROP_KEYS)}"}
    if props.get('grade') is not None:
        grade = props['grade']
        if not isinstance(grade, dict) or set(grade) - {'ev', 'contrast', 'sat', 'temp', 'tint'}:
            return {'ok': False, 'error': 'grade uses ev (exposure stops, neutral 0), contrast/sat (multipliers, neutral 1), temp/tint (neutral 0). Include existing values to preserve other adjustments.'}
    if clip.get("asset_id") is None and any(k in props for k in ("position", "fit", "crop",
                                                                   "volume", "speed", "asset_id", "source_start")):
        return {"ok": False, "error": "clip has no asset (use set_region for effects, set_clip for captions)"}
    if clip.get("asset_id") is None and "transform_keys" in props:
        if not clip.get("text"):
            return {"ok": False, "error": "transform_keys requires media or a text clip; use set_region for effects"}
        keys = props['transform_keys']
        if keys is not None and (not isinstance(keys, list) or any(
                not isinstance(k, dict) or any(not isinstance(k.get(n), (int, float)) or not math.isfinite(k[n]) for n in ('t','x','y'))
                or any(n in k and (not isinstance(k[n], (int, float)) or not math.isfinite(k[n]) or k[n] <= 0) for n in ('w','h')) for k in keys)):
            return {"ok": False, "error": "text transform_keys needs finite t,x,y and positive optional w,h"}
    ts, te = _f(clip.get("timeline_start")), _f(clip.get("timeline_end"))
    dur = te - ts
    changed: dict[str, Any] = {}
    if "asset_id" in props:
        a = _asset(assets, str(props["asset_id"]))
        if a is None:
            return {"ok": False, "error": f"asset not found: {props['asset_id']}"}
        if _asset_is_audio(a) != _asset_is_audio(_asset(assets, str(clip.get("asset_id")))):
            return {"ok": False, "error": "cannot swap between audio and visual assets"}
        clip["asset_id"] = str(props["asset_id"])
        if _asset_is_image(a):
            clip["kind"] = "image"
            clip["source_start"], clip["source_end"] = 0.0, round(dur, 3)
        else:
            clip.pop("kind", None)
            ss = _f(props.get("source_start", clip.get("source_start")))
            clip["source_start"] = round(ss, 3)
            clip["source_end"] = round(ss + dur * (_f(clip.get("speed"), 1.0) or 1.0), 3)
        changed["asset_id"] = clip["asset_id"]
    elif "source_start" in props:
        a = _asset(assets, str(clip.get("asset_id")))
        if _asset_is_image(a):
            return {"ok": False, "error": "image clips have no source window"}
        ss = max(0.0, _f(props["source_start"]))
        span = _f(clip.get("source_end")) - _f(clip.get("source_start"))
        adur = _asset_duration(a)
        if adur > 0 and ss + span > adur + 0.05:
            return {"ok": False, "error": f"source window {ss:.2f}+{span:.2f} exceeds asset duration {adur:.2f}"}
        clip["source_start"], clip["source_end"] = round(ss, 3), round(ss + span, 3)
        changed["source_start"] = clip["source_start"]
    if "speed" in props:
        spd = max(0.25, min(4.0, _f(props["speed"], 1.0)))
        a = _asset(assets, str(clip.get("asset_id")))
        if _asset_is_image(a):
            return {"ok": False, "error": "image clips have no speed"}
        ss = _f(clip.get("source_start"))
        adur = _asset_duration(a)
        keep_duration = props.get('keep_duration', False)
        if not isinstance(keep_duration, bool):
            return {"ok": False, "error": "keep_duration must be boolean"}
        se = ss + dur * spd if keep_duration else _f(clip.get('source_end'), ss + dur)
        if adur > 0 and se > adur + 0.05:
            return {"ok": False, "error": f"speed {spd} needs source up to {se:.2f}s but asset is {adur:.2f}s (trim first)"}
        clip["speed"] = round(spd, 4)
        clip.pop("speed_keys", None)
        clip["source_end"] = round(se, 3)
        if not keep_duration:
            clip['timeline_end'] = round(ts + (se-ss)/spd, 3)
            seq['duration'] = max(_f(seq.get('duration')), clip['timeline_end'])
            changed['timeline_end'] = clip['timeline_end']
        if clip.get("link_id"):
            for _, _, c in _all_clips(seq):
                if c is not clip and c.get("link_id") == clip.get("link_id"):
                    c["speed"] = clip["speed"]
                    c.pop("speed_keys", None)
                    c["source_start"], c["source_end"] = clip["source_start"], clip["source_end"]
                    c['timeline_end'] = clip['timeline_end']
        changed["speed"] = clip["speed"]
    if "position" in props:
        pz = props["position"]
        if pz is None:
            clip.pop("position", None)
        elif isinstance(pz, dict):
            clip["position"] = {"x": round(_f(pz.get("x")), 4), "y": round(_f(pz.get("y")), 4),
                                "width": round(max(0.01, _f(pz.get("width"), 1.0)), 4),
                                "height": round(max(0.01, _f(pz.get("height"), 1.0)), 4)}
        else:
            return {"ok": False, "error": "position must be {x,y,width,height} or null"}
        changed["position"] = clip.get("position")
    if "fit" in props:
        if props["fit"] not in {"cover", "contain", "stretch"}:
            return {"ok": False, "error": "fit must be cover|contain|stretch"}
        clip["fit"] = props["fit"]
        changed["fit"] = props["fit"]
    if "crop" in props:
        cr = props["crop"]
        if cr is None:
            clip.pop("crop", None)
        elif isinstance(cr, dict):
            clip["crop"] = {k: round(max(0.0, min(0.95, _f(cr.get(k)))), 4) for k in ("left", "top", "right", "bottom")}
        else:
            return {"ok": False, "error": "crop must be {left,top,right,bottom} or null"}
        changed["crop"] = clip.get("crop")
    if "transform_keys" in props:
        tk = props["transform_keys"]
        if tk is None:
            clip.pop("transform_keys", None)
        else:
            if not isinstance(tk, list):
                return {"ok": False, "error": "transform_keys must be a list of {t,x,y,w,h}"}
            out = []
            for k in tk:
                if not isinstance(k, dict) or "t" not in k:
                    return {"ok": False, "error": "each transform key needs t (and x,y,w,h)"}
                item = {"t": round(max(0.0, min(dur, _f(k["t"]))), 3)}
                for kk in ("x", "y", "w", "h"):
                    if k.get(kk) is not None:
                        item[kk] = round(_f(k[kk]), 4)
                out.append(item)
            out.sort(key=lambda k: k["t"])
            clip["transform_keys"] = out
        changed["transform_keys"] = clip.get("transform_keys")
    if "opacity" in props:
        clip["opacity"] = round(max(0.0, min(1.0, _f(props["opacity"], 1.0))), 3)
        changed["opacity"] = clip["opacity"]
    if "volume" in props:
        clip["volume"] = round(max(0.0, min(2.0, _f(props["volume"], 1.0))), 3)
        changed["volume"] = clip["volume"]
    if "muted" in props:
        clip["volume"] = 0.0 if props["muted"] else max(_f(clip.get("volume"), 1.0), 0.01)
        changed["volume"] = clip["volume"]
    if "video_enabled" in props:
        clip["video_enabled"] = bool(props["video_enabled"])
        changed["video_enabled"] = clip["video_enabled"]
    if "role" in props:
        clip["role"] = str(props["role"])
        changed["role"] = clip["role"]
    if "grade" in props:
        g = props["grade"]
        if g is None:
            clip.pop("grade", None)
        elif isinstance(g, dict):
            clip["grade"] = {k: round(_f(g.get(k)), 3) for k in ("ev", "contrast", "sat", "temp", "tint")
                             if g.get(k) is not None}
        changed["grade"] = clip.get("grade")
    return {"ok": True, "changed": changed}


def _interp_key(ks: list[dict[str, Any]], rel: float) -> dict[str, Any]:
    prev = [k for k in ks if _f(k.get("t")) <= rel]
    nxt = [k for k in ks if _f(k.get("t")) >= rel]
    if not prev:
        return dict(nxt[0], t=rel)
    if not nxt:
        return dict(prev[-1], t=rel)
    a, b = prev[-1], nxt[0]
    ta, tb = _f(a.get("t")), _f(b.get("t"))
    u = 0.0 if tb - ta < 1e-6 else (rel - ta) / (tb - ta)
    out: dict[str, Any] = {"t": rel}
    for kk in ("x", "y", "w", "h"):
        if a.get(kk) is not None and b.get(kk) is not None:
            out[kk] = round(_f(a[kk]) + (_f(b[kk]) - _f(a[kk])) * u, 4)
        elif a.get(kk) is not None:
            out[kk] = a[kk]
        elif b.get(kk) is not None:
            out[kk] = b[kk]
    return out


def _rebase_keys(keys: Any, cut_rel: float) -> tuple[list, list]:
    """Split a clip-relative keyframe list at cut_rel into (left, right) lists so the
    motion is identical before and after the cut."""
    if not isinstance(keys, list) or not keys:
        return [], []
    ks = sorted((k for k in keys if isinstance(k, dict)), key=lambda k: _f(k.get("t")))
    mid = _interp_key(ks, cut_rel)
    left = [dict(k) for k in ks if _f(k.get("t")) < cut_rel - 1e-6] + [dict(mid, t=round(cut_rel, 3))]
    right = [dict(mid, t=0.0)] + [dict(k, t=round(_f(k.get("t")) - cut_rel, 3))
                                  for k in ks if _f(k.get("t")) > cut_rel + 1e-6]
    return left, right


def split_clip(seq: dict[str, Any], *, clip_id: str, at: float) -> dict[str, Any]:
    """Cut a clip (and its A/V twin) into two at timeline time `at`. Source windows,
    region keyframes and transform keyframes are re-based so nothing visibly changes."""
    _, _, clip = _find_clip(seq, clip_id)
    if clip is None:
        return {"ok": False, "error": f"clip not found: {clip_id}"}
    at = _f(at)
    targets = [clip]
    if clip.get("link_id"):
        targets = [c for _, _, c in _all_clips(seq) if c.get("link_id") == clip.get("link_id")]
    for c in targets:
        ts, te = _f(c.get("timeline_start")), _f(c.get("timeline_end"))
        if at - ts < MIN_CLIP or te - at < MIN_CLIP:
            return {"ok": False, "error": f"split point {at:.2f} too close to clip edges ({ts:.2f}-{te:.2f})"}
    new_link = _new_id("lk_ag") if clip.get("link_id") else None
    created: list[str] = []
    for c in targets:
        ts, te = _f(c.get("timeline_start")), _f(c.get("timeline_end"))
        rel = at - ts
        second = json.loads(json.dumps(c))
        second["id"] = _new_id("clip_ag_s")
        if new_link:
            second["link_id"] = new_link
        c["timeline_end"] = round(at, 3)
        second["timeline_start"] = round(at, 3)
        has_src = c.get("source_end") is not None and not c.get("freeze") and str(c.get("kind")) != "image"
        if has_src:
            spd = _f(c.get("speed"), 1.0) or 1.0
            cut_src = _f(c.get("source_start")) + rel * spd
            c["source_end"] = round(cut_src, 3)
            second["source_start"] = round(cut_src, 3)
        elif str(c.get("kind")) == "image":
            c["source_end"] = round(rel, 3)
            second["source_start"], second["source_end"] = 0.0, round(te - at, 3)
        for key_field in ("region_keys", "transform_keys"):
            if isinstance(c.get(key_field), list) and c[key_field]:
                left, right = _rebase_keys(c[key_field], rel)
                c[key_field], second[key_field] = left, right
        for t in _tracks(seq):
            if any(x is c for x in t.get("clips") or []):
                t["clips"].append(second)
                _sorted(t)
        created.append(second["id"])
    _recompute_duration(seq)
    return {"ok": True, "left": [str(c.get("id")) for c in targets], "right": created}


def add_clip(seq: dict[str, Any], assets: dict, *, asset_id: str, timeline_start: float,
             duration: float, source_start: float = 0.0, lane: int | None = None,
             fit: str = "contain", position: dict[str, Any] | None = None, speed: float = 1.0,
             with_audio: bool = False, volume: float = 1.0) -> dict[str, Any]:
    """Video or image clip on a chosen visual lane (or the front-most free one).
    Unlike append_clip (base lane, always with linked audio) this is the general
    layering primitive: B-roll over narration, full-frame stills, PiP."""
    a = _asset(assets, asset_id)
    if a is None:
        return {"ok": False, "error": f"asset not found: {asset_id}"}
    if _asset_is_audio(a):
        return {"ok": False, "error": "audio assets belong on an audio lane; use add_audio"}
    if fit not in {"cover", "contain", "stretch"}:
        return {"ok": False, "error": "fit must be cover|contain|stretch"}
    duration = max(MIN_CLIP, _f(duration))
    ts = max(0.0, _f(timeline_start))
    te = ts + duration
    is_image = _asset_is_image(a)
    spd = max(0.25, min(4.0, _f(speed, 1.0)))
    source_start = max(0.0, _f(source_start))
    if not is_image:
        adur = _asset_duration(a)
        if adur > 0 and source_start + duration * spd > adur + 0.05:
            return {"ok": False, "error": f"source window {source_start:.2f}+{duration * spd:.2f} exceeds asset duration {adur:.2f}"}
    idx, lane_obj = _place_visual(seq, ts, te, lane=lane)
    if idx is None:
        return {"ok": False, "error": str(lane_obj)}
    cid = _new_id("clip_ag_v")
    clip: dict[str, Any] = {"id": cid, "asset_id": asset_id, "fit": fit,
                            "timeline_start": round(ts, 3), "timeline_end": round(te, 3)}
    if is_image:
        clip["kind"] = "image"
        clip["source_start"], clip["source_end"] = 0.0, round(duration, 3)
    else:
        clip["source_start"], clip["source_end"] = round(source_start, 3), round(source_start + duration * spd, 3)
        if spd != 1.0:
            clip["speed"] = round(spd, 4)
        clip["volume"] = 0.0 if not with_audio else round(max(0.0, min(2.0, _f(volume, 1.0))), 3)
        if with_audio:
            link = _new_id("lk_ag")
            clip["link_id"] = link
            atrack = _place_on_lane(seq, "audio", ts, te)
            aclip = {"id": _new_id("clip_ag_a"), "asset_id": asset_id, "link_id": link,
                     "timeline_start": clip["timeline_start"], "timeline_end": clip["timeline_end"],
                     "source_start": clip["source_start"], "source_end": clip["source_end"],
                     "volume": clip["volume"]}
            if spd != 1.0:
                aclip["speed"] = clip["speed"]
            atrack.setdefault("clips", []).append(aclip)
            _sorted(atrack)
    if isinstance(position, dict):
        clip["position"] = {"x": round(_f(position.get("x")), 4), "y": round(_f(position.get("y")), 4),
                            "width": round(max(0.01, _f(position.get("width"), 1.0)), 4),
                            "height": round(max(0.01, _f(position.get("height"), 1.0)), 4)}
    lane_obj.setdefault("clips", []).append(clip)
    _sorted(lane_obj)
    _recompute_duration(seq)
    return {"ok": True, "clip_id": cid, "lane": idx, "timeline_start": clip["timeline_start"],
            "timeline_end": clip["timeline_end"]}


def clip_kind(track: dict[str, Any], c: dict[str, Any], assets: dict) -> str:
    aid = str(c.get("asset_id") or "")
    a = assets.get(aid) or {}
    if c.get("text") is not None:
        return "caption"
    if c.get("region") is not None:
        return f"region:{c.get('style') or 'gaussian'}"
    if _is_audio_lane(track):
        return "audio"
    if c.get("kind") == "image" or _asset_is_image(a):
        return "image"
    return "video"


def clips_at(seq: dict[str, Any], assets: dict, *, t: float) -> list[dict[str, Any]]:
    """Every clip active at timeline time t (all lanes), back-to-front."""
    t = _f(t)
    rows: list[dict[str, Any]] = []
    for ti, track, c in _all_clips(seq):
        if _f(c.get("timeline_start")) <= t < _f(c.get("timeline_end")):
            aid = str(c.get("asset_id") or "")
            a = assets.get(aid) or {}
            rows.append({"clip_id": c.get("id"), "lane": ti, "lane_type": track.get("type"),
                         "kind": clip_kind(track, c, assets),
                         "timeline_start": c.get("timeline_start"), "timeline_end": c.get("timeline_end"),
                         "asset": a.get("filename"), "text": c.get("text"),
                         "region": c.get("region"), "position": c.get("position")})
    return rows


def _recompute_duration(seq: dict[str, Any]) -> None:
    dur = 0.0
    for _, _, c in _all_clips(seq):
        dur = max(dur, _f(c.get("timeline_end")))
    seq["duration"] = round(dur, 3)


# ---------------------------------------------------------------- validation

def validate_sequence(seq: dict[str, Any], assets: dict[str, dict[str, Any]],
                      native_exe: str | None = None, asset_dir: str | None = None) -> list[str]:
    """Whole-draft validation. Python checks data-level rules; when the native
    binary is available it additionally runs the editor's own structural
    invariants (single source of truth for overlap/link rules)."""
    problems: list[str] = []
    seen_ids: set[str] = set()
    links: dict[str, list[dict[str, Any]]] = {}
    for ti, track, c in _all_clips(seq):
        cid = str(c.get("id") or "")
        kind = str(track.get("type") or "")
        if not cid:
            problems.append(f"track{ti}: clip without id")
            continue
        if cid in seen_ids:
            problems.append(f"duplicate clip id: {cid}")
        seen_ids.add(cid)
        ts, te = _f(c.get("timeline_start")), _f(c.get("timeline_end"))
        if ts < -1e-6:
            problems.append(f"{cid}: negative timeline_start {ts}")
        if te - ts < MIN_CLIP - 1e-6:
            problems.append(f"{cid}: zero/negative length ({ts}-{te})")
        if c.get("link_id"):
            links.setdefault(str(c.get("link_id")), []).append(c)
        aid = c.get("asset_id")
        if aid is not None:
            a = _asset(assets, str(aid))
            if a is None:
                problems.append(f"{cid}: unknown asset {aid}")
            elif not c.get("freeze") and str(c.get("kind")) != "image" and not _asset_is_image(a):
                ss, se = _f(c.get("source_start")), _f(c.get("source_end"))
                if c.get("source_end") is not None:
                    if se <= ss + 1e-6:
                        pass  # implicit freeze convention — allowed
                    else:
                        adur = _asset_duration(a)
                        if adur > 0 and se > adur + 0.05:
                            problems.append(f"{cid}: source_end {se:.2f} beyond asset duration {adur:.2f}")
                        spd = _f(c.get("speed"), 1.0) or 1.0
                        if not c.get("speed_keys") and abs((te - ts) - (se - ss) / spd) > 0.05:
                            problems.append(f"{cid}: timeline span {te - ts:.2f}s != source span {se - ss:.2f}s"
                                            + (f" / speed {spd:.2f}" if spd != 1.0 else ""))
    # per-lane overlap
    for ti, track in enumerate(_tracks(seq)):
        clips = sorted(track.get("clips") or [], key=lambda c: _f(c.get("timeline_start")))
        for a, b in zip(clips, clips[1:]):
            if _f(a.get("timeline_end")) > _f(b.get("timeline_start")) + 1e-3:
                problems.append(
                    f"lane {ti} ({track.get('type')}): overlap {a.get('id')} / {b.get('id')} at {b.get('timeline_start')}"
                )
    # A/V links stay in sync
    for lid, group in links.items():
        starts = {round(_f(c.get("timeline_start")), 3) for c in group}
        ends = {round(_f(c.get("timeline_end")), 3) for c in group}
        if len(starts) > 1 or len(ends) > 1:
            problems.append(f"link {lid}: A/V clips out of sync ({sorted(starts)} / {sorted(ends)})")
    # native structural check (editor's own invariants) when available
    exe = native_exe or os.environ.get("NATIVE_UI_EXE")
    if not exe:
        from app.services.timeline_context import native_exe_default
        exe = native_exe_default()
    if exe and Path(exe).exists() and asset_dir:
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
                json.dump([{"title": "draft-validate", "format": seq.get("format") or "9:16", "timeline": {"format": seq.get("format") or "9:16", "sequence": seq}}], f, ensure_ascii=False)
                tmp = f.name
            r = subprocess.run(
                [exe, tmp, asset_dir, "--validate-contents"],
                capture_output=True, text=True, timeout=60,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            out = (r.stdout or "").strip().splitlines()
            verdict = json.loads(out[-1]) if out else {}
            for p in verdict.get("problems") or []:
                problems.append(f"native: {p}")
        except Exception as exc:  # noqa: BLE001 — native check is best-effort extra
            problems.append(f"native validator unavailable: {exc}")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return problems
