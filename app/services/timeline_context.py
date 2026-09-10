"""Perception for the timeline agent: what the video SAYS (transcript mapped onto
timeline time) and what it SHOWS (a composited frame of the current draft rendered
by the native engine — cuts, PiP, captions, blur, keyframes, image overlays all
included; the same pixels the editor preview and the export produce)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def probe_timeline_audio(sequence, asset_dir, t0, t1):
    """Native decoder spot check, not a listening/quality verdict or full export."""
    import math
    if not all(math.isfinite(t) for t in (t0, t1)) or t0 < 0 or t1 <= t0:
        return {'ok': False, 'error': 'Use a finite positive timeline range.'}
    with tempfile.TemporaryDirectory(prefix='dan-audio-probe-') as folder:
        path = Path(folder) / 'contents.json'
        path.write_text(json.dumps([{'id': 'probe', 'timeline': {'sequence': sequence}}]), encoding='utf-8')
        result = subprocess.run([native_exe_default(), str(path), str(asset_dir),
            '--probe-timeline-audio', str(t0), str(t1)], capture_output=True, text=True,
            timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return {'ok': result.returncode == 0, 'evidence': result.stdout.strip(),
            'error': result.stderr[-1000:] if result.returncode else None,
            'coverage': 'Samples up to 0.5 seconds at the start of each overlapping audio clip in the requested range. Checks native decoding and nonzero signal, not speech quality, synchronization, or the entire range.'}

_NATIVE_DIR = r"D:\done-desktop\scripts\poc\production_desktop\native_ui\target\release"


def native_exe_default() -> str:
    """The SAME build the user's editor runs (deployed to ~/.done/bin) so frames the
    agent sees, validation and export all agree with the preview. Order:
    env DAN_NATIVE_UI_EXE → .done/bin/native_ui_headless.exe (deploy copies it so it
    can be replaced while the editor holds native_ui.exe open) → .done/bin/native_ui.exe
    (a running exe can still be executed a second time) → this checkout's release build
    → the old done-desktop worktree (legacy fallback)."""
    env = os.environ.get("DAN_NATIVE_UI_EXE") or ""
    home_bin = os.path.join(os.path.expanduser("~"), ".done", "bin")
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "scripts", "poc", "production_desktop", "native_ui", "target", "release")
    for cand in (env,
                 os.path.join(home_bin, "native_ui_headless.exe"),
                 os.path.join(home_bin, "native_ui.exe"),
                 os.path.join(here, "native_ui.exe"),
                 os.path.join(_NATIVE_DIR, "native_ui_headless.exe"),
                 os.path.join(_NATIVE_DIR, "native_ui.exe")):
        if cand and os.path.exists(cand):
            return cand
    return os.path.join(_NATIVE_DIR, "native_ui.exe")


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def timeline_transcript(sequence: dict[str, Any], analyses: dict[str, dict[str, Any]],
                        t0: float | None = None, t1: float | None = None) -> list[dict[str, Any]]:
    """Map per-asset Whisper words onto TIMELINE time through the base/audio clips.
    Returns [{t0, t1, text, clip_id}] sorted by time, optionally windowed."""
    def _flat_words(ana: dict[str, Any]) -> list[dict[str, Any]]:
        # audio_analysis format: {"segments": [{"words": [{word,start,end}]}]}
        if not isinstance(ana, dict):
            return []
        if isinstance(ana.get("words"), list):
            return ana["words"]
        out: list[dict[str, Any]] = []
        for seg in ana.get("segments") or []:
            if isinstance(seg, dict):
                out.extend(w for w in (seg.get("words") or []) if isinstance(w, dict))
        return out

    rows: list[dict[str, Any]] = []
    for track in sequence.get("tracks") or []:
        if track.get("type") not in {"video", "audio"}:
            continue
        prefer_audio = track.get("type") == "audio"
        for clip in track.get("clips") or []:
            aid = str(clip.get("asset_id") or "")
            if not aid or clip.get("freeze"):
                continue
            words = _flat_words(analyses.get(aid) or {})
            if not words:
                continue
            ts = _f(clip.get("timeline_start"))
            te = _f(clip.get("timeline_end"))
            ss = _f(clip.get("source_start"))
            se = _f(clip.get("source_end"), ss + (te - ts))
            if se <= ss:
                continue
            buf: list[str] = []
            w0 = w1 = None
            for w in words:
                wt = _f(w.get("start") if isinstance(w, dict) else None, -1)
                we = _f(w.get("end") if isinstance(w, dict) else None, wt)
                txt = str(w.get("word") or w.get("text") or "") if isinstance(w, dict) else ""
                if not txt or wt < ss - 0.05 or wt > se + 0.05:
                    continue
                tt0 = ts + (wt - ss)
                tt1 = ts + (we - ss)
                if w0 is None:
                    w0 = tt0
                w1 = tt1
                buf.append(txt)
            if buf and (not prefer_audio or track.get("type") == "audio"):
                rows.append({
                    "t0": round(w0 or ts, 2), "t1": round(w1 or te, 2),
                    "clip_id": str(clip.get("id") or ""), "lane": track.get("type"),
                    "text": "".join(buf),
                })
    # audio lane duplicates the linked video's words — prefer audio rows, drop video
    # rows whose span an audio row already covers
    audio_rows = [r for r in rows if r["lane"] == "audio"]
    video_rows = [r for r in rows if r["lane"] != "audio"]
    kept = audio_rows + [
        v for v in video_rows
        if not any(abs(a["t0"] - v["t0"]) < 0.2 and abs(a["t1"] - v["t1"]) < 0.2 for a in audio_rows)
    ]
    kept.sort(key=lambda r: r["t0"])
    if t0 is not None or t1 is not None:
        lo = t0 if t0 is not None else -1e9
        hi = t1 if t1 is not None else 1e9
        kept = [r for r in kept if r["t1"] >= lo and r["t0"] <= hi]
    for r in kept:
        r.pop("lane", None)
    return kept


def render_timeline_frames(sequence: dict[str, Any], asset_dir: str, ts: list[float],
                           out_dir: str | None = None) -> dict[str, Any]:
    """Composite the DRAFT at several timeline times in ONE native engine spawn
    (engine setup + decoder opens amortize across the batch — a batch of 5 costs
    little more than a single frame). Returns {ok, paths|error} with paths in the
    same order as ts."""
    exe = os.environ.get("NATIVE_UI_EXE") or native_exe_default()
    if not Path(exe).exists():
        return {"ok": False, "error": f"native engine not found: {exe}"}
    ts = [float(t) for t in ts][:12] or [0.0]
    odir = Path(out_dir) if out_dir else Path(tempfile.gettempdir())
    odir.mkdir(parents=True, exist_ok=True)
    stem = odir / f"frame_{int(ts[0] * 1000)}_{int(time.time() * 1000) % 100000}"
    png = Path(f"{stem}.png")
    tspec = ",".join(f"{t:.3f}" for t in ts)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        fmt = str(sequence.get("format") or "9:16")
        # the native canvas follows timeline.format; without it every dump is 9:16 and
        # 16:9 timelines come back letterboxed with mis-placed regions (2026-09-04)
        json.dump([{"title": "draft-frame", "format": fmt, "timeline": {"format": fmt, "sequence": sequence}}], f, ensure_ascii=False)
        tmp = f.name
    try:
        from app.api.production_asset_routes import _ensure_native_caption_cache, _native_export_canvas
        missing = _ensure_native_caption_cache('', sequence, _native_export_canvas(sequence.get('format')), asset_dir=asset_dir)
        if missing:
            return {'ok': False, 'error': '字幕を含む検品画像を作れませんでした。字幕キャッシュの生成に失敗しました。'}
        r = subprocess.run(
            [exe, tmp, asset_dir, "--dump-frame", tspec, str(png)],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180 + 30 * len(ts),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=dict(os.environ, NATIVE_DUMP_ALL_CAPTIONS='1'),
        )
        paths = [png] if len(ts) == 1 else [Path(f"{stem}.{k}.png") for k in range(len(ts))]
        if all(p.exists() and p.stat().st_size > 0 for p in paths):
            # The same native compositor now owns every caption here, including
            # animation and lane order. A second browser overlay would duplicate text.
            return {"ok": True, "paths": [str(p) for p in paths]}
        return {"ok": False, "error": (r.stdout or "")[-400:] + (r.stderr or "")[-400:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "frame render timeout"}
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _composite_captions(frame_png: Path, sequence: dict[str, Any], t: float,
                        asset_dir: str) -> None:
    """Rasterize each caption active at t via the SAME /caption-frame route the
    editor preview uses (full canvas, position/style/karaoke included) and
    alpha-composite it onto the dumped frame. Cached per (text,style,words[,t])."""
    active: list[dict[str, Any]] = []
    for track in sequence.get("tracks") or []:
        if track.get("type") == "audio":
            continue
        for c in track.get("clips") or []:
            if c.get("style") == "note" or not str(c.get("text") or "").strip():
                continue
            if _f(c.get("timeline_start")) <= t < _f(c.get("timeline_end"), -1):
                active.append(c)
    if not active:
        return
    import hashlib

    from PIL import Image

    cache = Path(asset_dir) / "caption-cache"
    cache.mkdir(parents=True, exist_ok=True)
    frame = Image.open(frame_png).convert("RGBA")
    out_w, out_h = frame.size
    for c in active:
        text = str(c.get("text") or "").strip()
        design = c.get("style") if isinstance(c.get("style"), dict) else {}
        words = c.get("words") if isinstance(c.get("words"), list) else []
        key_obj: dict[str, Any] = {"w": out_w, "h": out_h, "t": text, "d": design, "words": words}
        if words:
            # karaoke highlight depends on the exact time — key per 0.1s step
            key_obj["at"] = round(t, 1)
        key = hashlib.sha1(json.dumps(key_obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
        png = cache / f"agent_{key}.png"
        if not (png.exists() and png.stat().st_size > 0):
            spec = cache / f"_spec_frame_{key}.json"
            item: dict[str, Any] = {"png": str(png), "text": text, "time": float(t),
                                    "design": design, "words": words}
            if words:
                item["start"] = _f(c.get("timeline_start"))
                item["end"] = _f(c.get("timeline_end"))
            spec.write_text(json.dumps({
                "outW": out_w, "outH": out_h,
                "web_base": os.environ.get("DAN_CAPTION_RENDER_BASE", "http://127.0.0.1:3000"),
                "items": [item],
            }, ensure_ascii=False), encoding="utf-8")
            try:
                script = Path(__file__).resolve().parents[2] / "scripts" / "render_caption_pngs.py"
                subprocess.run([sys.executable, str(script), str(spec)], capture_output=True,
                               stdin=subprocess.DEVNULL, timeout=120,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            finally:
                try:
                    spec.unlink()
                except OSError:
                    pass
        if not (png.exists() and png.stat().st_size > 0):
            raise RuntimeError('Caption render did not produce an image')
        if frame is None:
            frame = Image.open(frame_png).convert("RGBA")
        overlay = Image.open(png).convert("RGBA")
        if overlay.size != frame.size:
            overlay = overlay.resize(frame.size, Image.LANCZOS)
        frame.alpha_composite(overlay)
    if frame is not None:
        frame.save(frame_png)


def render_timeline_frame(sequence: dict[str, Any], asset_dir: str, t: float,
                          out_dir: str | None = None) -> dict[str, Any]:
    """Composite the DRAFT at timeline time t via the native engine; returns
    {ok, path|error}. The PNG is written into out_dir (default: temp)."""
    res = render_timeline_frames(sequence, asset_dir, [t], out_dir=out_dir)
    if res.get("ok"):
        return {"ok": True, "path": res["paths"][0]}
    return res


def timeline_outline(sequence: dict[str, Any], assets: dict[str, dict[str, Any]]) -> str:
    """Compact human/LLM-readable structure of the timeline (per lane, per clip).
    Lanes are layers: index 0 = backmost, higher lanes draw in front; audio lanes are
    the only lane-level distinction. Clip kind comes from the clip's own fields."""
    lines: list[str] = [f"duration: {_f(sequence.get('duration')):.2f}s / format: {sequence.get('format') or '9:16'}"]
    lines.append("lanes are layers: lane 0 = back, higher = front; an effect/overlay affects only lanes BELOW it")
    for ti, track in enumerate(sequence.get("tracks") or []):
        clips = track.get("clips") or []
        kind = str(track.get("type") or "")
        label = "audio" if kind == "audio" else ("caption" if kind == "caption" else "visual")
        flags = "".join(f" {k}" for k in ("locked", "hidden", "muted") if track.get(k))
        lines.append(f"[lane {ti}: {label}{flags}] {len(clips)} clips")
        for c in sorted(clips, key=lambda x: _f(x.get("timeline_start"))):
            aid = str(c.get("asset_id") or "")
            a = assets.get(aid) or {}
            ts, te = _f(c.get("timeline_start")), _f(c.get("timeline_end"))
            if c.get("text") is not None:
                what = f'caption text="{str(c.get("text"))[:40]}"'
            elif c.get("region") is not None:
                rg = c.get("region") or {}
                st = c.get("style") or "gaussian"
                what = (f"{st} region x={_f(rg.get('x')):.3f} y={_f(rg.get('y')):.3f} "
                        f"w={_f(rg.get('width')):.3f} h={_f(rg.get('height')):.3f}")
                if c.get("effect_color"):
                    what += f" color={c.get('effect_color')}"
                if c.get("region_keys"):
                    what += f" keys={len(c.get('region_keys'))}"
                if c.get("blur_track"):
                    what += " tracked"
            else:
                what = str(a.get("filename") or "?")
                if c.get("freeze"):
                    what += " freeze"
                elif c.get("kind") == "image" or (a and str(a.get("kind")) == "image"):
                    what += " image"
                else:
                    what += f" src={_f(c.get('source_start')):.2f}-{_f(c.get('source_end')):.2f}"
                    spd = _f(c.get("speed"), 1.0)
                    if abs(spd - 1.0) > 1e-3:
                        what += f" speed={spd:g}"
                if kind != "audio":
                    pz = c.get("position")
                    if isinstance(pz, dict):
                        what += (f" box=({_f(pz.get('x')):.2f},{_f(pz.get('y')):.2f},"
                                 f"{_f(pz.get('width')):.2f}x{_f(pz.get('height')):.2f})")
                    if c.get("crop"):
                        what += " cropped"
                    if c.get("transform_keys"):
                        what += f" moves({len(c.get('transform_keys'))}keys)"
                    if c.get("fit") and c.get("fit") != "cover":
                        what += f" fit={c.get('fit')}"
                    if c.get("video_enabled") is False:
                        what += " picture-off"
                else:
                    vol = _f(c.get("volume"), 1.0)
                    what += f" vol={vol:g}"
                    if c.get("role"):
                        what += f" role={c.get('role')}"
                if c.get("link_id"):
                    what += " linked-av"
            aid_tag = f" asset_id={aid}" if aid else ""
            lines.append(f"  {c.get('id')}: {ts:.2f}-{te:.2f} {what}{aid_tag}")
    return "\n".join(lines)
