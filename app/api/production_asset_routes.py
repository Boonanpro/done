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
from difflib import SequenceMatcher
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


def _caption_similarity(left: str | None, right: str | None) -> float:
    lval = re.sub(r"\s+", "", left or "")
    rval = re.sub(r"\s+", "", right or "")
    if not lval or not rval:
        return 0.0
    if lval in rval or rval in lval:
        return 1.0
    return SequenceMatcher(None, lval, rval).ratio()


def _asset_source_path(asset: dict[str, Any]) -> Path:
    source_value = asset.get("proxy_path") or asset.get("local_path")
    if not source_value:
        raise RuntimeError(f"Video asset has no local path: {asset.get('id')}")
    path = Path(source_value).resolve()
    if not path.exists():
        raise RuntimeError(f"Video file not found: {path}")
    return path


def _detect_nonsilent_ranges(path: Path, duration: float, *, limit_seconds: float = 75.0) -> list[tuple[float, float]]:
    if duration <= 0:
        return []
    analyze_until = min(duration, limit_seconds)
    try:
        result = subprocess.run(
            [
                _ffmpeg(),
                "-hide_banner",
                "-t",
                f"{analyze_until:.3f}",
                "-i",
                str(path),
                "-af",
                "silencedetect=n=-34dB:d=0.45",
                "-f",
                "null",
                "-",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=90,
            check=False,
        )
    except Exception:
        return []

    silence_starts: list[float] = []
    silences: list[tuple[float, float]] = []
    for line in (result.stderr or "").splitlines():
        start_match = re.search(r"silence_start:\s*([0-9.]+)", line)
        if start_match:
            silence_starts.append(float(start_match.group(1)))
            continue
        end_match = re.search(r"silence_end:\s*([0-9.]+)", line)
        if end_match and silence_starts:
            silences.append((silence_starts.pop(0), float(end_match.group(1))))
    for start in silence_starts:
        silences.append((start, analyze_until))

    ranges: list[tuple[float, float]] = []
    cursor = 0.0
    for silence_start, silence_end in silences:
        if silence_start - cursor >= 0.65:
            ranges.append((max(0.0, cursor - 0.08), min(analyze_until, silence_start + 0.08)))
        cursor = max(cursor, silence_end)
    if analyze_until - cursor >= 0.65:
        ranges.append((max(0.0, cursor - 0.08), analyze_until))

    merged: list[tuple[float, float]] = []
    for start, end in ranges:
        if not merged or start - merged[-1][1] > 0.25:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], end)
    return [(round(start, 3), round(end, 3)) for start, end in merged if end - start >= 0.65]


def _transcribe_video_segments(path: Path, duration: float, *, limit_seconds: float = 90.0) -> list[dict[str, Any]]:
    analyze_until = min(max(duration, 0.0), limit_seconds)
    if analyze_until <= 0:
        return []
    model_name = os.environ.get("DAN_WHISPER_MODEL", "base")
    safe_model_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", model_name)
    cache_path = path.with_name(f"{path.stem}_whisper_v2_{safe_model_name}_{int(analyze_until)}s.json")
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, list):
                return [item for item in cached if isinstance(item, dict)]
        except Exception:
            pass

    audio_path = path.with_name(f"{path.stem}_whisper_{int(analyze_until)}s.wav")
    try:
        creationflags = 0
        if hasattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS"):
            creationflags = subprocess.BELOW_NORMAL_PRIORITY_CLASS  # type: ignore[attr-defined]
        subprocess.run(
            [
                _ffmpeg(),
                "-y",
                "-t",
                f"{analyze_until:.3f}",
                "-i",
                str(path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(audio_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            timeout=120,
            check=True,
        )
        import whisper  # type: ignore

        ffmpeg_dir = str(Path(_ffmpeg()).parent)
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
        model = whisper.load_model(model_name)
        result = model.transcribe(str(audio_path), language="ja", fp16=False, verbose=False)
        segments: list[dict[str, Any]] = []
        for segment in result.get("segments") or []:
            text = str(segment.get("text") or "").strip()
            meaningful = re.sub(r"[\s?？!！。.,、…]+", "", text)
            start = max(0.0, float(segment.get("start") or 0))
            end = min(analyze_until, float(segment.get("end") or 0))
            if not text or len(meaningful) <= 2 or end - start < 0.35:
                continue
            segments.append({"start": round(start, 3), "end": round(end, 3), "text": text})
        cache_path.write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
        return segments
    except Exception:
        return []


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


def _render_sequence_job(room_id: str, job_id: str, content_id: str, instruction: dict[str, Any], job_dir: Path) -> dict[str, Any] | None:
    timeline = instruction.get("timeline") if isinstance(instruction.get("timeline"), dict) else {}
    sequence = timeline.get("sequence") if isinstance(timeline, dict) else None
    if not isinstance(sequence, dict):
        return None

    clips = _sequence_video_clips(sequence)
    if not clips:
        return None

    assets = _assets_by_id(room_id)
    output_width, output_height = _output_size(str(sequence.get("format") or timeline.get("format") or "9:16"))
    out_path = job_dir / f"{job_id}_sequence.mp4"

    command = [_ffmpeg(), "-y"]
    filters: list[str] = []
    concat_parts: list[str] = []
    rendered_count = 0

    for index, clip in enumerate(clips):
        asset_id = str(clip.get("asset_id") or "")
        asset = assets.get(asset_id)
        if not asset or asset.get("kind") != "video":
            continue

        source_path = _asset_source_path(asset)
        metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else _probe_video(source_path)
        source_duration = float(metadata.get("duration") or clip.get("source_duration") or 0)
        source_start = max(0.0, float(clip.get("source_start") or 0))
        source_end = float(clip.get("source_end") or 0)
        if source_end <= source_start:
            source_end = source_duration if source_duration > source_start else source_start + 1.0
        if source_duration > 0:
            source_end = min(source_end, source_duration)
        clip_duration = max(0.05, source_end - source_start)

        input_index = rendered_count
        command.extend(["-i", str(source_path)])
        filters.append(
            f"[{input_index}:v]"
            f"trim=start={source_start:.3f}:end={source_end:.3f},"
            "setpts=PTS-STARTPTS,"
            f"scale={output_width}:{output_height}:force_original_aspect_ratio=increase,"
            f"crop={output_width}:{output_height},"
            "setsar=1,fps=30,format=yuv420p"
            f"[v{rendered_count}]"
        )
        if metadata.get("audio_codec"):
            filters.append(
                f"[{input_index}:a]"
                f"atrim=start={source_start:.3f}:end={source_end:.3f},"
                "asetpts=PTS-STARTPTS,aresample=48000"
                f"[a{rendered_count}]"
            )
        else:
            filters.append(
                f"anullsrc=r=48000:cl=stereo,atrim=duration={clip_duration:.3f},asetpts=PTS-STARTPTS"
                f"[a{rendered_count}]"
            )
        concat_parts.extend([f"[v{rendered_count}]", f"[a{rendered_count}]"])
        rendered_count += 1

    if rendered_count == 0:
        return None

    filters.append("".join(concat_parts) + f"concat=n={rendered_count}:v=1:a=1[vcat][acat]")
    video_out = "vcat"
    for blur_index, annotation in enumerate(_blur_annotations(instruction), start=1):
        data = annotation.get("data") or {}
        x = max(0, min(output_width - 2, round(float(data.get("x") or 0) * output_width)))
        y = max(0, min(output_height - 2, round(float(data.get("y") or 0) * output_height)))
        w = max(2, min(output_width - x, round(float(data.get("width") or 0) * output_width)))
        h = max(2, min(output_height - y, round(float(data.get("height") or 0) * output_height)))
        start = max(0.0, float(annotation.get("start") or 0))
        end = max(start + 0.01, float(annotation.get("end") or (start + 0.5)))
        filters.append(
            f"[{video_out}]split[seqbase{blur_index}][seqcrop{blur_index}src];"
            f"[seqcrop{blur_index}src]crop={w}:{h}:{x}:{y},boxblur=18:2[seqblur{blur_index}];"
            f"[seqbase{blur_index}][seqblur{blur_index}]overlay={x}:{y}:enable='between(t\\,{start:.3f}\\,{end:.3f})'[vseq{blur_index}]"
        )
        video_out = f"vseq{blur_index}"

    captions = _sequence_caption_clips(sequence)
    if captions:
        ass_path = job_dir / f"{job_id}_captions.ass"
        _write_caption_ass(ass_path, captions, output_width, output_height)
        escaped_ass = str(ass_path).replace("\\", "/").replace(":", "\\:")
        filters.append(f"[{video_out}]subtitles='{escaped_ass}'[vcap]")
        video_out = "vcap"

    creationflags = 0
    if hasattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS"):
        creationflags = subprocess.BELOW_NORMAL_PRIORITY_CLASS  # type: ignore[attr-defined]
    elif hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = subprocess.CREATE_NO_WINDOW

    subprocess.run(
        [
            *command,
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[{video_out}]",
            "-map",
            "[acat]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
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

    prompt = f"""
You are DAN, the editor inside the production workspace. Your deliverable is a FINISHED, RENDERED video — not a plan.

Do not treat this as a template-filling task. Inspect the selected assets, reason about the footage, and use your video / post-production skills and the command line (ffmpeg) to actually cut, composite, caption, blur, and finish the video yourself — exactly as you would when a user asks you to make a video in normal chat. The same quality bar applies. A JSON plan without a rendered video is a FAILURE.

Read the full job instruction (brief, blur annotations, audio policy, format) here:
{instruction_path}

PRIMARY DELIVERABLE — render the finished video to this exact path:
{render_path}

RENDER EXECUTION (critical): Run ffmpeg in the FOREGROUND and wait for each call to finish. Do NOT start the render as a background/detached process and then poll for it (do not background it and wait via Monitor) — when your turn ends, detached child processes are killed and the output is lost. If you build the video in segments, run each ffmpeg call in the foreground, then concat to {render_path} as the final foreground step. Keep each ffmpeg call reasonably fast: prefer the proxy files, and if you need ranges deep inside a long source, cut those ranges to short intermediates first instead of re-seeking the full file repeatedly. Before you finish, confirm with ffprobe that {render_path} exists and has the expected duration.

How to work:
1. A Gemini analysis of each clip (timestamped transcript, scene segmentation = talking-head vs screen-operation, and blur candidates) is provided below under "映像分析(Gemini)". Use it as your PRIMARY source for what is said, what happens, and when — this is how you decide caption wording, where to cut silence/restatements, and exactly when to switch to the wipe/screen composition. Gemini's timestamps are only mm:ss-coarse, so for FRAME-ACCURATE cut points — and to find dead air and 言い直し (restatement) takes precisely — run the audio analysis tool on the talking-head source clip:
   python "{audio_check}" "<clip path>"
   It prints (and writes a JSON of) a word-timestamped transcript plus `dead_air` (silence gaps to trim) and `restatements` (adjacent duplicate takes; keep the later, drop the earlier). Use these exact boundaries to plan your cuts. Then confirm with ffprobe / frame extraction. Do not guess from metadata alone.
2. Execute real edits with ffmpeg: trim/cut, multi-clip concat, picture-in-picture / wipe (overlay one camera as a small window over another), captions/telop, audio replacement (e.g. use only the main-camera audio), and blur/mosaic. Every requirement in the brief (PiP/wipe, blur regions, audio source, no-cut sections, caption-free sections) must be honored in the actual rendered pixels — not just described.
3. Honor the requested blur style. If the brief asks for a soft/blended mosaic that follows a moving region, do that; do not settle for a single static hard box if the brief forbids it.
4. VISUAL SELF-VERIFY: extract several frames from {render_path} (intro, each PiP/operation section, each blur section) and confirm the wipe, captions, and blur are actually present and correct. If anything is wrong, fix it and re-render. Never hand off a video you have not visually checked.
4b. AUDIO SELF-VERIFY (do not skip — this is your "ears"): after rendering, run
   python "{audio_check}" "{render_path}"
   If it reports any `dead_air` spans or `restatements`, those are leftover dead silence and duplicate 言い直し takes that survived in the FINAL video. Remove those exact spans — cutting video AND audio together so they stay in sync — and re-render. Repeat until the report shows clean=true (or there is no further improvement after 2 passes). A frame can look perfect while the audio still drags; you only know the pacing is tight by checking it here.
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


def _build_initial_sequence(instruction: dict[str, Any]) -> dict[str, Any]:
    source_assets = [asset for asset in (instruction.get("source_assets") or []) if isinstance(asset, dict)]
    format_value = ((instruction.get("timeline") or {}).get("format") if isinstance(instruction.get("timeline"), dict) else None) or "9:16"
    video_clips: list[dict[str, Any]] = []
    caption_clips: list[dict[str, Any]] = []
    timeline_cursor = 0.0
    max_total = 75.0
    first_asset_budget = 45.0

    for index, asset in enumerate(source_assets):
        if asset.get("kind") != "video":
            continue
        metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
        source_duration = float(metadata.get("duration") or 0) if metadata else 0.0
        if source_duration <= 0:
            source_duration = 12.0

        ranges: list[tuple[float, float, str | None]] = []
        if metadata.get("audio_codec"):
            segments: list[dict[str, Any]] = []
            try:
                source_path = _asset_source_path(asset)
                segments = _transcribe_video_segments(source_path, source_duration)
                if segments:
                    ranges = [
                        (
                            max(0.0, float(segment.get("start") or 0) - 0.12),
                            min(source_duration, float(segment.get("end") or 0) + 0.08),
                            str(segment.get("text") or "").strip() or None,
                        )
                        for segment in segments
                    ]
                else:
                    ranges = [(start, end, None) for start, end in _detect_nonsilent_ranges(source_path, source_duration)]
            except Exception:
                ranges = []

        if not ranges:
            if index == 0:
                ranges = [(0.0, min(18.0, source_duration), None)]
            else:
                ranges = [(0.0, min(12.0, source_duration), None)]

        previous_caption_text: str | None = None
        for range_index, (source_start, source_end, caption_text) in enumerate(ranges):
            if timeline_cursor >= max_total:
                break
            if index == 0 and timeline_cursor >= first_asset_budget and len(source_assets) > 1:
                break
            if caption_text and _caption_similarity(previous_caption_text, caption_text) >= 0.86:
                previous_caption_text = caption_text
                continue
            clip_duration = max(0.05, source_end - source_start)
            if index == 0 and len(source_assets) > 1 and timeline_cursor + clip_duration > first_asset_budget:
                break
            if timeline_cursor + clip_duration > max_total:
                break
            video_clips.append(
                {
                    "id": f"clip_{index + 1}_{range_index + 1}",
                    "asset_id": asset.get("id"),
                    "label": asset.get("filename") or asset.get("local_path") or f"素材 {index + 1}",
                    "source_start": round(source_start, 3),
                    "source_end": round(source_end, 3),
                    "source_duration": source_duration,
                    "timeline_start": round(timeline_cursor, 3),
                    "timeline_end": round(timeline_cursor + clip_duration, 3),
                    "track": "video",
                    "muted": False,
                    "locked": False,
                    "auto_edit_reason": "speech_detected" if metadata.get("audio_codec") else "demo_sample",
                }
            )
            if caption_text:
                previous_caption_text = caption_text
            if caption_text:
                caption_clips.append(
                    {
                        "id": f"caption_{index + 1}_{range_index + 1}",
                        "text": caption_text,
                        "timeline_start": round(timeline_cursor, 3),
                        "timeline_end": round(timeline_cursor + clip_duration, 3),
                        "track": "caption",
                    }
                )
            timeline_cursor += clip_duration
        if timeline_cursor >= max_total:
            break

    return {
        "version": 1,
        "format": format_value,
        "duration": round(timeline_cursor, 3),
        "tracks": [
            {"id": "video_1", "type": "video", "label": "映像", "clips": video_clips},
            {"id": "overlay_1", "type": "overlay", "label": "重ね素材", "clips": []},
            {"id": "caption_1", "type": "caption", "label": "テロップ", "clips": caption_clips},
            {"id": "audio_1", "type": "audio", "label": "音声", "clips": []},
        ],
    }


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
