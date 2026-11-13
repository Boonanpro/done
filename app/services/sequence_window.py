"""Part of a timeline through the FFmpeg export (the path the Mac uses, where the native
compositor is a Windows build). A window of whole frames is cut out of the sequence —
every clip trimmed to it with its source, keyframes and caption animation re-based — so a
frame or a range costs only its own frames instead of the whole video."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

_EPS = 1e-6


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def trim_sequence(sequence: dict[str, Any], assets: dict[str, dict[str, Any]],
                  k0: int, k1: int, fps: float) -> dict[str, Any]:
    """Visual lanes of frames [k0, k1), moved so frame k0 is time 0. Audio lanes are emptied
    (sound is mixed from the original sequence). A clip owns frame k when the frame's centre
    is inside it — the export's rule — so the cut keeps every frame's picture."""
    from app.api import production_asset_routes as par
    from app.services.timeline_commands import _rebase_keys

    tracks = []
    for track in sequence.get("tracks") or []:
        if not isinstance(track, dict):
            continue
        clips = []
        if track.get("type") != "audio":
            for clip in track.get("clips") or []:
                if not isinstance(clip, dict):
                    continue
                a, b = _f(clip.get("timeline_start")), _f(clip.get("timeline_end"))
                fa, fb = par._frame_index(a, fps), par._frame_index(b, fps)
                na, nb = max(fa, k0), min(fb, k1)
                if nb <= na:
                    continue
                cut = json.loads(json.dumps(clip))
                cut["timeline_start"] = (na - k0) / fps
                cut["timeline_end"] = (nb - k0) / fps
                rel = (na - fa) / fps
                if str(clip.get("text") or "").strip() and (na > fa or nb < fb):
                    # The caption keeps its own start/end so an animation is in the same phase,
                    # and its drawings stay on the export's grid (frame i drawn at
                    # a + (i + 0.5) / F, shown from a + i / F); only the drawn part changes.
                    grid = par._CAPTION_ANIM_FPS
                    i0 = max(0, math.floor((k0 / fps - a + 0.5 / fps) * grid + _EPS))
                    cut["_caption_span"] = [a, b]
                    cut["_caption_sample"] = [a + i0 / grid, min(b, k1 / fps)]
                    cut["_caption_at"] = a + i0 / grid - k0 / fps
                if na > fa and isinstance(clip.get("scene"), dict):
                    # an editable scene cut by the window carries on from where it was
                    cut["scene_offset"] = _f(clip.get("scene_offset")) + rel
                if na > fa:
                    _shift_source(cut, clip, assets.get(str(clip.get("asset_id") or "")), rel, fps)
                    for field in ("transform_keys", "region_keys"):
                        if isinstance(clip.get(field), list) and clip[field]:
                            cut[field] = _rebase_keys(clip[field], rel)[1]
                clips.append(cut)
        tracks.append({**track, "clips": clips})
    return {**sequence, "tracks": tracks, "duration": (k1 - k0) / fps}


def _shift_source(cut: dict[str, Any], clip: dict[str, Any], asset: dict[str, Any] | None,
                  rel: float, fps: float) -> None:
    """Start the clip `rel` seconds later in its source (the export plays sources at 1x)."""
    from app.api import production_asset_routes as par

    if not asset or asset.get("kind") != "video" or par._asset_is_image_kind(asset):
        return
    meta = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
    ss, se, _dur, _src, freeze = par._clip_source_range(clip, meta)
    if freeze:
        return
    popout = next((e for e in (clip.get("effects") or [])
                   if isinstance(e, dict) and e.get("type") == "popout"), None)
    if popout is not None:
        # The cached cut-out was made for the whole clip: keep pointing at the same one.
        params = dict(popout.get("params") or {})
        if not isinstance(params.get("bake_start"), (int, float)):
            params["bake_start"], params["bake_end"] = par._popout_bake_range(asset, ss, se)
        cut["effects"] = [dict(e, params=params) if e is popout else e
                          for e in (clip.get("effects") or [])]
    start = ss + rel
    if start >= se - 0.5 / fps:
        # past the end of a source shorter than its slot: the export holds the last frame
        cut["source_start"] = cut["source_end"] = round(max(ss, se - 1 / fps), 6)
    else:
        cut["source_start"] = round(start, 6)
        cut["source_end"] = round(se, 6)


def _covers(sequence: dict[str, Any], k0: int, k1: int, fps: float) -> bool:
    """The export concatenates the bottom lane, so the window needs it without gaps."""
    from app.api import production_asset_routes as par

    base, _ = par._sequence_z_items(sequence)
    at = 0.0
    for clip in base:
        if abs(_f(clip.get("timeline_start")) - at) > 0.5 / fps:
            return False
        at = _f(clip.get("timeline_end"))
    return abs(at - (k1 - k0) / fps) <= 0.5 / fps


def frame_of(t: float, fps: float) -> int:
    """The frame on screen at time t."""
    return max(0, math.floor(t * fps + _EPS))


def render_frames(room_id: str, sequence: dict[str, Any], ts: list[float],
                  out_dir: Path) -> dict[str, Any]:
    """PNG of the finished picture at each time (cuts, overlays, captions, blur regions).
    {ok, paths} in the order of ts, or {ok: False, error}."""
    from app.api import production_asset_routes as par

    fps = par._sequence_frame_rate(sequence)
    assets = par._assets_by_id(room_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = uuid.uuid4().hex[:6]

    def one(i: int) -> tuple[str | None, str | None]:
        k = frame_of(ts[i], fps)
        window = trim_sequence(sequence, assets, k, k + 1, fps)
        if not _covers(window, k, k + 1, fps):
            return None, f"{ts[i]:.2f}秒は一番下のレーンに映像がありません"
        png = out_dir / f"frame_{int(ts[i] * 1000)}_{stamp}_{i}.png"
        # the pass leaves its filtergraph and key frames next to its output: draw in a scratch folder
        with tempfile.TemporaryDirectory(prefix="dan-frame-") as work:
            drawn_png = Path(work) / "frame.png"
            try:
                drawn = par._render_sequence_pass(room_id, f"frame{i}", {"timeline": {"sequence": window}},
                                                  Path(work), drawn_png, video_only=True, still=True)
            except subprocess.CalledProcessError as exc:
                return None, f"{ts[i]:.2f}秒の絵を描けませんでした: {(exc.stderr or '')[-400:]}"
            if not drawn or not drawn_png.exists() or drawn_png.stat().st_size == 0:
                return None, f"{ts[i]:.2f}秒の絵を描けませんでした"
            shutil.move(str(drawn_png), png)
        return str(png), None

    with ThreadPoolExecutor(max_workers=max(1, min(4, len(ts)))) as pool:
        results = list(pool.map(one, range(len(ts))))
    problems = [err for _, err in results if err]
    if problems:
        return {"ok": False, "error": " / ".join(problems)}
    return {"ok": True, "paths": [path for path, _ in results]}


def render_ranges(room_id: str, job_id: str, instruction: dict[str, Any], job_dir: Path,
                  out_path: Path, ranges: list[tuple[float, float]]) -> tuple[int, int, int]:
    """The given timeline ranges, picture and sound, joined into one file in order."""
    from app.api import production_asset_routes as par

    timeline = instruction.get("timeline") if isinstance(instruction.get("timeline"), dict) else {}
    sequence = timeline["sequence"]
    fps = par._sequence_frame_rate(sequence)
    assets = par._assets_by_id(room_id)
    sound = par._export_audio_clips(sequence, assets)
    parts = job_dir / f"{job_id}_ranges"
    parts.mkdir(parents=True, exist_ok=True)
    decoded = par._decoded_audio_sources(sound, assets, parts) if sound else {}
    exe = par._ffmpeg()
    drawn_total, size = 0, (0, 0)
    try:
        for i, (r0, r1) in enumerate(ranges):
            k0, k1 = par._frame_index(r0, fps), par._frame_index(r1, fps)
            if k1 <= k0:
                continue
            window = trim_sequence(sequence, assets, k0, k1, fps)
            if not _covers(window, k0, k1, fps):
                raise RuntimeError(f"{r0:.2f}〜{r1:.2f}秒は一番下のレーンに映像が無い所があります")
            anns = []
            for ann in (timeline.get("annotations") or []):
                if not isinstance(ann, dict):
                    continue
                st = _f(ann.get("start"))
                en = _f(ann.get("end"), st + 0.5)
                if en > k0 / fps and st < k1 / fps:
                    anns.append({**ann, "start": st - k0 / fps, "end": en - k0 / fps})
            sub = {**instruction, "timeline": {**timeline, "sequence": window, "annotations": anns}}
            video = parts / f"v{i:03d}.mp4"
            # captions are drawn into per-pass numbered files: one folder per range
            scratch = parts / f"w{i:03d}"
            scratch.mkdir()
            drawn = par._render_sequence_pass(room_id, job_id, sub, scratch, video, video_only=True, segment=True)
            if not drawn:
                raise RuntimeError("範囲の書き出しで描く物が見つかりませんでした")
            drawn_total += drawn[0]
            size = drawn[1:]
            cmd = [exe, "-y", "-v", "error", "-i", str(video)]
            if sound:
                wav = parts / f"a{i:03d}.wav"
                par._render_audio_window(room_id, sequence, k0 / fps, k1 / fps, wav, decoded)
                cmd += ["-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
            else:
                cmd += ["-c", "copy"]
            subprocess.run([*cmd, str(parts / f"p{i:03d}.mp4")], stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, text=True, check=True)
        pieces = sorted(parts.glob("p*.mp4"))
        if not pieces:
            raise RuntimeError("書き出す範囲がありません")
        listing = parts / "pieces.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in pieces), encoding="utf-8")
        subprocess.run([exe, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                        "-c", "copy", "-movflags", "+faststart", str(out_path)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=True)
    finally:
        shutil.rmtree(parts, ignore_errors=True)
    return drawn_total, size[0], size[1]


def probe_audio(room_id: str, sequence: dict[str, Any], t0: float, t1: float) -> dict[str, Any]:
    """What is heard over [t0, t1): mixed like the export, then the level of each overlapping
    sound clip's first half second inside the range and of the whole range."""
    import array

    from app.api import production_asset_routes as par

    assets = par._assets_by_id(room_id)
    sr = 48000
    rows = []
    with tempfile.TemporaryDirectory(prefix="dan-audio-probe-") as folder:
        wav = Path(folder) / "mix.wav"
        par._render_audio_window(room_id, sequence, t0, t1, wav)
        raw = subprocess.run([par._ffmpeg(), "-v", "error", "-i", str(wav), "-ac", "1", "-f", "s16le", "-"],
                             capture_output=True, check=True).stdout
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) // 2 * 2])

    def level(a: float, b: float) -> str:
        part = samples[max(0, round((a - t0) * sr)): max(0, round((b - t0) * sr))]
        if not part:
            return "no samples"
        peak = max(abs(v) for v in part)
        rms = math.sqrt(sum(v * v for v in part) / len(part))
        db = 20 * math.log10(rms / 32768) if rms > 0 else float("-inf")
        return f"peak={peak / 32768:.3f} rms={db:.1f}dBFS" + (" SILENT" if peak == 0 else "")

    for clip in par._export_audio_clips(sequence, assets):
        a, b = _f(clip.get("timeline_start")), _f(clip.get("timeline_end"))
        if b <= t0 or a >= t1:
            continue
        s = max(a, t0)
        rows.append(f"clip {clip.get('id')} {s:.2f}-{min(b, s + 0.5, t1):.2f}s: {level(s, min(b, s + 0.5, t1))}")
    rows.append(f"mix {t0:.2f}-{t1:.2f}s: {level(t0, t1)}")
    return {"ok": True, "evidence": "\n".join(rows),
            "coverage": "Mixed like the export over the requested range. Levels the first 0.5 seconds of each "
                        "overlapping sound clip inside the range and the whole mix. Checks decoding and nonzero "
                        "signal, not speech quality or synchronization."}
