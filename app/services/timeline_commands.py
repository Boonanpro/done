"""Timeline command layer — the ONLY way the agent mutates a draft.

Every command takes the draft's sequence dict, applies one validated operation
and returns {"ok": bool, "error": str|None, ...}. The LLM never writes raw
JSON: parameters are narrow, every write is clamped/checked here, and
validate_sequence() re-checks the WHOLE draft before commit (per-track overlap
rules, asset existence/duration, id uniqueness, A/V link integrity).

Track semantics:
  video   — the base lane: clips may not overlap each other
  overlay — PiP / image overlays: may not overlap within the same lane
  effect  — region blur/mosaic etc.: may not overlap within the same lane
  caption — may not overlap within the same lane
  audio   — may not overlap within the same lane
Anything may coexist ACROSS lanes (layering is the point of lanes).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
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
    t = {"type": kind, "clips": []}
    _tracks(seq).append(t)
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


def _place_on_lane(seq: dict[str, Any], kind: str, ts: float, te: float) -> dict[str, Any]:
    """First lane of `kind` where [ts,te) is free; appends a new lane when none is."""
    for t in _tracks(seq):
        if t.get("type") == kind and _span_free(t, ts, te):
            return t
    t = {"type": kind, "clips": []}
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


_CAPTION_STYLE_KEYS = {"font", "fontSize", "color", "outlineColor", "outlineWidth", "x", "y"}


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
            out[k] = max(0.3, min(3.0, fv))
        else:
            out[k] = v
    return out or None


def add_caption(seq: dict[str, Any], *, text: str, timeline_start: float, timeline_end: float,
                style: dict[str, Any] | None = None) -> dict[str, Any]:
    text = str(text or "").strip()
    if not text:
        return {"ok": False, "error": "empty text"}
    ts, te = _f(timeline_start), _f(timeline_end)
    if te - ts < MIN_CLIP:
        return {"ok": False, "error": "caption span too short"}
    lane = _place_on_lane(seq, "caption", ts, te)
    cid = _new_id("clip_ag_c")
    lane.setdefault("clips", []).append({
        "id": cid, "track": "caption", "text": text,
        "timeline_start": round(ts, 3), "timeline_end": round(te, 3),
        **({"style": _sanitize_caption_style(style)} if _sanitize_caption_style(style) else {}),
    })
    _sorted(lane)
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
                        if abs((te - ts) - (se - ss)) > 0.05:
                            problems.append(f"{cid}: timeline span {te - ts:.2f}s != source span {se - ss:.2f}s")
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
                json.dump([{"title": "draft-validate", "timeline": {"sequence": seq}}], f, ensure_ascii=False)
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
