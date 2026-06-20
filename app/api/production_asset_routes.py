from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import subprocess
import uuid
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.api.chat_artifact_routes import get_current_user
from app.services.auth_service import TokenData


router = APIRouter(prefix="/production-assets", tags=["production-assets"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UPLOADS_DIR = PROJECT_ROOT / "uploads"
ASSET_ROOT = UPLOADS_DIR / "production-assets"
ASSET_ROOT.mkdir(parents=True, exist_ok=True)

VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


class ProductionAsset(BaseModel):
    id: str
    room_id: str
    kind: Literal["video", "image", "audio", "file"]
    source_type: Literal["local_path", "nas_path", "cloud_url", "upload", "generated"]
    original_uri: str
    local_path: str | None = None
    proxy_path: str | None = None
    proxy_url: str | None = None
    thumbnail_path: str | None = None
    thumbnail_url: str | None = None
    filename: str | None = None
    status: Literal["registered", "processing", "proxy_ready", "failed", "missing"] = "registered"
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: str
    updated_at: str


class RegisterAssetRequest(BaseModel):
    room_id: str
    uri: str
    source_type: Literal["local_path", "nas_path", "cloud_url", "upload", "generated"] = "local_path"
    make_proxy: bool = True


class ProductionContent(BaseModel):
    id: str
    room_id: str
    title: str
    format: str = "9:16"
    status: Literal["draft", "running", "ready", "failed"] = "draft"
    asset_ids: list[str] = Field(default_factory=list)
    timeline: dict[str, Any] = Field(default_factory=dict)
    outputs: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str
    updated_at: str


class CreateContentRequest(BaseModel):
    room_id: str
    title: str = "Untitled content"
    format: str = "9:16"
    asset_ids: list[str] = Field(default_factory=list)
    timeline: dict[str, Any] = Field(default_factory=dict)


class SaveContentRequest(BaseModel):
    timeline: dict[str, Any] | None = None
    asset_ids: list[str] | None = None
    status: Literal["draft", "running", "ready", "failed"] | None = None


class ProductionJob(BaseModel):
    id: str
    room_id: str
    content_id: str
    kind: str = "dan_execute"
    status: Literal["queued", "running", "done", "failed"] = "queued"
    instruction: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: str
    updated_at: str


class CreateJobRequest(BaseModel):
    room_id: str
    content_id: str
    instruction: dict[str, Any] = Field(default_factory=dict)


def _ffmpeg() -> str:
    candidates = [
        shutil.which("ffmpeg"),
        r"C:\Users\Owner\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError("ffmpeg not found")


def _ffprobe() -> str:
    candidates = [
        shutil.which("ffprobe"),
        r"C:\Users\Owner\ffmpeg\bin\ffprobe.exe",
        r"C:\ffmpeg\bin\ffprobe.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError("ffprobe not found")


def _room_dir(room_id: str) -> Path:
    safe = "".join(ch for ch in room_id if ch.isalnum() or ch in "-_")[:80]
    if not safe:
        raise HTTPException(status_code=400, detail="Invalid room_id")
    path = ASSET_ROOT / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_path(room_id: str) -> Path:
    return _room_dir(room_id) / "assets.json"


def _contents_path(room_id: str) -> Path:
    return _room_dir(room_id) / "contents.json"


def _jobs_path(room_id: str) -> Path:
    return _room_dir(room_id) / "jobs.json"


def _read_assets(room_id: str) -> list[dict[str, Any]]:
    path = _index_path(room_id)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write_assets(room_id: str, assets: list[dict[str, Any]]) -> None:
    _index_path(room_id).write_text(json.dumps(assets, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write_json_list(path: Path, items: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_contents(room_id: str) -> list[dict[str, Any]]:
    contents = _read_json_list(_contents_path(room_id))
    changed = False
    for content in contents:
        timeline = content.get("timeline") if isinstance(content.get("timeline"), dict) else {}
        source_asset_ids = timeline.get("source_asset_ids") if isinstance(timeline, dict) else None
        if not content.get("asset_ids") and isinstance(source_asset_ids, list) and source_asset_ids:
            content["asset_ids"] = [str(asset_id) for asset_id in source_asset_ids]
            changed = True
    if changed:
        _write_json_list(_contents_path(room_id), contents)
    return contents


def _write_contents(room_id: str, contents: list[dict[str, Any]]) -> None:
    _write_json_list(_contents_path(room_id), contents)


def _read_jobs(room_id: str) -> list[dict[str, Any]]:
    return _read_json_list(_jobs_path(room_id))


def _write_jobs(room_id: str, jobs: list[dict[str, Any]]) -> None:
    _write_json_list(_jobs_path(room_id), jobs)


def _update_job(room_id: str, job_id: str, patch: dict[str, Any]) -> None:
    jobs = _read_jobs(room_id)
    now = datetime.now(timezone.utc).isoformat()
    for job in jobs:
        if job.get("id") == job_id:
            job.update(patch)
            job["updated_at"] = now
            break
    _write_jobs(room_id, jobs)


def _update_content(room_id: str, content_id: str, patch: dict[str, Any]) -> None:
    contents = _read_contents(room_id)
    now = datetime.now(timezone.utc).isoformat()
    for content in contents:
        if content.get("id") == content_id:
            content.update(patch)
            content["updated_at"] = now
            break
    _write_contents(room_id, contents)


def _update_asset(room_id: str, asset_id: str, patch: dict[str, Any]) -> None:
    assets = _read_assets(room_id)
    now = datetime.now(timezone.utc).isoformat()
    for asset in assets:
        if asset.get("id") == asset_id:
            asset.update(patch)
            asset["updated_at"] = now
            break
    _write_assets(room_id, assets)


def _add_generated_video_asset(
    room_id: str,
    path: Path,
    *,
    filename: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    asset_id = str(uuid.uuid4())
    thumb = path.with_name(f"{path.stem}_thumb.jpg")
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        subprocess.run(
            [
                _ffmpeg(),
                "-y",
                "-ss",
                "1",
                "-i",
                str(path),
                "-vframes",
                "1",
                "-vf",
                "scale=-2:360",
                str(thumb),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            check=False,
        )
    except Exception:
        pass

    asset = ProductionAsset(
        id=asset_id,
        room_id=room_id,
        kind="video",
        source_type="generated",
        original_uri=str(path),
        local_path=str(path),
        proxy_path=str(path),
        proxy_url=f"/api/v1/production-assets/media?room_id={room_id}&asset_id={asset_id}&variant=proxy",
        thumbnail_path=str(thumb) if thumb.exists() else None,
        thumbnail_url=f"/api/v1/production-assets/media?room_id={room_id}&asset_id={asset_id}&variant=thumbnail"
        if thumb.exists()
        else None,
        filename=filename,
        status="proxy_ready",
        metadata=metadata or _probe_video(path),
        created_at=now,
        updated_at=now,
    ).model_dump()
    assets = _read_assets(room_id)
    assets.append(asset)
    _write_assets(room_id, assets)
    return asset


def _remove_asset_files(asset: dict[str, Any]) -> None:
    for key in ("local_path", "proxy_path", "thumbnail_path"):
        value = asset.get(key)
        if not value:
            continue
        try:
            path = Path(str(value)).resolve()
            if path.exists() and path.is_file() and UPLOADS_DIR.resolve() in path.parents:
                path.unlink()
        except Exception:
            pass


def _source_asset_for_job(room_id: str, asset_ids: list[Any]) -> dict[str, Any] | None:
    assets = _read_assets(room_id)
    id_set = {str(asset_id) for asset_id in asset_ids}
    for asset in assets:
        if asset.get("id") in id_set and asset.get("kind") == "video":
            return asset
    return None


def _assets_by_id(room_id: str) -> dict[str, dict[str, Any]]:
    return {str(asset.get("id")): asset for asset in _read_assets(room_id) if asset.get("id")}


def _output_size(format_value: str | None) -> tuple[int, int]:
    # Draft renders are intentionally lighter than final platform exports.
    if format_value == "16:9":
        return 1280, 720
    if format_value == "1:1":
        return 1080, 1080
    if format_value == "4:5":
        return 864, 1080
    return 720, 1280


def _sequence_video_clips(sequence: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(sequence, dict):
        return []
    clips: list[dict[str, Any]] = []
    for track in sequence.get("tracks") or []:
        if not isinstance(track, dict) or track.get("type") != "video":
            continue
        for clip in track.get("clips") or []:
            if isinstance(clip, dict):
                clips.append(clip)
    return sorted(clips, key=lambda item: float(item.get("timeline_start") or 0))


def _sequence_caption_clips(sequence: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(sequence, dict):
        return []
    clips: list[dict[str, Any]] = []
    for track in sequence.get("tracks") or []:
        if not isinstance(track, dict) or track.get("type") != "caption":
            continue
        for clip in track.get("clips") or []:
            if isinstance(clip, dict) and str(clip.get("text") or "").strip():
                clips.append(clip)
    return sorted(clips, key=lambda item: float(item.get("timeline_start") or 0))


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    sec = seconds % 60
    return f"{hours}:{minutes:02d}:{sec:05.2f}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def _write_caption_ass(path: Path, captions: list[dict[str, Any]], width: int, height: int) -> None:
    font_size = max(28, round(height * 0.04))
    margin_v = max(54, round(height * 0.08))
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,Yu Gothic,{font_size},&H00FFFFFF,&H000000FF,&H00111111,&HAA000000,"
        f"1,0,0,0,100,100,0,0,1,4,1,2,54,54,{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for caption in captions:
        start = float(caption.get("timeline_start") or 0)
        end = max(start + 0.2, float(caption.get("timeline_end") or start + 2))
        text = _ass_escape(str(caption.get("text") or "").strip())
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}")
    path.write_text("\n".join(lines), encoding="utf-8")


def _asset_source_path(asset: dict[str, Any]) -> Path:
    source_value = asset.get("proxy_path") or asset.get("local_path")
    if not source_value:
        raise RuntimeError(f"Video asset has no local path: {asset.get('id')}")
    path = Path(source_value).resolve()
    if not path.exists():
        raise RuntimeError(f"Video file not found: {path}")
    return path


def _attach_output_asset(
    room_id: str,
    content_id: str,
    job_id: str,
    output_asset: dict[str, Any],
    out_path: Path,
    *,
    kind: str,
) -> None:
    contents = _read_contents(room_id)
    for content in contents:
        if content.get("id") == content_id:
            outputs = list(content.get("outputs") or [])
            outputs.insert(
                0,
                {
                    "job_id": job_id,
                    "asset_id": output_asset["id"],
                    "path": str(out_path),
                    "url": output_asset.get("proxy_url"),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "kind": kind,
                },
            )
            content["outputs"] = outputs
            content["updated_at"] = datetime.now(timezone.utc).isoformat()
            break
    _write_contents(room_id, contents)


def _blur_annotations(instruction: dict[str, Any]) -> list[dict[str, Any]]:
    annotations = ((instruction.get("timeline") or {}).get("annotations") or [])
    return [
        annotation
        for annotation in annotations
        if annotation.get("intent") == "blur" and annotation.get("kind") == "rect" and isinstance(annotation.get("data"), dict)
    ]


def _is_overlay_clip(clip: dict[str, Any]) -> bool:
    return str(clip.get("composition") or "") in ("pip", "overlay")


def _sequence_overlay_clips(sequence: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Clips that should be composited ON TOP of the base video (PiP / wipe).
    From overlay-type tracks, plus video-track clips marked composition pip/overlay."""
    if not isinstance(sequence, dict):
        return []
    clips: list[dict[str, Any]] = []
    for track in sequence.get("tracks") or []:
        if not isinstance(track, dict):
            continue
        ttype = track.get("type")
        for clip in track.get("clips") or []:
            if not isinstance(clip, dict):
                continue
            if ttype == "overlay" or (ttype == "video" and _is_overlay_clip(clip)):
                clips.append(clip)
    return sorted(clips, key=lambda c: (float(c.get("layer") or 0), float(c.get("timeline_start") or 0)))


def _sequence_audio_clips(sequence: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(sequence, dict):
        return []
    clips: list[dict[str, Any]] = []
    for track in sequence.get("tracks") or []:
        if not isinstance(track, dict) or track.get("type") != "audio":
            continue
        for clip in track.get("clips") or []:
            if isinstance(clip, dict) and clip.get("asset_id"):
                clips.append(clip)
    return sorted(clips, key=lambda c: float(c.get("timeline_start") or 0))


def _sequence_effect_clips(sequence: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(sequence, dict):
        return []
    clips: list[dict[str, Any]] = []
    for track in sequence.get("tracks") or []:
        if not isinstance(track, dict) or track.get("type") != "effect":
            continue
        for clip in track.get("clips") or []:
            if isinstance(clip, dict) and isinstance(clip.get("region"), dict):
                clips.append(clip)
    return clips


def _clip_source_range(clip: dict[str, Any], metadata: dict[str, Any]) -> tuple[float, float, float, float, bool]:
    """Return (source_start, source_end, out_duration, source_duration, is_freeze).

    The clip's TIMELINE duration (timeline_end - timeline_start) is authoritative
    for how long it occupies the output: out_duration = timeline duration. Playback
    is always 1x (NO time-warp): if the source span is longer than the slot it is
    trimmed (the head is shown at normal speed); if shorter, the caller freeze-pads
    the last frame. This avoids fast-forward/slow-motion.
    A clip with source_start >= source_end is a freeze-frame held for out_duration."""
    asset_duration = float(metadata.get("duration") or clip.get("source_duration") or 0)
    source_start = max(0.0, float(clip.get("source_start") or 0))
    source_end = float(clip.get("source_end") or 0)
    tl_start = float(clip.get("timeline_start") or 0)
    tl_end = float(clip.get("timeline_end") or 0)
    tl_dur = tl_end - tl_start if tl_end > tl_start else 0.0
    if source_end > source_start:
        if asset_duration > 0:
            source_end = min(source_end, asset_duration)
        src_dur = max(0.05, source_end - source_start)
        out_dur = tl_dur if tl_dur > 0 else src_dur
        if src_dur > out_dur:  # source longer than slot: trim tail, keep 1x speed
            source_end = source_start + out_dur
            src_dur = out_dur
        return source_start, source_end, out_dur, src_dur, False
    # freeze-frame: one frame held for the timeline duration
    return source_start, source_start + 0.04, max(0.05, tl_dur or 2.0), 0.0, True


def _blur_chain(video_in: str, idx: int, x: int, y: int, w: int, h: int, start: float, end: float, style: str) -> tuple[str, str]:
    """Return (filter_string, out_label) for a time-gated regional blur/mosaic overlay."""
    out = f"vblur{idx}"
    base, crop, blurred = f"bbase{idx}", f"bcrop{idx}", f"bblur{idx}"
    style = (style or "").lower()
    if "mosaic" in style:
        down_w = max(2, w // 12)
        down_h = max(2, h // 12)
        proc = f"crop={w}:{h}:{x}:{y},scale={down_w}:{down_h}:flags=neighbor,scale={w}:{h}:flags=neighbor"
    elif "gaussian" in style or "gblur" in style or "soft" in style:
        proc = f"crop={w}:{h}:{x}:{y},gblur=sigma=18"
    else:
        proc = f"crop={w}:{h}:{x}:{y},boxblur=18:2"
    filt = (
        f"[{video_in}]split[{base}][{crop}];"
        f"[{crop}]{proc}[{blurred}];"
        f"[{base}][{blurred}]overlay={x}:{y}:enable='between(t\\,{start:.3f}\\,{end:.3f})'[{out}]"
    )
    return filt, out


def _render_sequence_job(room_id: str, job_id: str, content_id: str, instruction: dict[str, Any], job_dir: Path) -> dict[str, Any] | None:
    timeline = instruction.get("timeline") if isinstance(instruction.get("timeline"), dict) else {}
    sequence = timeline.get("sequence") if isinstance(timeline, dict) else None
    if not isinstance(sequence, dict):
        return None

    base_clips = [c for c in _sequence_video_clips(sequence) if not _is_overlay_clip(c)]
    if not base_clips:
        return None

    overlay_clips = _sequence_overlay_clips(sequence)
    audio_clips = _sequence_audio_clips(sequence)
    effect_clips = _sequence_effect_clips(sequence)
    has_audio_track = len(audio_clips) > 0

    assets = _assets_by_id(room_id)
    output_width, output_height = _output_size(str(sequence.get("format") or timeline.get("format") or "9:16"))
    out_path = job_dir / f"{job_id}_sequence.mp4"

    command = [_ffmpeg(), "-y"]
    filters: list[str] = []
    input_index = 0

    # --- base video: concat the full-frame clips (pip/overlay clips excluded) ---
    concat_parts: list[str] = []
    rendered_count = 0
    for clip in base_clips:
        asset = assets.get(str(clip.get("asset_id") or ""))
        if not asset or asset.get("kind") != "video":
            continue
        source_path = _asset_source_path(asset)
        metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else _probe_video(source_path)
        source_start, source_end, out_dur, src_dur, is_freeze = _clip_source_range(clip, metadata)
        command.extend(["-i", str(source_path)])
        pad_needed = 0.0 if is_freeze else max(0.0, out_dur - src_dur)
        _scale = f"scale={output_width}:{output_height}:force_original_aspect_ratio=increase,crop={output_width}:{output_height},setsar=1,fps=30"
        if is_freeze:
            setpts = f"setpts=PTS-STARTPTS,{_scale},tpad=stop_mode=clone:stop_duration={out_dur:.3f}"
        else:
            _pad = f",tpad=stop_mode=clone:stop_duration={pad_needed:.3f}" if pad_needed > 0.02 else ""
            setpts = f"setpts=PTS-STARTPTS,{_scale}{_pad}"
        filters.append(
            f"[{input_index}:v]"
            f"trim=start={source_start:.3f}:end={source_end:.3f},"
            f"{setpts},format=yuv420p"
            f"[v{rendered_count}]"
        )
        if not has_audio_track:
            if metadata.get("audio_codec") and not clip.get("muted") and not is_freeze:
                filters.append(
                    f"[{input_index}:a]"
                    f"atrim=start={source_start:.3f}:end={source_end:.3f},"
                    f"asetpts=PTS-STARTPTS,apad,atrim=duration={out_dur:.3f},aresample=48000,aformat=channel_layouts=stereo"
                    f"[a{rendered_count}]"
                )
            else:
                filters.append(
                    f"anullsrc=r=48000:cl=stereo,atrim=duration={out_dur:.3f},asetpts=PTS-STARTPTS"
                    f"[a{rendered_count}]"
                )
            concat_parts.extend([f"[v{rendered_count}]", f"[a{rendered_count}]"])
        else:
            concat_parts.append(f"[v{rendered_count}]")
        input_index += 1
        rendered_count += 1

    if rendered_count == 0:
        return None

    if has_audio_track:
        filters.append("".join(concat_parts) + f"concat=n={rendered_count}:v=1:a=0[vcat]")
        base_audio_out: str | None = None
    else:
        filters.append("".join(concat_parts) + f"concat=n={rendered_count}:v=1:a=1[vcat][acat]")
        base_audio_out = "acat"
    video_out = "vcat"

    # --- regional blur / mosaic: effect-track clips + blur annotations (honor style) ---
    blur_specs: list[dict[str, Any]] = []
    for clip in effect_clips:
        region = clip.get("region") if isinstance(clip.get("region"), dict) else {}
        blur_specs.append({
            "x": region.get("x"), "y": region.get("y"), "width": region.get("width"), "height": region.get("height"),
            "start": clip.get("timeline_start"), "end": clip.get("timeline_end"), "style": clip.get("style"),
        })
    for annotation in _blur_annotations(instruction):
        data = annotation.get("data") or {}
        blur_specs.append({
            "x": data.get("x"), "y": data.get("y"), "width": data.get("width"), "height": data.get("height"),
            "start": annotation.get("start"), "end": annotation.get("end"),
            "style": data.get("blur_style") or data.get("style"),
        })
    for bi, spec in enumerate(blur_specs, start=1):
        x = max(0, min(output_width - 2, round(float(spec.get("x") or 0) * output_width)))
        y = max(0, min(output_height - 2, round(float(spec.get("y") or 0) * output_height)))
        w = max(2, min(output_width - x, round(float(spec.get("width") or 0) * output_width)))
        h = max(2, min(output_height - y, round(float(spec.get("height") or 0) * output_height)))
        start = max(0.0, float(spec.get("start") or 0))
        end = max(start + 0.01, float(spec.get("end") or (start + 0.5)))
        filt, video_out = _blur_chain(video_out, bi, x, y, w, h, start, end, str(spec.get("style") or ""))
        filters.append(filt)

    # --- overlay / PiP (wipe): composite on top, ascending layer = closer to front ---
    for oi, clip in enumerate(overlay_clips, start=1):
        asset = assets.get(str(clip.get("asset_id") or ""))
        if not asset or asset.get("kind") != "video":
            continue
        source_path = _asset_source_path(asset)
        metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else _probe_video(source_path)
        source_start, source_end, ov_dur, ov_src, ov_freeze = _clip_source_range(clip, metadata)
        pos = clip.get("position") if isinstance(clip.get("position"), dict) else {}
        ow = max(2, round(float(pos.get("width") or 0.46) * output_width))
        oh = max(2, round(float(pos.get("height") or 0.145) * output_height))
        px = max(0, min(output_width - 2, round(float(pos.get("x") or 0.27) * output_width)))
        py = max(0, min(output_height - 2, round(float(pos.get("y") or 0.835) * output_height)))
        ts = max(0.0, float(clip.get("timeline_start") or 0))
        te = max(ts + 0.05, float(clip.get("timeline_end") or (ts + ov_dur)))
        ov_pad = 0.0 if ov_freeze else max(0.0, ov_dur - ov_src)
        if ov_freeze:
            ov_pre = f"setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={ov_dur:.3f},"
        else:
            ov_pre = "setpts=PTS-STARTPTS," + (f"tpad=stop_mode=clone:stop_duration={ov_pad:.3f}," if ov_pad > 0.02 else "")
        command.extend(["-i", str(source_path)])
        filters.append(
            f"[{input_index}:v]"
            f"trim=start={source_start:.3f}:end={source_end:.3f},"
            f"{ov_pre}"
            f"scale={ow}:{oh},setsar=1,setpts=PTS-STARTPTS+{ts:.3f}/TB,format=yuv420p"
            f"[ov{oi}]"
        )
        filters.append(
            f"[{video_out}][ov{oi}]overlay={px}:{py}:enable='between(t\\,{ts:.3f}\\,{te:.3f})'[vov{oi}]"
        )
        video_out = f"vov{oi}"
        input_index += 1

    captions = _sequence_caption_clips(sequence)
    if captions:
        ass_path = job_dir / f"{job_id}_captions.ass"
        _write_caption_ass(ass_path, captions, output_width, output_height)
        escaped_ass = str(ass_path).replace("\\", "/").replace(":", "\\:")
        filters.append(f"[{video_out}]subtitles='{escaped_ass}'[vcap]")
        video_out = "vcap"

    # --- audio: when an audio track exists, mix its clips (replaces base clip audio) ---
    audio_out = base_audio_out
    if has_audio_track:
        audio_labels: list[str] = []
        for clip in audio_clips:
            asset = assets.get(str(clip.get("asset_id") or ""))
            if not asset or asset.get("kind") != "video":
                continue
            source_path = _asset_source_path(asset)
            metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else _probe_video(source_path)
            if not metadata.get("audio_codec"):
                continue
            source_start, source_end, _dur, _src, au_freeze = _clip_source_range(clip, metadata)
            if au_freeze:
                continue
            ts_ms = max(0, round(float(clip.get("timeline_start") or 0) * 1000))
            label = f"au{len(audio_labels)}"
            command.extend(["-i", str(source_path)])
            filters.append(
                f"[{input_index}:a]"
                f"atrim=start={source_start:.3f}:end={source_end:.3f},"
                f"asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,adelay={ts_ms}|{ts_ms}"
                f"[{label}]"
            )
            audio_labels.append(label)
            input_index += 1
        if len(audio_labels) == 1:
            audio_out = audio_labels[0]
        elif len(audio_labels) > 1:
            filters.append("".join(f"[{l}]" for l in audio_labels) + f"amix=inputs={len(audio_labels)}:duration=longest:normalize=0[aout]")
            audio_out = "aout"
        else:
            audio_out = None

    creationflags = 0
    if hasattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS"):
        creationflags = subprocess.BELOW_NORMAL_PRIORITY_CLASS  # type: ignore[attr-defined]
    elif hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = subprocess.CREATE_NO_WINDOW

    maps = ["-map", f"[{video_out}]"]
    audio_args = ["-an"]
    if audio_out:
        maps += ["-map", f"[{audio_out}]"]
        audio_args = ["-c:a", "aac", "-b:a", "128k"]

    subprocess.run(
        [
            *command,
            "-filter_complex",
            ";".join(filters),
            *maps,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            *audio_args,
            "-movflags",
            "+faststart",
            str(out_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creationflags,
        check=True,
    )

    output_asset = _add_generated_video_asset(
        room_id,
        out_path,
        filename=f"draft_{content_id[:8]}_{job_id[:8]}.mp4",
    )
    _attach_output_asset(room_id, content_id, job_id, output_asset, out_path, kind="sequence_render")
    return {
        "output_asset_id": output_asset["id"],
        "output_path": str(out_path),
        "output_url": output_asset.get("proxy_url"),
        "rendered_clip_count": rendered_count,
        "render_size": f"{output_width}x{output_height}",
    }


def _render_blur_job(room_id: str, job_id: str, content_id: str, instruction: dict[str, Any], job_dir: Path) -> dict[str, Any] | None:
    blur_items = _blur_annotations(instruction)
    if not blur_items:
        return None

    source_asset = _source_asset_for_job(room_id, instruction.get("asset_ids") or [])
    if not source_asset:
        raise RuntimeError("No source video asset found for blur render")

    source_value = source_asset.get("proxy_path") or source_asset.get("local_path")
    if not source_value:
        raise RuntimeError("Source video asset has no local path")
    source_path = Path(source_value).resolve()
    if not source_path.exists():
        raise RuntimeError(f"Source video not found: {source_path}")

    metadata = _probe_video(source_path)
    width = int(metadata.get("width") or 0)
    height = int(metadata.get("height") or 0)
    if width <= 0 or height <= 0:
        probed = _probe_video(source_path)
        width = int(probed.get("width") or 0)
        height = int(probed.get("height") or 0)
        metadata = probed
    if width <= 0 or height <= 0:
        raise RuntimeError("Could not determine source video dimensions")

    out_path = job_dir / f"{job_id}_blur.mp4"
    filters: list[str] = ["[0:v]format=yuv420p[v0]"]
    last = "v0"
    for index, annotation in enumerate(blur_items, start=1):
        data = annotation.get("data") or {}
        x = max(0, min(width - 2, round(float(data.get("x") or 0) * width)))
        y = max(0, min(height - 2, round(float(data.get("y") or 0) * height)))
        w = max(2, min(width - x, round(float(data.get("width") or 0) * width)))
        h = max(2, min(height - y, round(float(data.get("height") or 0) * height)))
        start = max(0.0, float(annotation.get("start") or 0))
        end = max(start + 0.01, float(annotation.get("end") or (start + 0.5)))
        filters.append(
            f"[{last}]split[base{index}][crop{index}src];"
            f"[crop{index}src]crop={w}:{h}:{x}:{y},boxblur=18:2[blur{index}];"
            f"[base{index}][blur{index}]overlay={x}:{y}:enable='between(t\\,{start:.3f}\\,{end:.3f})'[v{index}]"
        )
        last = f"v{index}"

    filter_complex = ";".join(filters)
    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    subprocess.run(
        [
            _ffmpeg(),
            "-y",
            "-i",
            str(source_path),
            "-filter_complex",
            filter_complex,
            "-map",
            f"[{last}]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(out_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creationflags,
        check=True,
    )

    output_asset = _add_generated_video_asset(
        room_id,
        out_path,
        filename=f"{Path(source_path).stem}_blur_{job_id[:8]}.mp4",
    )
    _attach_output_asset(room_id, content_id, job_id, output_asset, out_path, kind="blur_render")
    return {
        "output_asset_id": output_asset["id"],
        "output_path": str(out_path),
        "output_url": output_asset.get("proxy_url"),
        "rendered_blur_count": len(blur_items),
    }


def _extract_json_object(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else None
    except Exception:
        pass

    start = cleaned.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(cleaned)):
        ch = cleaned[index]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    value = json.loads(cleaned[start:index + 1])
                    return value if isinstance(value, dict) else None
                except Exception:
                    return None
    return None


def _job_events_path(room_id: str, job_id: str) -> Path:
    return _room_dir(room_id) / "jobs" / job_id / "events.jsonl"


def _append_job_event(room_id: str, job_id: str, event: dict[str, Any]) -> None:
    try:
        path = _job_events_path(room_id, job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


PRODUCTION_ANALYSIS_PROMPT = (
    "この動画を、動画編集者が使うための『編集用メモ』として分析してください。\n"
    "必ず mm:ss のタイムスタンプ付きで、以下を出力してください:\n\n"
    "1. シーン分割（タイムスタンプ範囲つき）: 各区間が『人物が喋る(トーキングヘッド)』か"
    "『画面操作/デモ』か『その他』かを明記。どこで切り替わるかが分かるように。\n"
    "2. 発話の書き起こし（タイムスタンプつき）: 実際に喋っている言葉をそのまま。言い直し・"
    "フィラー(えー/あの等)・不要な無音/間は [無音] のように明示。\n"
    "3. 画面操作の手順（操作デモ区間）: 何の画面で何を操作しているかを時系列で。\n"
    "4. 画面に映る固有名詞・個人情報・入力値など、ぼかすべき可能性がある要素の位置と時刻。\n"
    "推測は推測と明記。日本語で、簡潔かつ具体的に。"
)

# Cap per-asset analysis injected into the edit prompt (full text is cached on the asset).
_EDIT_ANALYSIS_INJECT_LIMIT = 4500


async def _analyze_assets_for_edit(room_id: str, source_assets: list[dict[str, Any]]) -> dict[str, str]:
    """Give Dan 'eyes': run Gemini multimodal analysis on each video asset and return
    {asset_id: analysis_text}. Results are cached on the asset metadata so repeat jobs
    on the same footage do not re-pay the upload+analysis cost. Analyzes the proxy
    (light) rather than the original (often multi-GB)."""
    from app.services.video_analyzer import analyze_video

    assets = _read_assets(room_id)
    by_id = {str(a.get("id")): a for a in assets if a.get("id")}
    results: dict[str, str] = {}
    dirty = False
    for asset in source_assets:
        if not isinstance(asset, dict) or asset.get("kind") != "video":
            continue
        aid = str(asset.get("id") or "")
        if not aid:
            continue
        src = asset.get("proxy_path") or asset.get("local_path")
        if not src or not Path(src).exists():
            continue
        live = by_id.get(aid)
        meta = (live.get("metadata") if live and isinstance(live.get("metadata"), dict) else {}) or {}
        if meta.get("edit_analysis") and meta.get("edit_analysis_src") == str(src):
            results[aid] = meta["edit_analysis"]
            continue
        text = await analyze_video(str(src), prompt=PRODUCTION_ANALYSIS_PROMPT)
        if text:
            results[aid] = text
            if live is not None:
                meta = dict(meta)
                meta["edit_analysis"] = text
                meta["edit_analysis_src"] = str(src)
                live["metadata"] = meta
                dirty = True
    if dirty:
        _write_assets(room_id, assets)
    return results


def _build_dan_timeline(
    room_id: str,
    user_id: str,
    job_id: str,
    instruction: dict[str, Any],
    instruction_path: Path,
    output_path: Path,
    render_path: Path,
) -> dict[str, Any] | None:
    source_assets = [
        {
            "id": asset.get("id"),
            "kind": asset.get("kind"),
            "filename": asset.get("filename"),
            "local_path": asset.get("local_path"),
            "proxy_path": asset.get("proxy_path"),
            "source_type": asset.get("source_type"),
            "metadata": asset.get("metadata"),
        }
        for asset in (instruction.get("source_assets") or [])
        if isinstance(asset, dict)
    ]
    timeline = instruction.get("timeline") if isinstance(instruction.get("timeline"), dict) else {}

    # Give Dan "eyes": Gemini multimodal read of each clip (timestamped transcript,
    # talking-head vs screen-operation segmentation, blur candidates). This is the
    # semantic layer that chat-Dan gets and the production tab previously lacked.
    analyses: dict[str, str] = {}
    try:
        analyses = asyncio.run(_analyze_assets_for_edit(room_id, source_assets))
    except Exception:
        analyses = {}
    if analyses:
        _append_job_event(room_id, job_id, {"type": "status", "text": f"映像分析(Gemini)完了: {len(analyses)}本"})
    analysis_parts = []
    for asset in source_assets:
        aid = str(asset.get("id") or "")
        if aid in analyses:
            text = analyses[aid]
            if len(text) > _EDIT_ANALYSIS_INJECT_LIMIT:
                text = text[:_EDIT_ANALYSIS_INJECT_LIMIT] + "\n...(以下略・全文はアセットにキャッシュ済)"
            analysis_parts.append(f"### asset {aid} ({asset.get('filename') or ''})\n{text}")
    analysis_block = "\n\n".join(analysis_parts) if analysis_parts else "(映像分析なし。ffprobe/フレーム抽出で自分で把握すること)"
    audio_check = PROJECT_ROOT / "scripts" / "dan_audio_check.py"
    try:
        edit_policy = (PROJECT_ROOT / ".claude" / "skills" / "post-production" / "edit_policy.md").read_text(encoding="utf-8")
    except Exception:
        edit_policy = ""

    prompt = f"""
You are DAN, the editor inside the production workspace. Your deliverable is a FINISHED, RENDERED video — not a plan.

Do not treat this as a template-filling task. Inspect the selected assets, reason about the footage, and use your video / post-production skills and the command line (ffmpeg) to actually cut, composite, caption, blur, and finish the video yourself — exactly as you would when a user asks you to make a video in normal chat. The same quality bar applies. A JSON plan without a rendered video is a FAILURE.

Read the full job instruction (brief, blur annotations, audio policy, format) here:
{instruction_path}

PRIMARY DELIVERABLE — render the finished video to this exact path:
{render_path}

RENDER EXECUTION (critical): Run ffmpeg in the FOREGROUND and wait for each call to finish. Do NOT start the render as a background/detached process and then poll for it (do not background it and wait via Monitor) — when your turn ends, detached child processes are killed and the output is lost. If you build the video in segments, run each ffmpeg call in the foreground, then concat to {render_path} as the final foreground step. Keep each ffmpeg call reasonably fast: prefer the proxy files, and if you need ranges deep inside a long source, cut those ranges to short intermediates first instead of re-seeking the full file repeatedly. Before you finish, confirm with ffprobe that {render_path} exists and has the expected duration.

EDITING POLICY (必読 — これに従って編集する。合格基準は「短さ」や clean=true ではなく、人間が手で詰めた時の自然さ):
{edit_policy}

How to work:
1. A Gemini analysis of each clip (timestamped transcript, scene segmentation = talking-head vs screen-operation, and blur candidates) is provided below under "映像分析(Gemini)". Use it as your PRIMARY source for what is said, what happens, and when — this is how you decide caption wording, which 言い直し takes to drop, and when to switch to the wipe/screen composition. Follow the EDITING POLICY: cut ONLY restatements, keep full sentences with a 0.3-0.5s breath, never clip sentence ends, keep filler. Gemini's timestamps are only mm:ss-coarse, so for FRAME-ACCURATE cut points run the audio analysis tool on the talking-head source clip:
   python "{audio_check}" "<clip path>"
   It writes a word-timestamped transcript plus `dead_air` and `restatements`. Use the word timestamps to set out-points at SENTENCE boundaries (last word end + breath), not at the nearest silence. Drop only the earlier of a restatement pair. Then confirm with ffprobe / frame extraction. Do not guess from metadata alone.
1b. SCREEN MAP (for any screen-recording asset): BEFORE building, make a contact sheet — extract frames every ~5-10s and montage them into one image, then Read it — to map the full operation flow. Per EDITING POLICY §2, show the operation from the very start (app launch / home screen) through completion; never start mid-flow or skip steps like opening the app or selecting the photo.
2. Execute real edits with ffmpeg: trim/cut, multi-clip concat, picture-in-picture / wipe (overlay one camera as a small window over another), captions/telop, audio replacement (e.g. use only the main-camera audio), and blur/mosaic. Every requirement in the brief (PiP/wipe, blur regions, audio source, no-cut sections, caption-free sections) must be honored in the actual rendered pixels — not just described.
3. Honor the requested blur style. If the brief asks for a soft/blended mosaic that follows a moving region, do that; do not settle for a single static hard box if the brief forbids it.
4. VISUAL SELF-VERIFY: extract several frames from {render_path} (intro, each PiP/operation section, each blur section) and confirm the wipe, captions, and blur are actually present and correct. If anything is wrong, fix it and re-render. Never hand off a video you have not visually checked.
4b. AUDIO SELF-VERIFY (do not skip — this is your "ears"): after rendering, run
   python "{audio_check}" "{render_path}"
   Use it to catch problems, but follow the EDITING POLICY — do NOT just chase clean=true (it over-cuts):
   - `restatements`: remove the earlier duplicate take only (keep the later, complete one).
   - `dead_air` BETWEEN sentences: compress to a natural beat (~0.3s) — do NOT delete it entirely.
   - Never clip a sentence end: if a cut lands before the final word/particle finishes, move the out-point later and keep a 0.3-0.5s breath. Keep filler (えー/あの).
   - Confirm necessary content survived: the full operation flow (from app launch) and every required step must still be present. If a step is missing, you cut too much — restore it.
   When you remove a span, cut video AND audio together, re-render, and re-check. Stop when the pacing is natural per the policy — not when a metric hits zero. A frame can look perfect while the pacing is wrong, so this audio pass plus the policy checks are how you judge it.
5. Use the proxy_path files for fast iteration; use the local_path originals when you need full resolution for the final render.

AFTER the video at {render_path} exists and you have verified it, write a production-state JSON that DESCRIBES the edit you actually rendered (so the user can fine-tune it on the timeline) here:
{output_path}

The JSON must be one object whose tracks/clips/captions/annotations match the video you rendered. Preserve the user's brief and source_asset_ids. Use any extra fields you need; the UI will preserve unknown fields. This JSON is a description of finished work, not the goal.

Shape to match (so the timeline editor can read it):
{{
  "brief": string,
  "workflow_preset": string,
  "format": string,
  "source_asset_ids": string[],
  "annotations": [
    {{"id": string, "kind": "rect"|"freehand"|"marker"|"note", "intent": "blur"|"replace"|"comment"|string, "start": number, "end": number, "data": object, "note": string}}
  ],
  "sequence": {{
    "version": 1,
    "format": string,
    "duration": number,
    "tracks": [
      {{"id": "video_1", "type": "video", "label": "Main video", "clips": [
        {{
          "id": string,
          "asset_id": string,
          "label": string,
          "source_start": number,
          "source_end": number,
          "source_duration": number,
          "timeline_start": number,
          "timeline_end": number,
          "track": "video",
          "muted": boolean,
          "locked": false,
          "role": "main"|"screen"|"broll"|string,
          "composition": "fullscreen"|"pip"|"background"|string,
          "position": {{"x": number, "y": number, "width": number, "height": number}} | null,
          "auto_edit_reason": string
        }}
      ]}},
      {{"id": "overlay_1", "type": "overlay", "label": "Overlay/PIP", "clips": []}},
      {{"id": "caption_1", "type": "caption", "label": "Captions", "clips": [
        {{"id": string, "text": string, "timeline_start": number, "timeline_end": number, "track": "caption"}}
      ]}},
      {{"id": "audio_1", "type": "audio", "label": "Audio", "clips": [
        {{"id": string, "asset_id": string, "source_start": number, "source_end": number, "timeline_start": number, "timeline_end": number, "track": "audio", "role": "dialogue"|"music"|"sfx"|string}}
      ]}},
      {{"id": "effects_1", "type": "effect", "label": "Blur/Effects", "clips": []}}
    ]
  }}
}}

Important:
- The finished video at {render_path} is the goal. Do not stop at the JSON.
- Use only the selected assets below.
- Keep source_start/source_end inside each asset duration when duration is known.
- The JSON's tracks/clips/captions/annotations must describe what the rendered video actually shows (PiP, background/screen/main camera, blur regions, audio source, caption-free sections), so the timeline editor matches the video.
- If the brief says all audio uses the main camera, the rendered audio must come from the main-camera asset only.
- You may create analysis notes or helper files in the job directory; the final video and the UI handoff JSON must be written to the exact paths above.
- Print a concise status summary including the final video path after you finish.

映像分析(Gemini) — 各クリップの編集用メモ（タイムスタンプ・発話書き起こし・シーン分割・ぼかし候補）:
{analysis_block}

Selected assets:
{json.dumps(source_assets, ensure_ascii=False, indent=2)}

Existing timeline:
{json.dumps(timeline, ensure_ascii=False, indent=2)}
""".strip()

    async def run_dan(prompt_text: str, *, skip_resume: bool = False) -> str:
        from app.agent.cli_runner import process_message_cli

        chunks: list[str] = []
        async for event in process_message_cli(
            room_id=room_id,
            user_id=user_id,
            content=prompt_text,
            project_title=str(instruction.get("content_title") or "Production"),
            project_description=str(timeline.get("brief") or instruction.get("brief") or ""),
            project_status="in_progress",
            skip_save=True,
            skip_resume=skip_resume,
            cwd="D:/dan-workspace",
        ):
            event_type = str(event.get("type") or "event")
            if event_type in {"text", "reasoning", "tool_use", "result", "error"}:
                _append_job_event(room_id, job_id, {
                    "type": event_type,
                    "text": str(event.get("text") or event.get("message") or "")[:4000],
                    "name": event.get("name") or event.get("tool_name"),
                })
            if event.get("type") in {"text", "result"} and event.get("text"):
                chunks.append(str(event.get("text")))
        return "\n".join(chunks).strip()

    try:
        output = asyncio.run(run_dan(prompt))
    except Exception:
        output = None

    def read_timeline_output() -> dict[str, Any] | None:
        if not output_path.exists():
            return None
        try:
            value = json.loads(output_path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and isinstance(value.get("timeline"), dict):
                value = value["timeline"]
            if isinstance(value, dict) and isinstance(value.get("sequence"), dict):
                return value
        except Exception:
            return None
        return None

    recovered = read_timeline_output()
    if recovered:
        return recovered

    if output and "Connection closed mid-response" in output:
        repair_prompt = f"""
The previous production run was interrupted before it finished.

Do not redo the whole analysis unless necessary. Use the already inspected files, the job instruction, and your notes from the previous run.

First make sure the finished video exists and is complete at:
{render_path}
(render it if it is missing or incomplete, then extract a few frames to verify it.)

Then write the production-state JSON that describes that video here:
{output_path}

Instruction JSON:
{instruction_path}

The JSON must include a top-level "sequence" object with timeline tracks and be parseable by json.loads.
The finished video is the priority: if you can only finish one thing, finish the video.
""".strip()
        _append_job_event(room_id, job_id, {"type": "status", "text": "Retrying production-state write after interrupted CLI response."})
        try:
            repair_output = asyncio.run(run_dan(repair_prompt))
        except Exception:
            repair_output = None
        recovered = read_timeline_output()
        if recovered:
            return recovered
        if repair_output:
            value = _extract_json_object(repair_output)
            if value and isinstance(value.get("sequence"), dict):
                output_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
                return value

    if output:
        value = _extract_json_object(output)
        if value and isinstance(value.get("sequence"), dict):
            output_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            return value
    return None


# --- Timeline-first "dan_plan" mode -------------------------------------------
# Instead of Dan rendering an MP4 (its best effort) and then writing a degraded JSON
# description (the old dan_edit), Dan outputs only editing DECISIONS in natural language
# (which speech segments to keep, where the screen demo overlays as a PiP wipe, what to
# blur) and deterministic code assembles the exact timeline from Whisper word/segment
# timestamps. No timeline math is asked of Dan (LLMs degrade when forced to emit
# structured numbers), and no MP4 is rendered — the timeline IS the deliverable; the
# user reviews/edits it and exports to MP4 only on approval.

def _segment_id(asset_index: int, seg_index: int) -> str:
    return f"a{asset_index}_s{seg_index:02d}"


def _run_audio_analysis(room_id: str, job_id: str, source_assets: list[dict[str, Any]]) -> dict[str, Any]:
    """Give Dan 'ears' as STRUCTURED data: run dan_audio_check.py on each video asset up
    front (not via Dan's own tool call) so we hold a segment-timestamped transcript with
    stable ids (e.g. 'a1_s03') to drive deterministic assembly. Cached on asset metadata.
    Returns {asset_id: {asset_index, duration, segments[], dead_air[], restatements[]}}."""
    import sys, os
    assets = _read_assets(room_id)
    by_id = {str(a.get("id")): a for a in assets if a.get("id")}
    script = PROJECT_ROOT / "scripts" / "dan_audio_check.py"
    # Model choice: large-v3 (the script default) needs ~10GB VRAM and overflows an 8GB
    # GPU -> CPU fallback -> minutes/asset. 'medium' (~2.7GB) fits the GPU, runs fast, and
    # segments finely enough that 言い直し land in SEPARATE segments (so the restatement
    # safety net in _assemble_sequence_from_decisions can drop the earlier take) — and it
    # transcribes captions far more accurately than 'base'. Override via DAN_PLAN_WHISPER_MODEL.
    whisper_model = os.environ.get("DAN_PLAN_WHISPER_MODEL", "medium")
    results: dict[str, Any] = {}
    dirty = False
    asset_index = 0
    for asset in source_assets:
        if not isinstance(asset, dict) or asset.get("kind") != "video":
            continue
        asset_index += 1
        aid = str(asset.get("id") or "")
        if not aid:
            continue
        src = asset.get("proxy_path") or asset.get("local_path")
        if not src or not Path(src).exists():
            continue
        live = by_id.get(aid)
        meta = (live.get("metadata") if live and isinstance(live.get("metadata"), dict) else {}) or {}
        cached = meta.get("audio_analysis")
        if isinstance(cached, dict) and meta.get("audio_analysis_src") == str(src) and meta.get("audio_analysis_model") == whisper_model:
            cached = dict(cached)
            cached["asset_index"] = asset_index
            for j, s in enumerate(cached.get("segments") or [], start=1):
                s["id"] = _segment_id(asset_index, j)
                s["asset_id"] = aid
            results[aid] = cached
            continue
        out_json = Path(src).with_name(Path(src).stem + "_audiocheck.json")
        try:
            subprocess.run(
                [sys.executable, str(script), str(src), "--words", "--json-only", "--model", whisper_model],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=900, check=False,
            )
            data = json.loads(out_json.read_text(encoding="utf-8")) if out_json.exists() else {}
        except Exception:
            data = {}
        segs = data.get("segments") or []
        for j, s in enumerate(segs, start=1):
            s["id"] = _segment_id(asset_index, j)
            s["asset_id"] = aid
        entry = {
            "asset_id": aid,
            "asset_index": asset_index,
            "duration": data.get("duration"),
            "segments": segs,
            "dead_air": data.get("dead_air") or [],
            "restatements": data.get("restatements") or [],
        }
        results[aid] = entry
        if live is not None:
            meta = dict(meta)
            meta["audio_analysis"] = entry
            meta["audio_analysis_src"] = str(src)
            meta["audio_analysis_model"] = whisper_model
            live["metadata"] = meta
            dirty = True
    if dirty:
        _write_assets(room_id, assets)
    if results:
        n = sum(len(v.get("segments") or []) for v in results.values())
        _append_job_event(room_id, job_id, {"type": "status", "text": f"音声解析(Whisper)完了: {len(results)}本 / {n}セグメント"})
    return results


def _build_dan_plan(
    room_id: str,
    user_id: str,
    job_id: str,
    instruction: dict[str, Any],
    instruction_path: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Run Dan in DECISION-ONLY mode (no render, no timeline JSON math). Returns
    (decisions, transcripts). Dan reasons freely then emits a small DECISIONS object
    that references transcript segment ids; _assemble_sequence_from_decisions turns it
    into the exact timeline."""
    source_assets = [
        {
            "id": asset.get("id"),
            "kind": asset.get("kind"),
            "filename": asset.get("filename"),
            "local_path": asset.get("local_path"),
            "proxy_path": asset.get("proxy_path"),
            "source_type": asset.get("source_type"),
            "metadata": asset.get("metadata"),
        }
        for asset in (instruction.get("source_assets") or [])
        if isinstance(asset, dict)
    ]
    timeline = instruction.get("timeline") if isinstance(instruction.get("timeline"), dict) else {}

    analyses: dict[str, str] = {}
    try:
        analyses = asyncio.run(_analyze_assets_for_edit(room_id, source_assets))
    except Exception:
        analyses = {}
    if analyses:
        _append_job_event(room_id, job_id, {"type": "status", "text": f"映像分析(Gemini)完了: {len(analyses)}本"})
    transcripts = _run_audio_analysis(room_id, job_id, source_assets)

    analysis_parts = []
    for asset in source_assets:
        aid = str(asset.get("id") or "")
        if aid in analyses:
            text = analyses[aid]
            if len(text) > _EDIT_ANALYSIS_INJECT_LIMIT:
                text = text[:_EDIT_ANALYSIS_INJECT_LIMIT] + "\n...(以下略)"
            analysis_parts.append(f"### asset {aid} ({asset.get('filename') or ''})\n{text}")
    analysis_block = "\n\n".join(analysis_parts) if analysis_parts else "(映像分析なし)"

    transcript_parts = []
    for asset in source_assets:
        aid = str(asset.get("id") or "")
        t = transcripts.get(aid)
        if not t:
            continue
        lines = [f"### asset {aid} ({asset.get('filename') or ''}) — segments:"]
        for s in t.get("segments") or []:
            lines.append(f"  {s['id']}  [{float(s.get('start') or 0):.2f}-{float(s.get('end') or 0):.2f}]  {s.get('text') or ''}")
        for r in t.get("restatements") or []:
            f0, s0 = r.get("first") or {}, r.get("second") or {}
            lines.append(f"  ↳言い直し: 前を捨てる [{float(f0.get('start') or 0):.2f}-{float(f0.get('end') or 0):.2f}] '{f0.get('text') or ''}'  / 後を残す '{s0.get('text') or ''}'")
        transcript_parts.append("\n".join(lines))
    transcript_block = "\n\n".join(transcript_parts) if transcript_parts else "(音声なし)"

    try:
        edit_policy = (PROJECT_ROOT / ".claude" / "skills" / "post-production" / "edit_policy.md").read_text(encoding="utf-8")
    except Exception:
        edit_policy = ""

    prompt = f"""
You are DAN, a video editor. Your deliverable is EDITING DECISIONS for a timeline — NOT a rendered video, and NOT a timeline JSON with exact numbers. Do NOT run ffmpeg. Do NOT render anything. A program will assemble the exact timeline from your decisions and the word-level transcript below, and the user will fine-tune it and export to MP4 later.

Work in TWO steps, in this order:

STEP 1 — Reason out loud (free-form Japanese). Like a skilled human editor: decide which spoken segments to KEEP and in what order, which 言い直し (restatement) take to DROP, where the screen-recording should take over as the background with the main camera shown as a small wipe (PiP), what on screen must be blurred, and how tight the pacing should be. Explain WHY. Follow the EDITING POLICY below.

STEP 2 — AFTER your reasoning, output ONE json object (and nothing after it) with your DECISIONS. Reference segments by their id (e.g. a1_s03). Do NOT compute timeline seconds yourself — the assembler derives them from the transcript timestamps.

DECISIONS schema:
{{
  "spine": [ {{"segment_id": "a1_s03", "caption": "整えたテロップ文字列 or null=発話そのまま"}} ],
  "cuts": [ {{"asset_id": "<asset id>", "start": <sec>, "end": <sec>, "reason": "restatement|filler"}} ],
  "screen_overlays": [ {{"screen_asset_id": "<asset id>", "screen_source_start": <sec>, "screen_source_end": <sec>, "from_segment": "a1_s06", "to_segment": "a1_s12", "main_as_pip": true}} ],
  "blur": [ {{"asset_id": "<asset id>", "region": {{"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}}, "source_start": <sec>, "source_end": <sec>, "style": "soft"}} ],
  "silence_threshold": 0.45
}}

Rules:
- spine = the kept talking segments in final order. Anything not listed is cut. Drop the earlier take of a CROSS-segment restatement by omitting that segment.
- cuts = WORD-LEVEL removals WITHIN kept segments. The transcript below has word-level timestamps; use cuts (in the asset's own seconds) to remove a 言い直し/stutter that happens INSIDE a single segment (e.g. the segment says "スタイル名や…スタイル名や…" — cut the first occurrence) or an obvious repeated filler run. The assembler trims exactly those spans. This is how you remove duplicates that survive the spine — listen via the transcript and cut them.
- Never cut a sentence end. The assembler AUTO-compresses internal silence longer than silence_threshold seconds, so do NOT list silence in cuts. Set silence_threshold lower (e.g. 0.3) for tighter pacing or higher for relaxed, following the user's request; omit it to use the default (0.45).
- During screen_overlays the screen recording is the background and the main camera is the small wipe; captions are auto-suppressed there (do not add captions to those segments).
- All audio comes from the main-camera spine segments automatically.
- region/source coords for blur are 0..1 normalized and in the screen asset's own seconds.
- Output the json LAST, after the reasoning. It must be valid JSON.

EDITING POLICY (必読):
{edit_policy}

映像分析(Gemini):
{analysis_block}

文字起こし(セグメントid付き — これを使って spine を組む):
{transcript_block}

Selected assets:
{json.dumps(source_assets, ensure_ascii=False, indent=2)}

Brief / existing timeline:
{json.dumps(timeline, ensure_ascii=False, indent=2)}
""".strip()

    async def run_dan(prompt_text: str) -> str:
        from app.agent.cli_runner import process_message_cli
        chunks: list[str] = []
        async for event in process_message_cli(
            room_id=room_id,
            user_id=user_id,
            content=prompt_text,
            project_title=str(instruction.get("content_title") or "Production"),
            project_description=str(timeline.get("brief") or instruction.get("brief") or ""),
            project_status="in_progress",
            skip_save=True,
            skip_resume=True,
            cwd="D:/dan-workspace",
        ):
            et = str(event.get("type") or "")
            if et in {"text", "reasoning", "tool_use", "result", "error"}:
                _append_job_event(room_id, job_id, {
                    "type": et,
                    "text": str(event.get("text") or event.get("message") or "")[:4000],
                    "name": event.get("name") or event.get("tool_name"),
                })
            if et in {"text", "result"} and event.get("text"):
                chunks.append(str(event.get("text")))
        return "\n".join(chunks).strip()

    output = asyncio.run(run_dan(prompt))
    decisions = _extract_json_object(output)
    if not isinstance(decisions, dict) or not decisions.get("spine"):
        decisions = None
    return decisions, transcripts


def _assemble_sequence_from_decisions(
    decisions: dict[str, Any],
    transcripts: dict[str, Any],
    room_id: str,
    fmt: str,
) -> dict[str, Any] | None:
    """Deterministically build the exact timeline sequence from Dan's DECISIONS plus the
    Whisper segment timestamps. Dan never computes timeline seconds — this does."""
    import os
    PIP_POS = {"x": 0.30, "y": 0.655, "width": 0.40, "height": 0.30}

    seg_by_id: dict[str, Any] = {}
    for _aid, t in transcripts.items():
        for s in (t.get("segments") or []):
            seg_by_id[str(s.get("id"))] = s

    # Restatement safety net: if audio_check flagged a 言い直し pair and BOTH takes ended
    # up in the spine, deterministically drop the earlier take (policy: keep the later,
    # complete one) even when Dan failed to. Maps the detector's time ranges to seg ids.
    spine = decisions.get("spine") or []
    spine_ids = {str(it.get("segment_id") if isinstance(it, dict) else it) for it in spine}

    def _seg_at(aid: str, start: float, end: float) -> str | None:
        for sid, s in seg_by_id.items():
            if str(s.get("asset_id")) != aid:
                continue
            ss, se = float(s.get("start") or 0), float(s.get("end") or 0)
            if min(end, se) - max(start, ss) > 0.2:  # meaningful overlap
                return sid
        return None

    drop_earlier: set[str] = set()
    for _aid, t in transcripts.items():
        for r in (t.get("restatements") or []):
            f0, s0 = r.get("first") or {}, r.get("second") or {}
            fid = _seg_at(str(t.get("asset_id")), float(f0.get("start") or 0), float(f0.get("end") or 0))
            sid2 = _seg_at(str(t.get("asset_id")), float(s0.get("start") or 0), float(s0.get("end") or 0))
            if fid and sid2 and fid in spine_ids and sid2 in spine_ids and fid != sid2:
                drop_earlier.add(fid)

    assets = _read_assets(room_id)
    dur_by_id: dict[str, float] = {}
    for a in assets:
        m = a.get("metadata") if isinstance(a.get("metadata"), dict) else {}
        try:
            dur_by_id[str(a.get("id"))] = float(m.get("duration") or 0)
        except Exception:
            pass

    n = {"v": 0, "o": 0, "c": 0, "a": 0, "e": 0}
    def _cid(kind: str) -> str:
        n[kind] += 1
        return f"clip_{kind}{n[kind]:03d}"

    # Word-level editing (Descript-style). Internal pauses longer than SIL are dropped
    # (silence compression); Dan's `cuts` (restatement/filler spans it chose to remove) are
    # honored too. SIL default lives in code; Dan may override via decisions.silence_threshold
    # when the user asks for tighter/looser pacing. Each kept segment yields 1+ word-runs,
    # each a clip; runs are placed contiguously (no drift, no boundary replay).
    try:
        SIL = float(decisions.get("silence_threshold") or os.environ.get("DAN_PLAN_SILENCE_GAP", "0.45"))
    except Exception:
        SIL = 0.45
    SIL = max(0.2, SIL)
    LEAD, TAIL = 0.06, 0.10  # tiny pads around each kept word-run

    cuts_by_asset: dict[str, list[tuple[float, float]]] = {}
    for c in (decisions.get("cuts") or []):
        if not isinstance(c, dict):
            continue
        caid = str(c.get("asset_id") or "")
        try:
            cstart, cend = float(c.get("start")), float(c.get("end"))
        except Exception:
            continue
        if cend > cstart:
            cuts_by_asset.setdefault(caid, []).append((cstart, cend))

    def _in_cut(aid: str, t: float) -> bool:
        return any(cs <= t <= ce for cs, ce in cuts_by_asset.get(aid, []))

    def _runs_for_segment(s: dict[str, Any]) -> list[tuple[float, float]]:
        """Contiguous kept-word runs in source time: split at internal silences > SIL and
        drop words inside Dan's cut spans. Falls back to the whole segment if no word data."""
        aid = str(s.get("asset_id") or "")
        words = s.get("words") or []
        if not words:
            a, b = float(s.get("start") or 0), float(s.get("end") or 0)
            return [] if _in_cut(aid, (a + b) / 2) else [(a, b)]
        runs: list[tuple[float, float]] = []
        cs = ce = None
        for w in words:
            ws, we = float(w.get("start") or 0), float(w.get("end") or 0)
            if _in_cut(aid, (ws + we) / 2):
                if cs is not None:
                    runs.append((cs, ce)); cs = ce = None
                continue
            if cs is None:
                cs, ce = ws, we
            elif ws - ce > SIL:           # internal silence -> split (drop the gap)
                runs.append((cs, ce)); cs, ce = ws, we
            else:
                ce = we
        if cs is not None:
            runs.append((cs, ce))
        return runs

    # Resolve kept spine items (after the restatement drop).
    kept: list[tuple[str, dict[str, Any], str | None]] = []
    for item in spine:
        sid = str(item.get("segment_id") if isinstance(item, dict) else item)
        if sid in drop_earlier:
            continue
        s = seg_by_id.get(sid)
        if not s:
            continue
        cap = item.get("caption") if isinstance(item, dict) else None
        kept.append((sid, s, cap if isinstance(cap, str) else None))

    # Pass 1: lay out word-level pieces contiguously. seg_span tracks each segment's overall
    # timeline span (first piece -> last piece) for captions + overlay coverage.
    pieces: list[dict[str, Any]] = []
    seg_span: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    cursor = 0.0
    prev_end_by_asset: dict[str, float] = {}
    for sid, s, cap in kept:
        aid = str(s.get("asset_id") or "")
        runs = _runs_for_segment(s)
        if not runs:
            continue
        ad = dur_by_id.get(aid) or 0.0
        seg_ts = seg_te = None
        for rs, re in runs:
            src_start = max(0.0, rs - LEAD)
            src_end = re + TAIL
            pe = prev_end_by_asset.get(aid)
            if pe is not None and src_start < pe:
                src_start = pe
            if ad:
                src_end = min(src_end, ad)
            if src_end <= src_start:
                src_end = src_start + 0.05
            out_dur = max(0.05, round(src_end - src_start, 3))
            ts = round(cursor, 3)
            te = round(cursor + out_dur, 3)
            pieces.append({
                "sid": sid, "asset_id": aid,
                "source_start": round(src_start, 3), "source_end": round(src_end, 3),
                "timeline_start": ts, "timeline_end": te,
            })
            prev_end_by_asset[aid] = src_end
            cursor = te
            if seg_ts is None:
                seg_ts = ts
            seg_te = te
        if seg_ts is None:
            continue
        seg_span[sid] = {
            "timeline_start": seg_ts, "timeline_end": seg_te,
            "caption": (cap.strip() if cap else str(s.get("text") or "").strip()),
        }
        order.append(sid)
    if not pieces:
        return None
    total = round(pieces[-1]["timeline_end"], 3)

    # Determine which spine segments are covered by a screen overlay.
    overlays = []
    covered: set[str] = set()
    for ov in (decisions.get("screen_overlays") or []):
        frm, to = str(ov.get("from_segment") or ""), str(ov.get("to_segment") or "")
        if frm not in seg_span or to not in seg_span:
            continue
        i0 = order.index(frm) if frm in order else None
        i1 = order.index(to) if to in order else None
        if i0 is None or i1 is None or i1 < i0:
            continue
        span_ids = order[i0:i1 + 1]
        overlays.append({
            "screen_asset_id": str(ov.get("screen_asset_id") or ""),
            "screen_source_start": float(ov.get("screen_source_start") or 0),
            "screen_source_end": float(ov.get("screen_source_end") or 0),
            "span_start": seg_span[frm]["timeline_start"], "span_end": seg_span[to]["timeline_end"],
            "main_as_pip": bool(ov.get("main_as_pip", True)),
        })
        for sid in span_ids:
            covered.add(sid)

    video_clips: list[dict[str, Any]] = []
    overlay_clips: list[dict[str, Any]] = []
    caption_clips: list[dict[str, Any]] = []
    audio_clips: list[dict[str, Any]] = []
    effect_clips: list[dict[str, Any]] = []

    # Pass 2: each word-piece -> visual (fullscreen or PiP) + audio. The visual and its
    # audio share a link_id so the editor can move/trim them together (A/V link).
    n["lnk"] = 0
    for p in pieces:
        n["lnk"] += 1
        link_id = f"lnk{n['lnk']:03d}"
        base = {
            "asset_id": p["asset_id"],
            "source_start": p["source_start"], "source_end": p["source_end"],
            "timeline_start": p["timeline_start"], "timeline_end": p["timeline_end"],
            "muted": True, "locked": False, "role": "main", "auto_edit_reason": "spine",
            "link_id": link_id,
        }
        if p["sid"] in covered:
            overlay_clips.append({**base, "id": _cid("o"), "track": "overlay",
                                  "composition": "pip", "position": dict(PIP_POS), "layer": 1})
        else:
            video_clips.append({**base, "id": _cid("v"), "track": "video",
                                "composition": "fullscreen", "layer": 0})
        audio_clips.append({
            "id": _cid("a"), "asset_id": p["asset_id"], "track": "audio", "role": "dialogue",
            "source_start": p["source_start"], "source_end": p["source_end"],
            "timeline_start": p["timeline_start"], "timeline_end": p["timeline_end"],
            "link_id": link_id,
        })
    # Captions: one per kept (non-overlay) segment, spanning its full timeline range.
    for sid in order:
        if sid in covered:
            continue
        sp = seg_span[sid]
        if sp["caption"]:
            caption_clips.append({"id": _cid("c"), "text": sp["caption"], "track": "caption",
                                  "timeline_start": sp["timeline_start"], "timeline_end": sp["timeline_end"]})

    # Pass 3: screen background clips (fullscreen base) under each overlay span.
    for ov in overlays:
        ss = ov["screen_source_start"]
        se = ov["screen_source_end"]
        if se <= ss:
            se = ss + (ov["span_end"] - ov["span_start"])
        ad = dur_by_id.get(ov["screen_asset_id"]) or 0.0
        if ad:
            se = min(se, ad)
        video_clips.append({
            "id": _cid("v"), "asset_id": ov["screen_asset_id"], "track": "video",
            "source_start": round(ss, 3), "source_end": round(se, 3),
            "timeline_start": ov["span_start"], "timeline_end": ov["span_end"],
            "muted": True, "locked": False, "role": "screen",
            "composition": "background", "layer": 0, "auto_edit_reason": "screen_overlay",
        })

    # Pass 4: blur regions → effect clips, mapping screen source time → timeline time.
    for b in (decisions.get("blur") or []):
        region = b.get("region") if isinstance(b.get("region"), dict) else None
        if not region:
            continue
        baid = str(b.get("asset_id") or "")
        bs = float(b.get("source_start") or 0)
        be = float(b.get("source_end") or 0)
        ov = next((o for o in overlays if o["screen_asset_id"] == baid and o["screen_source_end"] > o["screen_source_start"]), None)
        if ov:
            ss, se = ov["screen_source_start"], ov["screen_source_end"]
            span = ov["span_end"] - ov["span_start"]
            def _map(x: float) -> float:
                return ov["span_start"] + (max(ss, min(se, x)) - ss) / (se - ss) * span
            ts, te = round(_map(bs), 3), round(_map(be if be > bs else se), 3)
        else:
            ts, te = 0.0, total
        if te <= ts:
            te = round(ts + 0.5, 3)
        effect_clips.append({
            "id": _cid("e"), "track": "effect", "region": region,
            "style": str(b.get("style") or "soft"),
            "timeline_start": ts, "timeline_end": te,
        })

    return {
        "version": 1,
        "format": fmt,
        "duration": total,
        "generated_by": "dan_plan",
        "tracks": [
            {"id": "video_1", "type": "video", "label": "Main video", "clips": video_clips},
            {"id": "overlay_1", "type": "overlay", "label": "Overlay/PiP", "clips": overlay_clips},
            {"id": "caption_1", "type": "caption", "label": "Captions", "clips": caption_clips},
            {"id": "audio_1", "type": "audio", "label": "Audio", "clips": audio_clips},
            {"id": "effects_1", "type": "effect", "label": "Blur/Effects", "clips": effect_clips},
        ],
    }


def _run_production_job(room_id: str, job_id: str, content_id: str, instruction: dict[str, Any], user_id: str) -> None:
    _update_job(room_id, job_id, {"status": "running"})
    _update_content(room_id, content_id, {"status": "running", "timeline": instruction.get("timeline") or {}})
    job_dir = _room_dir(room_id) / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    instruction_path = job_dir / "timeline_instruction.json"
    task_path = job_dir / "DAN_TASK.md"
    dan_timeline_path = job_dir / "dan_timeline.json"
    try:
        instruction_path.write_text(json.dumps(instruction, ensure_ascii=False, indent=2), encoding="utf-8")
        annotations = ((instruction.get("timeline") or {}).get("annotations") or [])
        mode = instruction.get("mode") or "timeline_instruction"
        source_assets = instruction.get("source_assets") or []
        brief = instruction.get("brief") or ((instruction.get("timeline") or {}).get("brief") if isinstance(instruction.get("timeline"), dict) else "")
        task_lines = [
            "# Production Job",
            "",
            "Use the available production, studio, and post-production workflows for this video edit.",
            "Make the best edit decisions from the selected assets, brief, and timeline state.",
            "The production-state JSON is the UI handoff, not a restriction on how you work.",
            "",
            f"- content_id: {content_id}",
            f"- mode: {mode}",
            f"- annotation_count: {len(annotations)}",
            f"- instruction_json: {instruction_path}",
            "",
            "## Brief",
            "",
            str(brief or "").strip() or "(none)",
            "",
            "## Source Assets",
            "",
        ]
        for asset in source_assets:
            if isinstance(asset, dict):
                task_lines.append(
                    f"- {asset.get('id')}: {asset.get('filename') or asset.get('local_path') or ''} "
                    f"({asset.get('kind')}, {asset.get('source_type')})"
                )
                if asset.get("local_path"):
                    task_lines.append(f"  - local_path: {asset.get('local_path')}")
                if asset.get("proxy_path"):
                    task_lines.append(f"  - proxy_path: {asset.get('proxy_path')}")
        task_lines.extend([
            "",
            "## Required Output",
            "",
            (
                "Produce the best production-state handoff for the workspace. Create previews or helper files if they are useful, and always write the final state JSON for the UI."
                if mode == "dan_edit"
                else "Render a revised video only for the requested timeline/export job."
            ),
            "",
            "## Timeline Notes",
            "",
        ])
        for index, annotation in enumerate(annotations, start=1):
            task_lines.append(
                f"{index}. {annotation.get('intent')} {annotation.get('start')}s-{annotation.get('end')}s: {annotation.get('note') or ''}"
            )
        task_path.write_text("\n".join(task_lines), encoding="utf-8")
        _append_job_event(room_id, job_id, {"type": "status", "text": "Dan production job started."})
        sequence_result = None
        timeline_result = None
        render_result = None
        dan_render_path = job_dir / f"{job_id}_dan_render.mp4"
        if mode == "dan_edit":
            timeline_result = _build_dan_timeline(
                room_id, user_id, job_id, instruction, instruction_path, dan_timeline_path, dan_render_path
            )
            if timeline_result:
                sequence_result = timeline_result.get("sequence") if isinstance(timeline_result.get("sequence"), dict) else None
            # Primary deliverable is the finished video Dan rendered. Register it so the UI shows it.
            if dan_render_path.exists() and dan_render_path.stat().st_size > 0:
                output_asset = _add_generated_video_asset(
                    room_id, dan_render_path, filename=f"dan_{content_id[:8]}_{job_id[:8]}.mp4"
                )
                _attach_output_asset(room_id, content_id, job_id, output_asset, dan_render_path, kind="dan_render")
                probed = _probe_video(dan_render_path)
                render_result = {
                    "output_asset_id": output_asset["id"],
                    "output_path": str(dan_render_path),
                    "output_url": output_asset.get("proxy_url"),
                    "render_size": f"{probed.get('width')}x{probed.get('height')}",
                }
                _append_job_event(room_id, job_id, {"type": "status", "text": "Dan rendered and registered the finished video."})
            if not render_result and not sequence_result:
                raise RuntimeError("Dan did not produce a rendered video or an editable timeline")
        elif mode == "dan_plan":
            # Timeline-first: Dan emits editing DECISIONS, code assembles the exact
            # sequence. No MP4 is rendered (the timeline is the deliverable).
            decisions, transcripts = _build_dan_plan(room_id, user_id, job_id, instruction, instruction_path)
            if not decisions:
                raise RuntimeError("Dan did not produce usable editing decisions")
            fmt = str((instruction.get("timeline") or {}).get("format") or instruction.get("format") or "9:16")
            sequence_result = _assemble_sequence_from_decisions(decisions, transcripts, room_id, fmt)
            if not sequence_result:
                raise RuntimeError("Could not assemble a timeline from the decisions")
            timeline_result = {"sequence": sequence_result}
            dan_timeline_path.write_text(
                json.dumps({"decisions": decisions, "sequence": sequence_result}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            _append_job_event(room_id, job_id, {"type": "status", "text": "編集判断からタイムラインを組み立てました（MP4は未生成）。"})
        if timeline_result and sequence_result:
            timeline = dict(instruction.get("timeline") or {})
            timeline.update(timeline_result)
            timeline["sequence"] = sequence_result
            instruction["timeline"] = timeline
            instruction_path.write_text(json.dumps(instruction, ensure_ascii=False, indent=2), encoding="utf-8")
            _update_content(room_id, content_id, {"timeline": timeline})
        if mode in {"render_timeline", "export", "blur_render"}:
            render_result = _render_sequence_job(room_id, job_id, content_id, instruction, job_dir)
            if not render_result:
                render_result = _render_blur_job(room_id, job_id, content_id, instruction, job_dir)
        result = {
            "instruction_path": str(instruction_path),
            "task_path": str(task_path),
            "dan_timeline_path": str(dan_timeline_path) if mode == "dan_edit" else None,
            "message": (
                "Video render completed."
                if render_result
                else "Editable sequence prepared." if sequence_result
                else "Dan task package prepared. Execution handoff is ready."
            ),
        }
        if sequence_result:
            result["sequence_created"] = True
            result["sequence_clip_count"] = sum(len(track.get("clips") or []) for track in sequence_result.get("tracks", []))
        if render_result:
            result.update(render_result)
        _append_job_event(room_id, job_id, {"type": "status", "text": result["message"]})
        _update_job(room_id, job_id, {"status": "done", "result": result, "error": None})
        _update_content(room_id, content_id, {"status": "ready", "timeline": instruction.get("timeline") or {}})
    except Exception as exc:
        _append_job_event(room_id, job_id, {"type": "error", "text": str(exc)})
        _update_job(room_id, job_id, {"status": "failed", "error": str(exc)})
        _update_content(room_id, content_id, {"status": "failed"})


def _kind_for(uri: str) -> Literal["video", "image", "audio", "file"]:
    suffix = Path(uri.split("?", 1)[0]).suffix.lower()
    if suffix in VIDEO_SUFFIXES:
        return "video"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    return "file"


def _resolve_local_uri(uri: str) -> Path:
    value = uri.strip().strip('"')
    if value.startswith("/api/v1/files/"):
        return (UPLOADS_DIR / value.rstrip("/").split("/")[-1]).resolve()
    path = Path(value)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path)
    resolved = path.resolve()
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="Asset file not found")
    if not resolved.is_file():
        raise HTTPException(status_code=400, detail="Asset path is not a file")
    return resolved


def _range_file_response(path: Path, request: Request):
    file_size = path.stat().st_size
    content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    range_header = request.headers.get("range")

    if not range_header:
        return FileResponse(path, media_type=content_type, headers={"Accept-Ranges": "bytes"})

    try:
        units, value = range_header.split("=", 1)
        if units.strip().lower() != "bytes":
            raise ValueError("unsupported range unit")
        start_s, end_s = value.split("-", 1)
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else file_size - 1
        start = max(0, min(start, file_size - 1))
        end = max(start, min(end, file_size - 1))
    except Exception:
        raise HTTPException(status_code=416, detail="Invalid Range header")

    chunk_size = end - start + 1

    def iterator():
        with path.open("rb") as file:
            file.seek(start)
            remaining = chunk_size
            while remaining > 0:
                chunk = file.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(
        iterator(),
        status_code=206,
        media_type=content_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(chunk_size),
        },
    )


def _probe_video(path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                _ffprobe(),
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        raw = json.loads(result.stdout or "{}")
    except Exception as exc:
        return {"probe_error": str(exc)}

    video_stream = next((s for s in raw.get("streams", []) if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in raw.get("streams", []) if s.get("codec_type") == "audio"), {})
    return {
        "duration": float(raw.get("format", {}).get("duration") or 0),
        "size": int(raw.get("format", {}).get("size") or path.stat().st_size),
        "width": int(video_stream.get("width") or 0),
        "height": int(video_stream.get("height") or 0),
        "fps": video_stream.get("r_frame_rate"),
        "video_codec": video_stream.get("codec_name"),
        "audio_codec": audio_stream.get("codec_name"),
    }


def _run_proxy_job(room_id: str, asset_id: str, source_path: str) -> None:
    src = Path(source_path)
    out_dir = _room_dir(room_id)
    proxy = out_dir / f"{asset_id}_proxy.mp4"
    thumb = out_dir / f"{asset_id}_thumb.jpg"

    try:
        creationflags = 0
        if hasattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS"):
            creationflags = subprocess.BELOW_NORMAL_PRIORITY_CLASS  # type: ignore[attr-defined]

        subprocess.run(
            [
                _ffmpeg(),
                "-y",
                "-i",
                str(src),
                "-vf",
                "scale=-2:720",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "28",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-movflags",
                "+faststart",
                str(proxy),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            check=True,
        )
        subprocess.run(
            [
                _ffmpeg(),
                "-y",
                "-ss",
                "1",
                "-i",
                str(src),
                "-vframes",
                "1",
                "-vf",
                "scale=-2:360",
                str(thumb),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            check=False,
        )
        _update_asset(
            room_id,
            asset_id,
            {
                "status": "proxy_ready",
                "proxy_path": str(proxy),
                "proxy_url": f"/api/v1/production-assets/media?room_id={room_id}&asset_id={asset_id}&variant=proxy",
                "thumbnail_path": str(thumb) if thumb.exists() else None,
                "thumbnail_url": f"/api/v1/production-assets/media?room_id={room_id}&asset_id={asset_id}&variant=thumbnail"
                if thumb.exists()
                else None,
                "metadata": _probe_video(src),
                "error": None,
            },
        )
    except Exception as exc:
        _update_asset(room_id, asset_id, {"status": "failed", "error": str(exc)})


@router.get("", response_model=list[ProductionAsset])
async def list_assets(
    room_id: str = Query(...),
    current_user: TokenData = Depends(get_current_user),
):
    return _read_assets(room_id)


@router.post("/register", response_model=ProductionAsset)
async def register_asset(
    data: RegisterAssetRequest,
    background_tasks: BackgroundTasks,
    current_user: TokenData = Depends(get_current_user),
):
    clean_uri = data.uri.strip().strip('"').strip("'")
    kind = _kind_for(clean_uri)
    now = datetime.now(timezone.utc).isoformat()
    asset_id = str(uuid.uuid4())
    local_path: str | None = None
    metadata: dict[str, Any] = {}
    status = "registered"

    if data.source_type in {"local_path", "nas_path", "upload", "generated"}:
        resolved = _resolve_local_uri(clean_uri)
        local_path = str(resolved)
        if kind == "video":
            metadata = _probe_video(resolved)
            status = "processing" if data.make_proxy else "registered"
    elif data.source_type == "cloud_url":
        status = "registered"

    asset = ProductionAsset(
        id=asset_id,
        room_id=data.room_id,
        kind=kind,
        source_type=data.source_type,
        original_uri=clean_uri,
        local_path=local_path,
        filename=Path(clean_uri.split("?", 1)[0]).name,
        status=status,  # type: ignore[arg-type]
        metadata=metadata,
        created_at=now,
        updated_at=now,
    ).model_dump()

    assets = _read_assets(data.room_id)
    assets.append(asset)
    _write_assets(data.room_id, assets)

    if data.make_proxy and kind == "video" and local_path:
        background_tasks.add_task(_run_proxy_job, data.room_id, asset_id, local_path)

    return asset


@router.post("/{asset_id}/proxy", response_model=ProductionAsset)
async def create_proxy(
    asset_id: str,
    background_tasks: BackgroundTasks,
    room_id: str = Query(...),
    current_user: TokenData = Depends(get_current_user),
):
    assets = _read_assets(room_id)
    asset = next((a for a in assets if a.get("id") == asset_id), None)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset.get("kind") != "video" or not asset.get("local_path"):
        raise HTTPException(status_code=400, detail="Only local video assets can be proxied")
    _update_asset(room_id, asset_id, {"status": "processing"})
    background_tasks.add_task(_run_proxy_job, room_id, asset_id, asset["local_path"])
    return next(a for a in _read_assets(room_id) if a.get("id") == asset_id)


@router.get("/media")
async def get_asset_media(
    request: Request,
    room_id: str = Query(...),
    asset_id: str = Query(...),
    variant: Literal["original", "proxy", "thumbnail"] = Query("proxy"),
):
    asset = next((a for a in _read_assets(room_id) if a.get("id") == asset_id), None)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    key = {
        "original": "local_path",
        "proxy": "proxy_path",
        "thumbnail": "thumbnail_path",
    }[variant]
    value = asset.get(key)
    if not value:
        raise HTTPException(status_code=404, detail=f"{variant} is not available")
    path = Path(value).resolve()
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Media file not found")
    return _range_file_response(path, request)


@router.post("/upload", response_model=ProductionAsset)
async def upload_asset(
    background_tasks: BackgroundTasks,
    room_id: str = Query(...),
    file: UploadFile = File(...),
    current_user: TokenData = Depends(get_current_user),
):
    room_dir = _room_dir(room_id)
    original_name = file.filename or f"asset-{uuid.uuid4()}"
    suffix = Path(original_name).suffix
    saved_name = f"{uuid.uuid4()}{suffix}"
    saved_path = room_dir / saved_name

    size = 0
    with saved_path.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            out.write(chunk)

    request = RegisterAssetRequest(
        room_id=room_id,
        uri=str(saved_path),
        source_type="upload",
        make_proxy=True,
    )
    asset = await register_asset(request, background_tasks, current_user)
    asset["filename"] = original_name
    metadata = asset.get("metadata") or {}
    metadata["upload_size"] = size
    asset["metadata"] = metadata
    _update_asset(room_id, asset["id"], {"filename": original_name, "metadata": metadata})
    return asset


@router.get("/contents", response_model=list[ProductionContent])
async def list_contents(
    room_id: str = Query(...),
    current_user: TokenData = Depends(get_current_user),
):
    return _read_contents(room_id)


@router.post("/contents", response_model=ProductionContent)
async def create_content(
    data: CreateContentRequest,
    current_user: TokenData = Depends(get_current_user),
):
    now = datetime.now(timezone.utc).isoformat()
    source_asset_ids = data.timeline.get("source_asset_ids") if isinstance(data.timeline, dict) else None
    asset_ids = data.asset_ids or ([str(asset_id) for asset_id in source_asset_ids] if isinstance(source_asset_ids, list) else [])
    content = ProductionContent(
        id=str(uuid.uuid4()),
        room_id=data.room_id,
        title=data.title.strip() or "Untitled content",
        format=data.format,
        asset_ids=asset_ids,
        timeline=data.timeline,
        created_at=now,
        updated_at=now,
    ).model_dump()
    contents = _read_contents(data.room_id)
    contents.append(content)
    _write_contents(data.room_id, contents)
    return content


@router.patch("/contents/{content_id}", response_model=ProductionContent)
async def update_content(
    content_id: str,
    data: SaveContentRequest,
    room_id: str = Query(...),
    current_user: TokenData = Depends(get_current_user),
):
    contents = _read_contents(room_id)
    now = datetime.now(timezone.utc).isoformat()
    for content in contents:
        if content.get("id") == content_id:
            if data.timeline is not None:
                content["timeline"] = data.timeline
            if data.asset_ids is not None:
                content["asset_ids"] = data.asset_ids
            if data.status is not None:
                content["status"] = data.status
            content["updated_at"] = now
            _write_contents(room_id, contents)
            return content
    raise HTTPException(status_code=404, detail="Content not found")


@router.delete("/contents/{content_id}")
async def delete_content(
    content_id: str,
    room_id: str = Query(...),
    current_user: TokenData = Depends(get_current_user),
):
    contents = _read_contents(room_id)
    target_content = next((content for content in contents if content.get("id") == content_id), None)
    next_contents = [content for content in contents if content.get("id") != content_id]
    if len(next_contents) == len(contents):
        raise HTTPException(status_code=404, detail="Content not found")
    _write_contents(room_id, next_contents)
    jobs = _read_jobs(room_id)
    removed_jobs = [job for job in jobs if job.get("content_id") == content_id]
    _write_jobs(room_id, [job for job in jobs if job.get("content_id") != content_id])
    for job in removed_jobs:
        job_id = str(job.get("id") or "")
        if not job_id:
            continue
        job_dir = (_room_dir(room_id) / "jobs" / job_id).resolve()
        try:
            if job_dir.exists() and job_dir.is_dir() and _room_dir(room_id).resolve() in job_dir.parents:
                shutil.rmtree(job_dir)
        except Exception:
            pass

    output_asset_ids = {
        str(output.get("asset_id"))
        for output in ((target_content or {}).get("outputs") or [])
        if isinstance(output, dict) and output.get("asset_id")
    }
    if output_asset_ids:
        assets = _read_assets(room_id)
        kept_assets = []
        for asset in assets:
            if str(asset.get("id")) in output_asset_ids and asset.get("source_type") == "generated":
                _remove_asset_files(asset)
                continue
            kept_assets.append(asset)
        _write_assets(room_id, kept_assets)
    return {"ok": True}


@router.post("/jobs", response_model=ProductionJob)
async def create_job(
    data: CreateJobRequest,
    background_tasks: BackgroundTasks,
    current_user: TokenData = Depends(get_current_user),
):
    contents = _read_contents(data.room_id)
    if not any(content.get("id") == data.content_id for content in contents):
        raise HTTPException(status_code=404, detail="Content not found")
    now = datetime.now(timezone.utc).isoformat()
    job = ProductionJob(
        id=str(uuid.uuid4()),
        room_id=data.room_id,
        content_id=data.content_id,
        instruction=data.instruction,
        created_at=now,
        updated_at=now,
    ).model_dump()
    jobs = _read_jobs(data.room_id)
    jobs.append(job)
    _write_jobs(data.room_id, jobs)
    background_tasks.add_task(_run_production_job, data.room_id, job["id"], data.content_id, data.instruction, current_user.user_id)
    return job


@router.get("/jobs", response_model=list[ProductionJob])
async def list_jobs(
    room_id: str = Query(...),
    content_id: str | None = Query(None),
    current_user: TokenData = Depends(get_current_user),
):
    jobs = _read_jobs(room_id)
    if content_id:
        jobs = [job for job in jobs if job.get("content_id") == content_id]
    return jobs


@router.get("/jobs/{job_id}/events")
async def list_job_events(
    job_id: str,
    room_id: str = Query(...),
    current_user: TokenData = Depends(get_current_user),
):
    jobs = _read_jobs(room_id)
    if not any(str(job.get("id")) == job_id for job in jobs):
        raise HTTPException(status_code=404, detail="Job not found")
    path = _job_events_path(room_id, job_id)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-200:]:
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                events.append(value)
        except Exception:
            continue
    return events
