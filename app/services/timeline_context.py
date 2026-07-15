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

_NATIVE_DIR = r"D:\done-desktop\scripts\poc\production_desktop\native_ui\target\release"


def native_exe_default() -> str:
    """Prefer the headless copy: the editor holds native_ui.exe open (so deploys
    can't replace it while a session runs), but native_ui_headless.exe is only used
    by short-lived dump/validate processes and can always be updated."""
    headless = os.path.join(_NATIVE_DIR, "native_ui_headless.exe")
    return headless if os.path.exists(headless) else os.path.join(_NATIVE_DIR, "native_ui.exe")


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
        json.dump([{"title": "draft-frame", "timeline": {"sequence": sequence}}], f, ensure_ascii=False)
        tmp = f.name
    try:
        r = subprocess.run(
            [exe, tmp, asset_dir, "--dump-frame", tspec, str(png)],
            capture_output=True, text=True, timeout=180 + 30 * len(ts),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        paths = [png] if len(ts) == 1 else [Path(f"{stem}.{k}.png") for k in range(len(ts))]
        if all(p.exists() and p.stat().st_size > 0 for p in paths):
            # ネイティブ合成はテロップを描かない（プレビュー=Webレイヤー担当、
            # 書き出し=ffmpeg担当）。ここで焼き込まないとエージェントの目に
            # テロップが永遠に映らず、「表示されない」と誤解して作業が迷走する
            # （実ジョブ2本がこれで数十分溶けた）
            for t, p in zip(ts, paths):
                try:
                    _composite_captions(p, sequence, t, asset_dir)
                except Exception:  # noqa: BLE001 — テロップ焼き込み失敗でフレーム自体は殺さない
                    logger.exception("caption composite failed for t=%s", t)
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
        if track.get("type") != "caption":
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
    frame = None
    for c in active:
        text = str(c.get("text") or "").strip()
        design = c.get("style") if isinstance(c.get("style"), dict) else {}
        words = c.get("words") if isinstance(c.get("words"), list) else []
        key_obj: dict[str, Any] = {"w": 1080, "h": 1920, "t": text, "d": design, "words": words}
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
                "outW": 1080, "outH": 1920,
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
            continue
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
    """Compact human/LLM-readable structure of the timeline (per lane, per clip)."""
    lines: list[str] = [f"duration: {_f(sequence.get('duration')):.2f}s / format: {sequence.get('format') or '9:16'}"]
    for ti, track in enumerate(sequence.get("tracks") or []):
        clips = track.get("clips") or []
        lines.append(f"[lane {ti}: {track.get('type')}] {len(clips)} clips")
        for c in sorted(clips, key=lambda x: _f(x.get("timeline_start"))):
            aid = str(c.get("asset_id") or "")
            a = assets.get(aid) or {}
            what = a.get("filename") or ("caption" if c.get("text") is not None else "effect")
            extra = ""
            if c.get("text") is not None:
                extra = f' text="{str(c.get("text"))[:40]}"'
            elif c.get("region") is not None:
                extra = " region-effect(blur/mosaic)"
            elif c.get("freeze"):
                extra = " freeze"
            elif c.get("kind") == "image" or (a and str(a.get("kind")) == "image"):
                extra = " image"
            aid_tag = f" asset_id={aid}" if aid else ""
            lines.append(
                f"  {c.get('id')}: {_f(c.get('timeline_start')):.2f}-{_f(c.get('timeline_end')):.2f} {what}{extra}{aid_tag}"
            )
    return "\n".join(lines)
