from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, HTTPException, Query, Request, UploadFile
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


def _clip_transform(clip: dict[str, Any]) -> tuple[float, float, float]:
    """Non-destructive source placement (scale, pan x, pan y). Default (1,0,0) = identity:
    the renderer takes the exact current cover path so unstyled output is byte-identical."""
    t = clip.get("transform") if isinstance(clip.get("transform"), dict) else None
    if not t:
        return 1.0, 0.0, 0.0
    try:
        return float(t.get("scale") or 1.0), float(t.get("x") or 0.0), float(t.get("y") or 0.0)
    except Exception:
        return 1.0, 0.0, 0.0


def _is_identity_transform(scale: float, tx: float, ty: float) -> bool:
    return abs(scale - 1.0) < 1e-4 and abs(tx) < 1e-4 and abs(ty) < 1e-4


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
        if not isinstance(track, dict) or track.get("type") != "caption" or track.get("hidden"):
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


def _hex_to_ass_color(hex_color: str) -> str:
    """#RRGGBB -> ASS &HAABBGGRR (alpha 00 = opaque, byte order reversed)."""
    h = str(hex_color or "").lstrip("#")
    if len(h) != 6:
        return "&H00FFFFFF"
    try:
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f"&H00{b}{g}{r}".upper()
    except Exception:
        return "&H00FFFFFF"


def _char_width(ch: str) -> float:
    """Rough advance width in em: full-width CJK ~1.0, half-width ~0.5."""
    o = ord(ch)
    if (0x3000 <= o <= 0x9FFF) or (0xFF00 <= o <= 0xFFEF) or (0x3040 <= o <= 0x30FF):
        return 1.0
    return 0.5


def _wrap_caption_ass(text: str, font_px: float, max_px: float) -> str:
    """Insert ASS \\N line breaks so each line fits max_px. CJK-aware (wraps per char;
    keeps ASCII words intact). Input may already be ASS-escaped; existing \\N are treated
    as hard breaks. Returns text with \\N between lines."""
    if font_px <= 0 or max_px <= 0:
        return text
    hard_text = text.replace("\\N", "\n")  # treat existing \N as hard breaks
    out_lines: list[str] = []
    for hard in hard_text.split("\n"):
        line = ""
        line_w = 0.0
        i = 0
        while i < len(hard):
            ch = hard[i]
            # keep an ASCII word together
            if ch.isascii() and not ch.isspace():
                j = i
                word = ""
                while j < len(hard) and hard[j].isascii() and not hard[j].isspace():
                    word += hard[j]; j += 1
                ww = sum(_char_width(c) for c in word) * font_px
                if line_w + ww > max_px and line:
                    out_lines.append(line); line = word; line_w = ww
                else:
                    line += word; line_w += ww
                i = j
                continue
            cw = _char_width(ch) * font_px
            if line_w + cw > max_px and line.strip():
                out_lines.append(line); line = ch if not ch.isspace() else ""; line_w = cw if not ch.isspace() else 0.0
            else:
                line += ch; line_w += cw
            i += 1
        out_lines.append(line)
    return "\\N".join(s.rstrip() for s in out_lines)


def _caption_style_override(style: dict[str, Any] | None, base_font: int, width: int = 0, height: int = 0) -> tuple[str, int]:
    """Return (inline ASS override prefix, effective font px) for a styled caption.
    Empty override + base_font when style is None/empty (keeps unstyled output identical)."""
    if not isinstance(style, dict) or not style:
        return "", base_font
    parts: list[str] = []
    font_px = base_font
    try:
        if style.get("fontSize"):
            font_px = max(10, round(base_font * float(style["fontSize"])))
            parts.append(f"\\fs{font_px}")
    except Exception:
        pass
    if style.get("color"):
        parts.append(f"\\c{_hex_to_ass_color(style['color'])}")
    if style.get("outlineColor"):
        parts.append(f"\\3c{_hex_to_ass_color(style['outlineColor'])}")
    try:
        if style.get("outlineWidth") is not None:
            parts.append(f"\\bord{max(0, round(4 * float(style['outlineWidth'])))}")
    except Exception:
        pass
    if style.get("bold") is False:
        parts.append("\\b0")
    # Anchored bottom-centre (\an2); the user moves it freely with x/y (no top/center/bottom preset).
    try:
        ox = float(style.get("x") or 0)
        oy = float(style.get("y") or 0)
    except Exception:
        ox = oy = 0.0
    if (abs(ox) > 1e-4 or abs(oy) > 1e-4) and width and height:
        ox = max(-0.3, min(0.3, ox))
        # y = fraction UP from the screen bottom (positive = up); ~0.08 is the default lower spot.
        yf = max(0.0, min(0.92, oy)) if abs(oy) > 1e-4 else 0.08
        px = round(width / 2 + ox * width)
        py = round(height - yf * height)
        parts.append(f"\\an2\\pos({px},{py})")
    else:
        parts.append("\\an2")
    return ("{" + "".join(parts) + "}" if parts else ""), font_px


def _write_caption_ass(path: Path, captions: list[dict[str, Any]], width: int, height: int) -> None:
    font_size = max(28, round(height * 0.04))
    margin_v = max(54, round(height * 0.08))
    max_px = width * 0.92
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
        override, font_px = _caption_style_override(caption.get("style"), font_size, width, height)
        # escape first (turns literal newlines into \N and protects braces), THEN wrap —
        # _wrap_caption_ass only inserts additional \N which must survive as-is.
        escaped = _ass_escape(str(caption.get("text") or "").strip())
        wrapped = _wrap_caption_ass(escaped, font_px, max_px)
        text = override + wrapped if override else wrapped
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}")
    path.write_text("\n".join(lines), encoding="utf-8")


_ANIMATED_CAPTIONS = {"pop", "fade", "slide", "typewriter", "karaoke"}
_CAPTION_ANIM_FPS = float(os.environ.get("DAN_CAPTION_ANIM_FPS", "20"))


def _render_caption_overlays(
    captions: list[dict[str, Any]], output_width: int, output_height: int, job_dir: Path
) -> list[dict[str, Any]]:
    """Render designed captions by screenshotting the Next.js /caption-frame route (same
    <CaptionLayer> as the live preview => pixel parity). A STATIC caption -> one transparent PNG;
    an ANIMATED caption -> a PNG sequence sampled over its duration. Returns a list of overlay
    specs ({kind:'static'|'anim', ...}). Raises on any failure so the caller can fall back to .ass."""
    web_base = os.environ.get("DAN_CAPTION_RENDER_BASE", "http://127.0.0.1:3000")
    items: list[dict[str, Any]] = []
    specs: list[dict[str, Any]] = []
    for i, cap in enumerate(captions):
        text = str(cap.get("text") or "").strip()
        if not text:
            continue
        start = max(0.0, float(cap.get("timeline_start") or 0))
        end = max(start + 0.2, float(cap.get("timeline_end") or start + 2))
        style = cap.get("style") or {}
        words = cap.get("words") if isinstance(cap.get("words"), list) else []
        animated = str(style.get("animation") or "") in _ANIMATED_CAPTIONS
        if animated:
            seq_dir = job_dir / f"caption_{i:03d}_seq"
            items.append({"seq_dir": str(seq_dir), "text": text, "start": start, "end": end,
                          "fps": _CAPTION_ANIM_FPS, "design": style, "words": words})
            specs.append({"kind": "anim", "seq_dir": seq_dir, "fps": _CAPTION_ANIM_FPS, "start": start, "end": end})
        else:
            png = job_dir / f"caption_{i:03d}.png"
            items.append({"png": str(png), "text": text, "time": 0.0, "design": style, "words": words})
            specs.append({"kind": "static", "png": png, "start": start, "end": end})
    if not items:
        return []
    spec_path = job_dir / "captions_spec.json"
    spec_path.write_text(
        json.dumps({"outW": output_width, "outH": output_height, "web_base": web_base, "items": items},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    script = PROJECT_ROOT / "scripts" / "render_caption_pngs.py"
    cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [sys.executable, str(script), str(spec_path)],
        capture_output=True, text=True, timeout=600, creationflags=cflags,
    )
    if result.returncode != 0:
        raise RuntimeError(f"caption png render failed: {(result.stdout or '')[-400:]} | {(result.stderr or '')[-300:]}")
    for spec in specs:
        if spec["kind"] == "static" and not spec["png"].exists():
            raise RuntimeError(f"caption PNG missing: {spec['png']}")
        if spec["kind"] == "anim" and not any(spec["seq_dir"].glob("*.png")):
            raise RuntimeError(f"caption sequence empty: {spec['seq_dir']}")
    return specs


def _asset_source_path(asset: dict[str, Any]) -> Path:
    source_value = asset.get("proxy_path") or asset.get("local_path")
    if not source_value:
        raise RuntimeError(f"Video asset has no local path: {asset.get('id')}")
    path = Path(source_value).resolve()
    if not path.exists():
        raise RuntimeError(f"Video file not found: {path}")
    return path


def _asset_hires_path(asset: dict[str, Any]) -> Path:
    """Prefer the ORIGINAL (full-res) source over the proxy — used for pop-out matting so the
    cutout edges stay clean (the proxy can be ~406x720; matting on it looks coarse). Falls back
    to the proxy if the original is missing."""
    for key in ("local_path", "proxy_path"):
        v = asset.get(key)
        if v and Path(v).exists():
            return Path(v).resolve()
    return _asset_source_path(asset)


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
    """Manual STATIC blur rectangles (ffmpeg/_blur_chain). Tracked (data.track) and KEYFRAMED
    (data.keyframes) ones are excluded here — they're followed per-frame in a post-pass instead
    (see _apply_tracked_blur)."""
    annotations = ((instruction.get("timeline") or {}).get("annotations") or [])
    return [
        annotation
        for annotation in annotations
        if annotation.get("intent") == "blur" and annotation.get("kind") == "rect"
        and isinstance(annotation.get("data"), dict)
        and not annotation["data"].get("track")
        and not (isinstance(annotation["data"].get("keyframes"), list) and annotation["data"]["keyframes"])
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
        if not isinstance(track, dict) or track.get("hidden"):
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
    tracks = [t for t in (sequence.get("tracks") or []) if isinstance(t, dict)]
    # link_id -> the visual lane that owns the linked audio (unified A/V rule)
    link_owner: dict[str, dict[str, Any]] = {}
    for t in tracks:
        if t.get("type") == "audio":
            continue
        for cl in t.get("clips") or []:
            if isinstance(cl, dict) and cl.get("link_id") and cl["link_id"] not in link_owner:
                link_owner[cl["link_id"]] = t
    any_solo = any(t.get("solo") for t in tracks)
    clips: list[dict[str, Any]] = []
    for track in tracks:
        if track.get("type") != "audio":
            continue
        for clip in track.get("clips") or []:
            if not (isinstance(clip, dict) and clip.get("asset_id")):
                continue
            gov = link_owner.get(clip.get("link_id") or "", track)
            if gov.get("muted"):
                continue
            if any_solo and not gov.get("solo"):
                continue
            clips.append(clip)
    return sorted(clips, key=lambda c: float(c.get("timeline_start") or 0))


def _sequence_effect_clips(sequence: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Region-bearing clips from ANY non-audio lane — lanes are just layers; the editor
    places blur clips wherever there is free space (no effect-lane special casing)."""
    if not isinstance(sequence, dict):
        return []
    clips: list[dict[str, Any]] = []
    for track in sequence.get("tracks") or []:
        if not isinstance(track, dict) or track.get("type") == "audio" or track.get("hidden"):
            continue
        for clip in track.get("clips") or []:
            if isinstance(clip, dict) and isinstance(clip.get("region"), dict) and not clip.get("asset_id"):
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


def _blur_style_proc(style: str, w: int, h: int) -> str:
    style = (style or "").lower()
    if "mosaic" in style:
        return f"scale={max(2, w // 12)}:{max(2, h // 12)}:flags=neighbor,scale={w}:{h}:flags=neighbor"
    return "gblur=sigma=20"


def _blur_chain_masked(video_in: str, idx: int, mask_path: Path, bt: dict[str, Any],
                       clip: dict[str, Any], base_clips: list[dict[str, Any]],
                       w: int, h: int, style: str) -> tuple[str, str] | None:
    """Tracked blur for the EXPORT: blur the full frame, alpha it by the baked SAM mask
    video, overlay back — per base-cut segment so mask time (source-anchored) aligns with
    output time. Mirrors what ps_blur_masked does live in the editor. Returns None when
    no segment of the effect window is covered (caller falls back to the static rect)."""
    ts = float(clip.get("timeline_start") or 0)
    te = float(clip.get("timeline_end") or 0)
    bs = float(bt.get("bake_start") or 0)
    be = float(bt.get("bake_end") or 0) or float("inf")
    baid = str(bt.get("asset_id") or "")
    segs: list[tuple[float, float, float]] = []  # (out t0, out t1, mask m0)
    for bc in base_clips:
        if str(bc.get("asset_id") or "") != baid:
            continue
        bts = float(bc.get("timeline_start") or 0)
        bte = float(bc.get("timeline_end") or 0)
        bss = float(bc.get("source_start") or 0)
        bse = float(bc.get("source_end") or 0)
        if bse <= bss:  # freeze clips: static mask would be wrong more often than right
            continue
        t0, t1 = max(ts, bts), min(te, bte)
        if t1 - t0 < 0.05:
            continue
        s0 = bss + (t0 - bts)
        s1 = bss + (t1 - bts)
        # clamp to the baked window (outside it there is no mask data)
        lo, hi = max(s0, bs), min(s1, be)
        if hi - lo < 0.05:
            continue
        t0 += lo - s0
        t1 -= s1 - hi
        segs.append((round(t0, 3), round(t1, 3), round(lo - bs, 3)))
    if not segs:
        return None
    proc = _blur_style_proc(style, w, h)
    n = len(segs)
    fsplit = "".join(f"[tf{idx}_{j}]" for j in range(n))
    parts = [f"[{video_in}]split={n + 1}[tb{idx}]{fsplit}"]
    cur = f"tb{idx}"
    for j, (t0, t1, m0) in enumerate(segs):
        d = t1 - t0
        # blurred picture for this segment (30fps so alphamerge's frame zip matches the mask)
        parts.append(
            f"[tf{idx}_{j}]fps=30,trim=start={t0:.3f}:end={t1:.3f},setpts=PTS-STARTPTS,{proc}[tfb{idx}_{j}]"
        )
        # mask frames for the same span (mask video timeline = bake window, CFR 30).
        # The mask lives in SOURCE-frame space: run it through the SAME cover-crop the
        # base video gets (plain scale=W:H stretched it and the blur landed offset).
        parts.append(
            f"{_movie_input(mask_path, max(0.0, m0 - 0.6))},fps=30,"
            f"trim=start={m0:.3f}:end={m0 + d:.3f},setpts=PTS-STARTPTS,"
            f"format=gray,scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}[tmk{idx}_{j}]"
        )
        parts.append(
            f"[tfb{idx}_{j}][tmk{idx}_{j}]alphamerge,setpts=PTS+{t0:.3f}/TB[tov{idx}_{j}]"
        )
        nxt = f"tc{idx}_{j}"
        parts.append(
            f"[{cur}][tov{idx}_{j}]overlay=0:0:enable='between(t\\,{t0:.3f}\\,{t1:.3f})':eof_action=pass[{nxt}]"
        )
        cur = nxt
    return ";\n".join(parts), cur


def _blur_chain(video_in: str, idx: int, x: int, y: int, w: int, h: int, start: float, end: float, style: str) -> tuple[str, str]:
    """Return (filter_string, out_label) for a time-gated regional blur/mosaic overlay."""
    out = f"vblur{idx}"
    base, crop, blurred = f"bbase{idx}", f"bcrop{idx}", f"bblur{idx}"
    style = (style or "").lower()
    if "mosaic" in style:
        down_w = max(2, w // 12)
        down_h = max(2, h // 12)
        proc = f"crop={w}:{h}:{x}:{y},scale={down_w}:{down_h}:flags=neighbor,scale={w}:{h}:flags=neighbor"
    else:
        # gaussian is the default look (was a boxy boxblur) — soft, content-obscuring.
        proc = f"crop={w}:{h}:{x}:{y},gblur=sigma=20"
    filt = (
        f"[{video_in}]split[{base}][{crop}];"
        f"[{crop}]{proc}[{blurred}];"
        f"[{base}][{blurred}]overlay={x}:{y}:enable='between(t\\,{start:.3f}\\,{end:.3f})'[{out}]"
    )
    return filt, out


def _apply_screen_blur(out_path: Path, spec: dict[str, Any], job_dir: Path) -> bool:
    """Post-pass: blur sensitive on-screen text (credentials etc.) in the FINAL rendered video by
    OCR-detecting it per frame (scripts/screen_blur.py). Runs ON THE OUTPUT, so it follows whatever
    is actually shown (scrolling, PiP, scaling) with no coordinate mapping. Replaces out_path."""
    targets = [str(t).strip() for t in (spec.get("targets") or []) if str(t).strip()]
    patterns = [str(p).strip() for p in (spec.get("patterns") or []) if str(p).strip()]
    regex = str(spec.get("regex") or "").strip()
    if not targets and not patterns and not regex:
        return False
    tmp = job_dir / "screenblur_out.mp4"
    script = PROJECT_ROOT / "scripts" / "screen_blur.py"
    cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    args = [sys.executable, str(script), str(out_path), str(tmp),
            "--fps", str(spec.get("fps") or 4), "--pad", str(spec.get("pad") or 0.35),
            "--style", str(spec.get("style") or "gaussian"), "--ffmpeg", _ffmpeg()]
    if targets:
        args += ["--targets", ",".join(targets)]
    if patterns:
        args += ["--patterns", ",".join(patterns)]
    if regex:
        args += ["--regex", regex]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=1800, creationflags=cflags)
    except Exception as exc:  # noqa: BLE001
        logger.warning("screen blur post-pass crashed: %s", exc)
        return False
    if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
        shutil.move(str(tmp), str(out_path))
        return True
    logger.warning("screen blur post-pass failed: %s | %s", (r.stdout or "")[-200:], (r.stderr or "")[-200:])
    return False


def _apply_tracked_blur(out_path: Path, annotations: list[dict[str, Any]], job_dir: Path) -> bool:
    """Post-pass: human-drawn TRACKED blur boxes (data.track) bake their PRE-COMPUTED OCR path
    (data.track_boxes, set when the user pressed 解析) onto the FINAL video, gaussian-blurred. The
    boxes are normalized output coords (drawn on the preview) so they map to the final video
    directly. No re-tracking here — the editor already tracked and the user confirmed the range."""
    tracks: list[dict[str, Any]] = []
    for ann in annotations:
        if ann.get("intent") != "blur" or ann.get("kind") != "rect":
            continue
        data = ann.get("data") if isinstance(ann.get("data"), dict) else {}
        style = str(data.get("blur_style") or data.get("style") or "gaussian")
        # Manual keyframes win: densely sample the linear interpolation between them (output coords,
        # timeline time) so the box glides exactly as the editor previewed it.
        kfs = data.get("keyframes")
        if isinstance(kfs, list) and len(kfs) >= 1:
            pts = sorted(
                [{"t": float(k.get("t") or 0), "x": float(k.get("x") or 0), "y": float(k.get("y") or 0),
                  "w": float(k.get("width") or 0), "h": float(k.get("height") or 0)} for k in kfs if isinstance(k, dict)],
                key=lambda p: p["t"],
            )
            if pts:
                boxes: dict[str, list] = {}
                if len(pts) == 1:
                    p = pts[0]
                    boxes[f"{p['t']:.3f}"] = [p["x"], p["y"], p["w"], p["h"]]
                else:
                    t = pts[0]["t"]
                    step = 1.0 / 30.0  # 30 fps sampling so the baked box tracks per-frame (no peeking)
                    while t <= pts[-1]["t"] + 1e-6:
                        k0, k1 = pts[0], pts[-1]
                        for i in range(len(pts) - 1):
                            if pts[i]["t"] <= t <= pts[i + 1]["t"]:
                                k0, k1 = pts[i], pts[i + 1]
                                break
                        span = (k1["t"] - k0["t"]) or 1.0
                        f = (t - k0["t"]) / span
                        boxes[f"{t:.3f}"] = [
                            k0["x"] + (k1["x"] - k0["x"]) * f, k0["y"] + (k1["y"] - k0["y"]) * f,
                            k0["w"] + (k1["w"] - k0["w"]) * f, k0["h"] + (k1["h"] - k0["h"]) * f,
                        ]
                        t += step
                tracks.append({"boxes": boxes, "style": style})
            continue
        if not data.get("track"):
            continue
        boxes = data.get("track_boxes")
        if isinstance(boxes, dict) and boxes:
            tracks.append({"boxes": boxes, "style": style})
    if not tracks:
        return False
    spec_path = job_dir / "trackblur_spec.json"
    spec_path.write_text(json.dumps({"tracks": tracks}), encoding="utf-8")
    tmp = job_dir / "trackblur_out.mp4"
    script = PROJECT_ROOT / "scripts" / "screen_blur.py"
    cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run(
            [sys.executable, str(script), str(out_path), str(tmp), "--render-spec", str(spec_path), "--ffmpeg", _ffmpeg()],
            capture_output=True, text=True, timeout=1800, creationflags=cflags,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("tracked blur post-pass crashed: %s", exc)
        return False
    if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
        shutil.move(str(tmp), str(out_path))
        return True
    logger.warning("tracked blur post-pass failed: %s | %s", (r.stdout or "")[-200:], (r.stderr or "")[-200:])
    return False


def _shape_cut_filter(shape: str | None, w: int, h: int, alpha: bool) -> str:
    """ffmpeg filter that cuts a clip to a circle / rounded 'photo' frame. alpha=True -> transparent
    outside (overlays); alpha=False -> BLACK outside (base layer, keeps yuv420p for the concat).
    Matches the canvas clip in the preview. '' for rect/None."""
    s = str(shape or "rect")
    if s == "circle":
        cond = f"lte(((X-{w}/2)/({w}/2))^2+((Y-{h}/2)/({h}/2))^2\\,1)"
    elif s == "rounded":
        rr = max(2, round(min(w, h) * 0.12))
        cond = (
            f"clip(gte(X\\,{rr})*lte(X\\,{w - 1 - rr})+gte(Y\\,{rr})*lte(Y\\,{h - 1 - rr})"
            f"+lte(hypot(X-{rr}\\,Y-{rr})\\,{rr})+lte(hypot(X-{w - 1 - rr}\\,Y-{rr})\\,{rr})"
            f"+lte(hypot(X-{rr}\\,Y-{h - 1 - rr})\\,{rr})+lte(hypot(X-{w - 1 - rr}\\,Y-{h - 1 - rr})\\,{rr})\\,0\\,1)"
        )
    else:
        return ""
    if alpha:
        return f",format=yuva420p,geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':a='255*{cond}'"
    return f",geq=lum='if({cond}\\,lum(X,Y)\\,16)':cb='if({cond}\\,cb(X,Y)\\,128)':cr='if({cond}\\,cr(X,Y)\\,128)'"


def _movie_input(path: Any, seek: float, *, audio: bool = False, streams: str | None = None, fmt: str | None = None) -> str:
    """movie=/amovie= source for the filtergraph SCRIPT — replaces a command-line -i input.

    With hundreds of clips the per-clip "-i path" args alone blow Windows' 32K argv limit
    (WinError 206); the script file has no such cap. seek_point additionally avoids decoding
    every source from t=0 (a bare -i + trim= drops frames only AFTER decoding them).
    """
    # two-level parse: the graph parser strips the quotes, then the OPTION parser still
    # splits on ':' — so the drive colon must be escaped even inside quotes ('C\:/...')
    p = str(path).replace("\\", "/").replace("'", "\\'").replace(":", "\\:")
    out = ("amovie" if audio else "movie") + f"=filename='{p}'"
    if seek > 0.001:
        out += f":seek_point={seek:.3f}"
    if streams:
        out += f":streams={streams}"
    if fmt:
        out += f":format_name={fmt}"
    return out


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
        pad_needed = 0.0 if is_freeze else max(0.0, out_dur - src_dur)
        bpos = clip.get("position") if isinstance(clip.get("position"), dict) else None
        is_full_pos = (not bpos) or (
            float(bpos.get("x") or 0) <= 0.001 and float(bpos.get("y") or 0) <= 0.001
            and float(bpos.get("width") or 1) >= 0.999 and float(bpos.get("height") or 1) >= 0.999
        )
        b_scale, b_tx, b_ty = _clip_transform(clip)
        sw = float(metadata.get("width") or 0)
        sh = float(metadata.get("height") or 0)
        # crop: trim edges of the source (0-1). Non-zero crop forces the non-identity path.
        bcrop = clip.get("crop") if isinstance(clip.get("crop"), dict) else None
        c_l = max(0.0, min(0.9, float(bcrop.get("left") or 0))) if bcrop else 0.0
        c_r = max(0.0, min(0.9, float(bcrop.get("right") or 0))) if bcrop else 0.0
        c_t = max(0.0, min(0.9, float(bcrop.get("top") or 0))) if bcrop else 0.0
        c_b = max(0.0, min(0.9, float(bcrop.get("bottom") or 0))) if bcrop else 0.0
        has_crop = (c_l + c_r + c_t + c_b) > 0.001
        identity = is_full_pos and _is_identity_transform(b_scale, b_tx, b_ty) and not has_crop
        # Wipe shape on a BASE clip: black outside the cutout (this layer has no alpha).
        base_shape = _shape_cut_filter(clip.get("shape"), output_width, output_height, alpha=False)
        if identity or sw <= 0 or sh <= 0:
            # IDENTITY (or unknown source dims): exact current cover-crop string (byte-identical).
            _scale = f"scale={output_width}:{output_height}:force_original_aspect_ratio=increase,crop={output_width}:{output_height},setsar=1,fps=30"
            if is_freeze:
                setpts = f"setpts=PTS-STARTPTS,{_scale},tpad=stop_mode=clone:stop_duration={out_dur:.3f}"
            else:
                _pad = f",tpad=stop_mode=clone:stop_duration={pad_needed:.3f}" if pad_needed > 0.02 else ""
                setpts = f"setpts=PTS-STARTPTS,{_scale}{_pad}"
            filters.append(
                _movie_input(source_path, source_start) + ","
                f"trim=start={source_start:.3f}:end={source_end:.3f},"
                f"{setpts},format=yuv420p{base_shape}"
                f"[v{rendered_count}]"
            )
        else:
            # NON-DESTRUCTIVE placement: scale the FULL source aspect-preserved to cover the
            # box × transform.scale, overlay onto a black W×H canvas at a (possibly negative)
            # offset so the frame windows it — no crop, overflow pixels preserved.
            # Placement (transform) uses the FULL source — crop does NOT change cover/scale.
            bw = output_width if is_full_pos else max(2, round(float(bpos.get("width") or 1) * output_width))
            bh = output_height if is_full_pos else max(2, round(float(bpos.get("height") or 1) * output_height))
            bx = 0 if is_full_pos else round(float(bpos.get("x") or 0) * output_width)
            by = 0 if is_full_pos else round(float(bpos.get("y") or 0) * output_height)
            cover = max(bw / sw, bh / sh)
            cw = max(2, round(sw * cover * b_scale))
            ch = max(2, round(sh * cover * b_scale))
            ox = round(bx + (bw - cw) / 2 + b_tx * output_width)
            oy = round(by + (bh - ch) / 2 + b_ty * output_height)
            # crop = MASK: after scaling the full source to its placed size, keep only the
            # inner region and overlay it at the offset shifted by the crop — the trimmed
            # edges are left as the black canvas (no zoom, position/size unchanged).
            crop_filt = ""
            if has_crop:
                kw = max(2, round(cw * (1 - c_l - c_r)))
                kh = max(2, round(ch * (1 - c_t - c_b)))
                crop_filt = f"crop={kw}:{kh}:{round(cw * c_l)}:{round(ch * c_t)},"
                ox = ox + round(cw * c_l)
                oy = oy + round(ch * c_t)
            tpad = ""
            if is_freeze:
                tpad = f",tpad=stop_mode=clone:stop_duration={out_dur:.3f}"
            elif pad_needed > 0.02:
                tpad = f",tpad=stop_mode=clone:stop_duration={pad_needed:.3f}"
            filters.append(
                _movie_input(source_path, source_start) + ","
                f"trim=start={source_start:.3f}:end={source_end:.3f},"
                f"setpts=PTS-STARTPTS,scale={cw}:{ch}:force_original_aspect_ratio=disable,setsar=1,fps=30,{crop_filt}setsar=1{tpad},format=yuv420p"
                f"[src{rendered_count}]"
            )
            filters.append(f"color=c=black:s={output_width}x{output_height}:r=30:d={out_dur:.3f}[bg{rendered_count}]")
            filters.append(
                f"[bg{rendered_count}][src{rendered_count}]overlay={ox}:{oy}:shortest=1,format=yuv420p{base_shape}[v{rendered_count}]"
            )
        if not has_audio_track:
            if metadata.get("audio_codec") and not clip.get("muted") and not is_freeze:
                try:
                    vol = float(clip.get("volume")) if clip.get("volume") is not None else 1.0
                except Exception:
                    vol = 1.0
                vol_filt = f",volume={vol:.3f}" if abs(vol - 1.0) > 1e-3 else ""
                filters.append(
                    _movie_input(source_path, source_start, audio=True) + ","
                    f"atrim=start={source_start:.3f}:end={source_end:.3f},"
                    f"asetpts=PTS-STARTPTS,apad,atrim=duration={out_dur:.3f},aresample=48000,aformat=channel_layouts=stereo{vol_filt}"
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
            "clip": clip,  # carries blur_track for the SAM-tracked export path
        })
    for annotation in _blur_annotations(instruction):
        data = annotation.get("data") or {}
        blur_specs.append({
            "x": data.get("x"), "y": data.get("y"), "width": data.get("width"), "height": data.get("height"),
            "start": annotation.get("start"), "end": annotation.get("end"),
            "style": data.get("blur_style") or data.get("style"),
        })
    for bi, spec in enumerate(blur_specs, start=1):
        # SAM-tracked clip: blur follows the baked mask video (what the preview shows);
        # the static rectangle below stays the fallback when no mask covers the window
        eclip = spec.get("clip") if isinstance(spec.get("clip"), dict) else None
        bt = (eclip or {}).get("blur_track") if isinstance((eclip or {}).get("blur_track"), dict) else None
        if bt and bt.get("key"):
            mask_path = _blur_cache_dir(room_id) / f"{re.sub(r'[^0-9a-f]', '', str(bt['key']))[:16]}.mask.mp4"
            if mask_path.exists() and mask_path.stat().st_size > 0:
                masked = _blur_chain_masked(
                    video_out, bi, mask_path, bt, eclip, base_clips,
                    output_width, output_height, str(spec.get("style") or ""))
                if masked:
                    filt, video_out = masked
                    filters.append(filt)
                    continue
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
        # No clamp: a wipe may sit partly/fully off-screen; ffmpeg overlay accepts negative
        # offsets and windows the overflow against the frame.
        px = round(float(pos.get("x") or 0.27) * output_width)
        py = round(float(pos.get("y") or 0.835) * output_height)
        # Manual per-edge crop = MASK: the wipe stays at its box size/position; we only cut the
        # trimmed strips away (cut edges reveal the main video behind). The picture does NOT move or
        # resize. Computed here (in box pixels), applied after the cover scale below. Mirrors the
        # native engine so the desktop preview and the export frame the wipe identically.
        _crop = clip.get("crop") if isinstance(clip.get("crop"), dict) else None
        _mask = None
        if _crop:
            _cl = max(0.0, min(0.9, float(_crop.get("left") or 0)))
            _cr = max(0.0, min(0.9, float(_crop.get("right") or 0)))
            _ct = max(0.0, min(0.9, float(_crop.get("top") or 0)))
            _cb = max(0.0, min(0.9, float(_crop.get("bottom") or 0)))
            if (_cl + _cr + _ct + _cb) > 1e-4:
                _ml = round(ow * _cl)
                _mt = round(oh * _ct)
                _mkw = max(2, ow - _ml - round(ow * _cr))
                _mkh = max(2, oh - _mt - round(oh * _cb))
                _mask = (_ml, _mt, _mkw, _mkh)
        ts = max(0.0, float(clip.get("timeline_start") or 0))
        te = max(ts + 0.05, float(clip.get("timeline_end") or (ts + ov_dur)))
        # --- pop-out effect (v4): composite the SAME cached bake the preview uses
        # (popout-cache/{key}.pv.mp4 = color track + alpha track) — alphamerge, apply the clip's
        # display transform, overlay. No re-matting at export; bakes on demand only if the cache
        # is missing (cleaned disk / legacy clip). Falls back to a plain wipe if the bake fails
        # (e.g. no person / no GPU). ---
        _popout = next((e for e in (clip.get("effects") or [])
                        if isinstance(e, dict) and e.get("type") == "popout"), None)
        if _popout:
            _pp = _popout.get("params") if isinstance(_popout.get("params"), dict) else {}
            # bake geometry = the CARD box captured at apply (params.box), NOT the display position
            _box_px = _popout_box_px(_pp.get("box") or clip.get("position"), output_width, output_height)
            if isinstance(_pp.get("bake_start"), (int, float)) and isinstance(_pp.get("bake_end"), (int, float)):
                _bs, _be = float(_pp["bake_start"]), float(_pp["bake_end"])
            else:
                _bs, _be = _popout_bake_range(asset, source_start, source_end)
            _intensity = str(_pp.get("intensity") or "mid")
            _shadow = _pp.get("shadow") is True  # default OFF (parity with the live look)
            _key = _popout_key(str(clip.get("asset_id") or ""), _bs, _be, _box_px,
                               output_width, output_height, _intensity, _shadow)
            _pv = _popout_cache_dir(room_id) / f"{_key}.pv.mp4"
            # >4KB, not >0: an interrupted bake leaves a tiny headerless stub (moov atom
            # missing) that movie= can't open — treat it as missing and re-bake over it
            if not (_pv.exists() and _pv.stat().st_size > 4096):
                try:
                    _popout_bake_sync(_asset_hires_path(asset), _pv, _box_px,
                                      output_width, output_height, _bs, _be,
                                      _intensity, _shadow, None)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("popout overlay failed for clip %s: %s — using plain wipe",
                                   clip.get("id"), exc)
                    _popout = None
            if _popout and _pv.exists() and _pv.stat().st_size > 4096:
                _off = max(0.0, source_start - _bs)
                _pdur = max(0.1, source_end - source_start)
                # the pv bake has 2 video tracks (color + alpha) — pull both from one movie=
                # source, trim each to the clip window, and alphamerge the pair. Index specs
                # (0+1), NOT "v:0+v:1": the option parser splits on ':' even when escaped.
                filters.append(
                    _movie_input(_pv, _off, streams="0+1") + f"[pvc{oi}][pva{oi}]"
                )
                filters.append(
                    f"[pvc{oi}]trim=start={_off:.3f}:end={_off + _pdur:.3f},setpts=PTS-STARTPTS[pvct{oi}]"
                )
                filters.append(
                    f"[pva{oi}]trim=start={_off:.3f}:end={_off + _pdur:.3f},setpts=PTS-STARTPTS[pvat{oi}]"
                )
                # display transform: the bake is full-canvas, so scale to the clip's box, cut the
                # per-edge crop strips in place (parity with the native videocrop), overlay at x/y
                _dis = clip.get("position") if isinstance(clip.get("position"), dict) else {}
                _dx = round(float(_dis.get("x") or 0) * output_width)
                _dy = round(float(_dis.get("y") or 0) * output_height)
                _dw = max(2, round(float(_dis.get("width") or 1) * output_width))
                _dh = max(2, round(float(_dis.get("height") or 1) * output_height))
                _chain = [f"[pvct{oi}][pvat{oi}]alphamerge"]
                if (_dw, _dh) != (output_width, output_height):
                    _chain.append(f"scale={_dw}:{_dh}")
                if _mask is not None:
                    _pl, _pt, _pkw, _pkh = (round(_dw * _cl), round(_dh * _ct),
                                            max(2, _dw - round(_dw * _cl) - round(_dw * _cr)),
                                            max(2, _dh - round(_dh * _ct) - round(_dh * _cb)))
                    _chain.append(f"crop={_pkw}:{_pkh}:{_pl}:{_pt}")
                    _dx, _dy = _dx + _pl, _dy + _pt
                _chain.append(f"setpts=PTS-STARTPTS+{ts:.3f}/TB")
                filters.append(",".join(_chain) + f"[pov{oi}]")
                filters.append(
                    f"[{video_out}][pov{oi}]overlay={_dx}:{_dy}:format=auto:"
                    f"enable='between(t\\,{ts:.3f}\\,{te:.3f})'[vov{oi}]"
                )
                video_out = f"vov{oi}"
                continue
        ov_pad = 0.0 if ov_freeze else max(0.0, ov_dur - ov_src)
        if ov_freeze:
            ov_pre = f"setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={ov_dur:.3f},"
        else:
            ov_pre = "setpts=PTS-STARTPTS," + (f"tpad=stop_mode=clone:stop_duration={ov_pad:.3f}," if ov_pad > 0.02 else "")
        # Wipe shape: clip the PiP to a circle / rounded frame via a transparent alpha mask.
        shape_filt = _shape_cut_filter(clip.get("shape"), ow, oh, alpha=True)
        # COVER by default: keep the source's aspect ratio (fill the box, crop the overflow) instead
        # of stretching it to the box's width AND height independently — the latter squished a 9:16
        # wipe into a 0.4×0.3 box (the "潰れ" bug). fit=="stretch" opts back into free-deform.
        if str(clip.get("fit") or "cover") == "stretch":
            _scale = f"scale={ow}:{oh}"
        else:
            _scale = f"scale={ow}:{oh}:force_original_aspect_ratio=increase,crop={ow}:{oh}"
        # MASK: cut the trimmed strips off the covered (and shaped) box; the kept pixels keep their
        # place, and the overlay origin shifts by the trimmed left/top so nothing moves or resizes.
        if _mask:
            _ml, _mt, _mkw, _mkh = _mask
            _maskcrop = f",crop={_mkw}:{_mkh}:{_ml}:{_mt}"
            _mx, _my = px + _ml, py + _mt
        else:
            _maskcrop = ""
            _mx, _my = px, py
        filters.append(
            _movie_input(source_path, source_start) + ","
            f"trim=start={source_start:.3f}:end={source_end:.3f},"
            f"{ov_pre}"
            f"{_scale},setsar=1,setpts=PTS-STARTPTS+{ts:.3f}/TB,format=yuv420p"
            f"{shape_filt}"
            f"{_maskcrop}"
            f"[ov{oi}]"
        )
        filters.append(
            f"[{video_out}][ov{oi}]overlay={_mx}:{_my}:enable='between(t\\,{ts:.3f}\\,{te:.3f})'[vov{oi}]"
        )
        video_out = f"vov{oi}"

    captions = _sequence_caption_clips(sequence)
    if captions:
        # Designed captions: burn the SAME HTML/CSS render the editor preview shows (via the
        # /caption-frame route, screenshotted to transparent PNGs) so preview == export. Falls
        # back to the libass .ass path if the caption renderer is unavailable.
        overlays: list[tuple[Path, float, float]] = []
        try:
            overlays = _render_caption_overlays(captions, output_width, output_height, job_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("designed caption overlay failed, falling back to .ass: %s", exc)
            overlays = []
        if overlays:
            for ci, ov in enumerate(overlays):
                cs = float(ov["start"])
                ce = float(ov["end"])
                if ov["kind"] == "anim":
                    # PNG sequence -> a moving overlay. Read at the sampling fps, then shift its
                    # PTS so frame 0 lands at the caption's start time.
                    fps = float(ov["fps"])
                    pattern = str(ov["seq_dir"] / "%05d.png")
                    # image2 defaults to 25fps — retime from the frame INDEX so the sampling
                    # fps is exact, then shift frame 0 to the caption start
                    filters.append(
                        _movie_input(pattern, 0.0, fmt="image2")
                        + f",format=rgba,setpts=N/({fps:g}*TB)+{cs:.3f}/TB[capsrc{ci}]"
                    )
                else:
                    # single frame: overlay's default eof_action=repeat holds it, enable= gates it
                    filters.append(_movie_input(ov["png"], 0.0) + f",format=rgba[capsrc{ci}]")
                filters.append(
                    f"[{video_out}][capsrc{ci}]overlay=0:0:enable='between(t\\,{cs:.3f}\\,{ce:.3f})'[vcap{ci}]"
                )
                video_out = f"vcap{ci}"
            filters.append(f"[{video_out}]format=yuv420p[vcapf]")
            video_out = "vcapf"
        else:
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
            try:
                avol = float(clip.get("volume")) if clip.get("volume") is not None else 1.0
            except Exception:
                avol = 1.0
            avol_filt = f",volume={avol:.3f}" if abs(avol - 1.0) > 1e-3 else ""
            filters.append(
                _movie_input(source_path, source_start, audio=True) + ","
                f"atrim=start={source_start:.3f}:end={source_end:.3f},"
                f"asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo{avol_filt},adelay={ts_ms}|{ts_ms}"
                f"[{label}]"
            )
            audio_labels.append(label)
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

    # Pass the filtergraph via a SCRIPT FILE, not the command line: with hundreds of clips the
    # graph is tens of KB and a single -filter_complex arg blows past Windows' command-line limit
    # (surfaces as WinError 206 "filename or extension too long").
    fg_path = job_dir / f"{job_id}_filtergraph.txt"
    fg_path.write_text(";".join(filters), encoding="utf-8")
    subprocess.run(
        [
            *command,
            "-filter_complex_script",
            str(fg_path),
            *maps,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
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

    # Privacy: bake in screen-recording blur (credentials/sensitive text) as a post-pass on the
    # final video, if the content has it enabled. Reads the authoritative stored spec.
    try:
        _content = next((c for c in _read_contents(room_id) if c.get("id") == content_id), None)
        _tl = (_content or {}).get("timeline") or {}
        # spec can live on the timeline (set directly) OR on the assembled sequence (Dan-driven).
        _sb = _tl.get("screen_blur") or (_tl.get("sequence") or {}).get("screen_blur")
        if isinstance(_sb, dict) and _sb.get("enabled"):
            _apply_screen_blur(out_path, _sb, job_dir)
        # manual TRACKED blur boxes the human drew on the timeline (follow the region per-frame).
        _anns = _tl.get("annotations") or []
        if any(isinstance(a, dict) and a.get("intent") == "blur" and (a.get("data") or {}).get("track") for a in _anns):
            _apply_tracked_blur(out_path, _anns, job_dir)
    except Exception as exc:  # noqa: BLE001
        logger.warning("screen blur post-pass skipped: %s", exc)

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


SILENCE_DB = float(os.environ.get("DAN_SILENCE_DB", "-30"))   # noise floor for silence
SILENCE_MIN = float(os.environ.get("DAN_SILENCE_MIN", "0.04"))  # detect spans this short (assembly filters by the user's threshold)


def _detect_silence(src: str, noise_db: float = SILENCE_DB, min_dur: float = SILENCE_MIN) -> list[list[float]]:
    """Audio-level (waveform) silence regions in SOURCE seconds via ffmpeg silencedetect: spans
    where the audio stays below noise_db for >= min_dur. This is FireCut-style detection — far
    tighter than Whisper word gaps — so dead air can be cut right up to the waveform."""
    try:
        proc = subprocess.run(
            [_ffmpeg(), "-hide_banner", "-nostats", "-i", src, "-af",
             f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"],
            capture_output=True, timeout=900, check=False,
        )
        err = (proc.stderr or b"").decode("utf-8", "ignore")
    except Exception:
        return []
    out: list[list[float]] = []
    cur_start: float | None = None
    for line in err.splitlines():
        line = line.strip()
        if "silence_start:" in line:
            try:
                cur_start = float(line.split("silence_start:")[1].strip().split()[0])
            except Exception:
                cur_start = None
        elif "silence_end:" in line and cur_start is not None:
            try:
                end = float(line.split("silence_end:")[1].split("|")[0].strip().split()[0])
                if end > cur_start:
                    out.append([round(cur_start, 3), round(end, 3)])
            except Exception:
                pass
            cur_start = None
    return out


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
        # Waveform silence regions (model-independent), cached separately so a Whisper-model
        # change doesn't force re-detection. Computed once per source, reused everywhere.
        sil = meta.get("silence_regions") if meta.get("silence_src") == str(src) else None
        if sil is None:
            sil = _detect_silence(str(src))
            if live is not None:
                meta = dict(meta)
                meta["silence_regions"] = sil
                meta["silence_src"] = str(src)
                live["metadata"] = meta
                dirty = True
        cached = meta.get("audio_analysis")
        if isinstance(cached, dict) and meta.get("audio_analysis_src") == str(src) and meta.get("audio_analysis_model") == whisper_model:
            cached = dict(cached)
            cached["asset_index"] = asset_index
            cached["silence_regions"] = sil
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
            "silence_regions": sil,
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

    user_brief = str(instruction.get("brief") or timeline.get("brief") or "").strip()
    brief_banner = (
        "ユーザーの指示（このジョブで最優先。既定の作り方・テンプレより必ずこちらに従う）:\n"
        + user_brief
        + "\n\n"
        if user_brief
        else ""
    )
    prompt = f"""
{brief_banner}You are DAN, a video editor. Your deliverable is EDITING DECISIONS for a timeline — NOT a rendered video, and NOT a timeline JSON with exact numbers. Do NOT run ffmpeg. Do NOT render anything. A program will assemble the exact timeline from your decisions and the word-level transcript below, and the user will fine-tune it and export to MP4 later.

Work in TWO steps, in this order:

STEP 1 — Reason out loud (free-form Japanese). Like a skilled human editor: decide which spoken segments to KEEP and in what order, which 言い直し (restatement) take to DROP, where the screen-recording should take over as the background with the main camera shown as a small wipe (PiP), what on screen must be blurred, and how tight the pacing should be. Explain WHY. Follow the EDITING POLICY below.

STEP 2 — AFTER your reasoning, output ONE json object (and nothing after it) with your DECISIONS. Reference segments by their id (e.g. a1_s03). Do NOT compute timeline seconds yourself — the assembler derives them from the transcript timestamps.

DECISIONS schema:
{{
  "spine": [ {{"segment_id": "a1_s03", "caption": "整えたテロップ文字列 | null=発話をそのまま表示 | \"\"(空文字)=このセグメントはテロップ無し"}} ],
  "no_captions": false,
  "cuts": [ {{"asset_id": "<asset id>", "start": <sec>, "end": <sec>, "reason": "restatement|filler"}} ],
  "screen_overlays": [ {{"screen_asset_id": "<asset id>", "screen_source_start": <sec>, "screen_source_end": <sec>, "from_segment": "a1_s06", "to_segment": "a1_s12", "main_as_pip": true}} ],
  "blur": [ {{"target_text": "<exact on-screen text to hide; follows it as it moves>", "pattern": "email|phone|key", "target_object": "<SHORT ENGLISH noun phrase for a VISUAL object to blur. Use '<noun> in <attribute>' form, e.g. 'person in red shirt', 'license plate', 'face' — NEVER the word 'wearing'>", "asset_id": "<id>", "region": {{"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}}, "source_start": <sec>, "source_end": <sec>, "style": "mosaic|soft"}} ],
  "silence_threshold": 0.45
}}

Rules:
- CAPTIONS ARE OPTIONAL: if the user's brief asks for no captions (テロップ不要/入れるな 等), set "no_captions": true — then NO caption clips are generated at all, regardless of per-segment values. For selective omission use caption: "" on those segments. Follow the user's instruction over any default.
- spine = the kept talking segments in final order. Anything not listed is cut. Drop the earlier take of a CROSS-segment restatement by omitting that segment.
- cuts = WORD-LEVEL removals WITHIN kept segments. The transcript below has word-level timestamps; use cuts (in the asset's own seconds) to remove a 言い直し/stutter that happens INSIDE a single segment (e.g. the segment says "スタイル名や…スタイル名や…" — cut the first occurrence) or an obvious repeated filler run. The assembler trims exactly those spans. This is how you remove duplicates that survive the spine — listen via the transcript and cut them.
- Never cut a sentence end. The assembler AUTO-compresses internal silence longer than silence_threshold seconds, so do NOT list silence in cuts. Set silence_threshold lower (e.g. 0.3) for tighter pacing or higher for relaxed, following the user's request; omit it to use the default (0.45).
- During screen_overlays the screen recording is the background and the main camera is the small wipe; captions are auto-suppressed there (do not add captions to those segments).
- All audio comes from the main-camera spine segments automatically.
- blur = hide something on screen. Pick the field by WHAT is hidden:
  * specific TEXT/info (認証情報/メール/電話/ID/口座/氏名 など) — ESPECIALLY in a screen recording
    where it scrolls — emit "target_text" (the exact text you see) and/or "pattern"
    ("email"/"phone"/"key"). Detected per-frame at export and FOLLOWS the text.
  * a VISUAL object/person (「赤い服の人」「通行人」「顔」「ナンバープレート」「商品」など) — emit
    "target_object" as a SHORT ENGLISH noun phrase + "asset_id" + "source_start"/"source_end"
    (the asset's own seconds where it appears). An AI tracker (SAM) segments EVERY instance of
    that concept and the blur follows their pixel silhouettes. Prefer this over "region"
    whenever the thing can move.
  * a fixed area that never moves — static "region" (0..1 normalized).
  Do NOT blur unless the user asked to hide something.
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


def _caption_words_timeline(segment: dict[str, Any], seg_pieces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map a segment's Whisper words (asset seconds) onto the TIMELINE using the segment's
    assembled pieces (which carry source_start/end -> timeline_start/end). Words inside cut-out
    gaps are dropped. Returns [{text, start, end}] for caption karaoke / typewriter sync."""
    out: list[dict[str, Any]] = []
    for w in (segment.get("words") or []):
        txt = str(w.get("word") or "").strip()
        if not txt:
            continue
        ws = float(w.get("start") or 0.0)
        we = float(w.get("end") or ws)
        for pc in seg_pieces:
            ss = float(pc["source_start"])
            se = float(pc["source_end"])
            if ws < se and we > ss:  # word overlaps this kept piece
                t0 = float(pc["timeline_start"]) + (max(ws, ss) - ss)
                t1 = float(pc["timeline_start"]) + (min(we, se) - ss)
                out.append({"text": txt, "start": round(t0, 3), "end": round(max(t1, t0 + 0.05), 3)})
                break
    return out


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
    # Tiny pads kept around each word-run. Overridable so the cut-adjust UI can loosen/tighten
    # the breathing room around cuts (decisions.lead / decisions.tail, in seconds).
    try:
        LEAD = float(decisions.get("lead")) if decisions.get("lead") is not None else 0.06
        TAIL = float(decisions.get("tail")) if decisions.get("tail") is not None else 0.10
    except Exception:
        LEAD, TAIL = 0.06, 0.10
    LEAD = max(0.0, min(1.0, LEAD))
    TAIL = max(0.0, min(1.5, TAIL))
    # cut_meta records how much source time was removed (and where, in final-timeline seconds)
    # so the UI can animate the silence/dead-air being cut out FireCut-style.
    cut_meta: list[dict[str, Any]] = []

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

    # Waveform silence regions per asset (from ffmpeg silencedetect, cached in the analysis).
    silence_by_asset: dict[str, list[tuple[float, float]]] = {}
    for _aid, t in transcripts.items():
        regs = t.get("silence_regions") or []
        silence_by_asset[str(t.get("asset_id") or _aid)] = [
            (float(r[0]), float(r[1])) for r in regs if isinstance(r, (list, tuple)) and len(r) >= 2
        ]

    def _subtract(a: float, b: float, removes: list[tuple[float, float]]) -> list[tuple[float, float]]:
        """[a,b] minus the (clipped, merged) removal spans -> the kept spans."""
        clipped = sorted((max(a, x), min(b, y)) for x, y in removes if min(b, y) > max(a, x) + 0.001)
        merged: list[list[float]] = []
        for x, y in clipped:
            if merged and x <= merged[-1][1] + 0.001:
                merged[-1][1] = max(merged[-1][1], y)
            else:
                merged.append([x, y])
        out: list[tuple[float, float]] = []
        cur = a
        for x, y in merged:
            if x > cur + 0.02:
                out.append((cur, x))
            cur = max(cur, y)
        if b > cur + 0.02:
            out.append((cur, b))
        return out

    def _runs_for_segment(s: dict[str, Any]) -> list[tuple[float, float]]:
        """Kept speech runs (source seconds) for a segment. Prefer WAVEFORM silence: subtract
        silence regions >= SIL and Dan's cut spans from the segment span — this cuts dead air
        right up to the audio, tighter than Whisper word gaps. Falls back to word gaps (then the
        whole segment) when silence data is unavailable."""
        aid = str(s.get("asset_id") or "")
        a, b = float(s.get("start") or 0), float(s.get("end") or 0)
        sils = silence_by_asset.get(aid)
        if sils:
            removes = list(cuts_by_asset.get(aid, []))
            removes += [(rs, re) for rs, re in sils if re - rs >= SIL]
            return [(rs, re) for rs, re in _subtract(a, b, removes) if re - rs > 0.05]
        words = s.get("words") or []
        if not words:
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
            removed_here = 0.0
            if pe is not None:
                if src_start < pe:
                    src_start = pe
                else:
                    removed_here = src_start - pe  # silence/dead-air skipped before this run
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
            if removed_here > 0.02:
                cut_meta.append({"at": ts, "removed": round(removed_here, 3), "type": "silence"})
            prev_end_by_asset[aid] = src_end
            cursor = te
            if seg_ts is None:
                seg_ts = ts
            seg_te = te
        if seg_ts is None:
            continue
        seg_span[sid] = {
            "timeline_start": seg_ts, "timeline_end": seg_te,
            # caption: explicit string = styled text, None = fall back to the spoken text,
            # EMPTY string = no caption for this segment (the user can opt out — a null
            # fallback used to make captions structurally mandatory)
            "caption": ("" if (isinstance(cap, str) and not cap.strip()) else (cap.strip() if cap else str(s.get("text") or "").strip())),
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
    # Captions: one per kept (non-overlay) segment, spanning its full timeline range. Attach
    # per-word timings (segment Whisper words mapped to the timeline) so a karaoke / typewriter
    # caption syncs to the actual speech without any extra UI step.
    pieces_by_sid: dict[str, list[dict[str, Any]]] = {}
    for p in pieces:
        pieces_by_sid.setdefault(p["sid"], []).append(p)
    for sid in order:
        if sid in covered:
            continue
        sp = seg_span[sid]
        if sp["caption"] and not decisions.get("no_captions"):
            clip: dict[str, Any] = {"id": _cid("c"), "text": sp["caption"], "track": "caption",
                                    "timeline_start": sp["timeline_start"], "timeline_end": sp["timeline_end"]}
            words = _caption_words_timeline(seg_by_id.get(sid) or {}, pieces_by_sid.get(sid, []))
            if words:
                clip["words"] = words
            caption_clips.append(clip)

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

    # Pass 4: blur → effect clips (fixed region) OR an OCR-follow screen-blur spec (text/pattern
    # that may move/scroll). Dan emits target_text/pattern when the user asks to hide specific
    # info ("○○を隠して"); those are detected per-frame at export so they never leak.
    _PAT = {"phone": "digits", "number": "digits", "tel": "digits", "数字": "digits", "メール": "email"}
    sb_targets: list[str] = []
    sb_patterns: list[str] = []
    for b in (decisions.get("blur") or []):
        tt = str(b.get("target_text") or "").strip()
        pat = str(b.get("pattern") or "").strip().lower()
        if tt or pat:
            if tt:
                sb_targets.append(tt)
            if pat:
                sb_patterns.append(_PAT.get(pat, pat))
            continue
        tobj = str(b.get("target_object") or "").strip()
        if tobj:
            # VISUAL object ("person in red shirt") -> SAM-tracked blur: find where the
            # (asset, source range) lands on the FINAL timeline, start one mask bake over
            # the whole needed source span, and bind blur_track effect clips — the same
            # data the editor's 追従ぼかし produces, so preview/export/re-bake all work.
            tobj = _blur_prompt_to_english(tobj)
            baid = str(b.get("asset_id") or "")
            b_ss = float(b.get("source_start") or 0)
            b_se = float(b.get("source_end") or 0)
            runs: list[list[float]] = []  # [tl0, tl1, src0, src1]
            for vc in video_clips + overlay_clips:
                if str(vc.get("asset_id")) != baid:
                    continue
                v_ss = float(vc.get("source_start") or 0)
                v_se = float(vc.get("source_end") or 0)
                v_ts = float(vc.get("timeline_start") or 0)
                if v_se <= v_ss:
                    continue
                lo = max(v_ss, b_ss) if b_se > b_ss else v_ss
                hi = min(v_se, b_se) if b_se > b_ss else v_se
                if hi - lo < 0.05:
                    continue
                runs.append([v_ts + (lo - v_ss), v_ts + (hi - v_ss), lo, hi])
            if not runs:
                logger.info("target_object %r: asset %s range not on final timeline", tobj, baid)
                continue
            runs.sort()
            merged: list[list[float]] = []
            for r in runs:
                if merged and r[0] - merged[-1][1] < 0.25:
                    merged[-1][1] = max(merged[-1][1], r[1])
                    merged[-1][3] = max(merged[-1][3], r[3])
                else:
                    merged.append(list(r))
            bake = None
            try:
                t_asset = _assets_by_id(room_id).get(baid)
                if t_asset:
                    bake = _ensure_blur_mask_started(
                        room_id, t_asset,
                        {"prompt": tobj, "box": None, "points": None, "keep_ids": None,
                         "feather": None, "dilate": None, "anchor": None},
                        min(r[2] for r in runs), max(r[3] for r in runs))
            except Exception as exc:  # noqa: BLE001
                logger.warning("target_object bake start failed (%r): %s", tobj, exc)
            for m in merged:
                clip_e: dict[str, Any] = {
                    "id": _cid("e"), "track": "effect",
                    # stand-in rectangle until the mask lands (center field of view)
                    "region": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8},
                    "style": str(b.get("style") or "soft"),
                    "timeline_start": round(m[0], 3), "timeline_end": round(m[1], 3),
                }
                if bake:
                    clip_e["blur_track"] = {
                        "asset_id": baid, "key": bake["key"],
                        "bake_start": bake["bake_start"], "bake_end": bake["bake_end"],
                        "prompt": tobj,
                    }
                effect_clips.append(clip_e)
            continue
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

    seq_out: dict[str, Any] = {
        "version": 1,
        "format": fmt,
        "duration": total,
        "generated_by": "dan_plan",
        # cut parameters used for THIS assembly, so the UI can show the current slider state.
        "cut_params": {"silence_threshold": round(SIL, 3), "lead": round(LEAD, 3), "tail": round(TAIL, 3)},
        # where source time was removed (final-timeline seconds), for the FireCut-style animation.
        "cut_meta": cut_meta,
        "removed_total": round(sum(c["removed"] for c in cut_meta), 3),
        "tracks": [
            {"id": "video_1", "type": "video", "label": "Main video", "clips": video_clips},
            {"id": "overlay_1", "type": "overlay", "label": "Overlay/PiP", "clips": overlay_clips},
            {"id": "caption_1", "type": "caption", "label": "Captions", "clips": caption_clips},
            {"id": "audio_1", "type": "audio", "label": "Audio", "clips": audio_clips},
            {"id": "effects_1", "type": "effect", "label": "Blur/Effects", "clips": effect_clips},
        ],
    }
    if sb_targets or sb_patterns:
        # OCR-follow blur Dan was asked to apply ("○○を隠して"); baked at export (post-pass).
        seq_out["screen_blur"] = {
            "enabled": True,
            "targets": sorted(set(sb_targets)),
            "patterns": sorted(set(sb_patterns)),
            "style": "gaussian",
        }
    return seq_out


def _clips_in_scope(sequence: dict[str, Any], regions: list[dict[str, Any]]) -> set[str]:
    """Clip ids that a revision is allowed to touch. If regions is empty, the instruction is
    global -> every clip is in scope. Otherwise only clips overlapping a region's time range
    (and matching track if the region names one)."""
    all_ids: list[tuple[str, dict[str, Any], str]] = []
    for track in sequence.get("tracks") or []:
        ttype = track.get("type")
        for clip in track.get("clips") or []:
            cid = str(clip.get("id") or "")
            if cid:
                all_ids.append((cid, clip, str(ttype or clip.get("track") or "")))
    if not regions:
        return {cid for cid, _c, _t in all_ids}
    scope: set[str] = set()
    for cid, clip, ttype in all_ids:
        cs, ce = float(clip.get("timeline_start") or 0), float(clip.get("timeline_end") or 0)
        for r in regions:
            rs, re = float(r.get("start") or 0), float(r.get("end") if r.get("end") is not None else 1e9)
            rtrack = r.get("track")
            if rtrack and str(rtrack) != ttype:
                continue
            if min(ce, re) - max(cs, rs) > 0.01:  # time overlap
                scope.add(cid)
                break
    return scope


def _merge_revision_patch(sequence: dict[str, Any], patch: dict[str, Any], allowed_ids: set[str]) -> dict[str, Any]:
    """Apply Dan's per-clip revision patch to the sequence, preserving every clip outside the
    allowed scope verbatim. Edits/removes targeting ids NOT in allowed_ids are ignored (this is
    the guard that stops Dan from silently mutating the rest of the timeline)."""
    edits_by_id: dict[str, dict[str, Any]] = {}
    removes: set[str] = set()
    for e in (patch.get("edits") or []):
        if not isinstance(e, dict):
            continue
        cid = str(e.get("id") or "")
        if not cid or cid not in allowed_ids:
            continue  # out-of-scope guard
        if e.get("remove"):
            removes.add(cid)
        else:
            edits_by_id[cid] = e

    EDITABLE = {"text", "style", "timeline_start", "timeline_end", "source_start", "source_end"}
    new_tracks = []
    for track in sequence.get("tracks") or []:
        out_clips = []
        for clip in track.get("clips") or []:
            cid = str(clip.get("id") or "")
            if cid in removes:
                continue
            e = edits_by_id.get(cid)
            if e:
                nc = dict(clip)
                for k in EDITABLE:
                    if k not in e or e[k] is None:
                        continue
                    if k == "style" and isinstance(e[k], dict):
                        # MERGE style fields onto the existing style so an edit that only
                        # changes e.g. position keeps the clip's existing color/size.
                        merged_style = dict(nc.get("style") or {})
                        merged_style.update(e[k])
                        nc[k] = merged_style
                    else:
                        nc[k] = e[k]
                out_clips.append(nc)
            else:
                out_clips.append(clip)  # untouched, verbatim
        new_tracks.append({**track, "clips": out_clips})

    # New caption clips (text additions) — only accepted when their range is in an allowed region.
    seq2 = {**sequence, "tracks": new_tracks}
    new_caps = patch.get("new_captions") or []
    if new_caps:
        cap_track = next((t for t in new_tracks if t.get("type") == "caption"), None)
        if cap_track is not None:
            n = len(cap_track.get("clips") or [])
            for nc in new_caps:
                if not isinstance(nc, dict) or not str(nc.get("text") or "").strip():
                    continue
                n += 1
                cap_track.setdefault("clips", []).append({
                    "id": f"clip_rev_c{n:03d}", "track": "caption",
                    "text": str(nc.get("text")).strip(),
                    "timeline_start": round(float(nc.get("timeline_start") or 0), 3),
                    "timeline_end": round(float(nc.get("timeline_end") or 0), 3),
                    "style": nc.get("style"),
                })
            cap_track["clips"].sort(key=lambda c: float(c.get("timeline_start") or 0))

    dur = 0.0
    for t in new_tracks:
        for c in t.get("clips") or []:
            dur = max(dur, float(c.get("timeline_end") or 0))
    seq2["duration"] = round(dur, 3)
    return seq2


def _apply_blur_objects(sequence: dict[str, Any], blur_objects: list[dict[str, Any]], room_id: str) -> int:
    """「〜をぼかして」(dan_revise): for each visual-target entry, start SAM mask bakes for
    every asset shown in the requested timeline range and add blur_track effect clips —
    the exact data the editor's 追従ぼかし produces (preview/export/re-bake all work).
    Mutates `sequence`; returns the number of effect clips added."""
    tracks = sequence.get("tracks") or []

    def _place_on_free_lane(clip: dict[str, Any]) -> None:
        """Front-most (display top) non-audio lane with free span; else a new top lane —
        the same no-overlap placement the editor's ◱ uses."""
        t0, t1 = float(clip["timeline_start"]), float(clip["timeline_end"])
        for tr in reversed(tracks):
            if tr.get("type") == "audio" or tr.get("hidden") or tr.get("locked"):
                continue
            cs = tr.get("clips") or []
            if all(float(c.get("timeline_end") or 0) <= t0 + 1e-3
                   or float(c.get("timeline_start") or 0) >= t1 - 1e-3 for c in cs):
                tr.setdefault("clips", []).append(clip)
                return
        idx = max((i for i, tr in enumerate(tracks) if tr.get("type") != "audio"),
                  default=len(tracks) - 1) + 1
        tracks.insert(idx, {"type": "overlay", "clips": [clip]})

    assets = _assets_by_id(room_id)
    seq_dur = max((float(c.get("timeline_end") or 0)
                   for t in tracks for c in (t.get("clips") or [])), default=0.0)
    added = 0
    for bo in blur_objects:
        target = _blur_prompt_to_english(str(bo.get("target") or "").strip())
        if not target:
            continue
        ts = max(0.0, float(bo.get("timeline_start") or 0.0))
        te = float(bo.get("timeline_end") or 0.0) or seq_dur
        te = min(max(te, ts + 0.1), seq_dur or (ts + 0.1))
        # visual clips per asset inside [ts, te] -> merged timeline runs + union source window
        by_asset: dict[str, list[list[float]]] = {}
        for t in tracks:
            if t.get("type") not in {"video", "overlay"} or t.get("hidden"):
                continue
            for c in t.get("clips") or []:
                aid = str(c.get("asset_id") or "")
                v_ss = float(c.get("source_start") or 0)
                v_se = float(c.get("source_end") or 0)
                v_ts = float(c.get("timeline_start") or 0)
                v_te = float(c.get("timeline_end") or 0)
                if not aid or v_se <= v_ss or v_te <= max(ts, v_ts) or min(te, v_te) <= v_ts:
                    continue
                t0, t1 = max(ts, v_ts), min(te, v_te)
                by_asset.setdefault(aid, []).append(
                    [t0, t1, v_ss + (t0 - v_ts), v_ss + (t1 - v_ts)])
        for aid, runs in by_asset.items():
            asset = assets.get(aid)
            if not asset or asset.get("kind") != "video":
                continue
            runs.sort()
            merged: list[list[float]] = []
            for r in runs:
                if merged and r[0] - merged[-1][1] < 0.25:
                    merged[-1][1] = max(merged[-1][1], r[1])
                    merged[-1][3] = max(merged[-1][3], r[3])
                else:
                    merged.append(list(r))
            try:
                bake = _ensure_blur_mask_started(
                    room_id, asset,
                    {"prompt": target, "box": None, "points": None, "keep_ids": None,
                     "feather": None, "dilate": None, "anchor": None},
                    min(r[2] for r in runs), max(r[3] for r in runs))
            except Exception as exc:  # noqa: BLE001
                logger.warning("blur_objects bake start failed (%r/%s): %s", target, aid, exc)
                continue
            for m in merged:
                _place_on_free_lane({
                    "id": f"fxo_{uuid.uuid4().hex[:8]}",
                    "region": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8},
                    "style": "soft",
                    "timeline_start": round(m[0], 3), "timeline_end": round(m[1], 3),
                    "blur_track": {"asset_id": aid, "key": bake["key"],
                                   "bake_start": bake["bake_start"],
                                   "bake_end": bake["bake_end"], "prompt": target},
                })
                added += 1
    return added


def _build_dan_revision(
    room_id: str, user_id: str, job_id: str, instruction: dict[str, Any], instruction_path: Path,
) -> dict[str, Any] | None:
    """Region-scoped partial edit. Dan sees ONLY the in-scope clips + the instruction and
    returns a per-clip patch. Code merges it, preserving everything out of scope."""
    timeline = instruction.get("timeline") if isinstance(instruction.get("timeline"), dict) else {}
    sequence = timeline.get("sequence") if isinstance(timeline.get("sequence"), dict) else None
    if not sequence:
        return None
    regions = instruction.get("revision_regions") or []
    text = str(instruction.get("revision_text") or instruction.get("brief") or "").strip()
    allowed = _clips_in_scope(sequence, regions)

    # Compact view of the in-scope clips for Dan (id + what's editable).
    scope_view = []
    for track in sequence.get("tracks") or []:
        for clip in track.get("clips") or []:
            cid = str(clip.get("id") or "")
            if cid not in allowed:
                continue
            scope_view.append({
                "id": cid, "track": track.get("type"),
                "timeline_start": clip.get("timeline_start"), "timeline_end": clip.get("timeline_end"),
                **({"text": clip.get("text")} if clip.get("text") is not None else {}),
                **({"style": clip.get("style")} if clip.get("style") is not None else {}),
            })
    region_desc = "\n".join(
        f"- {r.get('intent') or 'edit'} {r.get('start')}s〜{r.get('end')}s: {r.get('note') or ''}"
        for r in regions
    ) or "(範囲指定なし＝指示は全体に適用)"

    prompt = f"""
You are DAN, doing a PARTIAL, non-destructive edit of an existing video timeline. You may ONLY
edit the clips listed below (they are the ones the user's instruction/regions touch). Everything
else in the timeline is preserved automatically — do NOT try to change anything not listed.

USER INSTRUCTION (text):
{text or '(なし)'}

INSTRUCTION REGIONS (timeline seconds):
{region_desc}

EDITABLE CLIPS (only these ids may be changed):
{json.dumps(scope_view, ensure_ascii=False, indent=2)}

Return ONE json object with your edits (and nothing after it). Only reference ids from the list.
{{
  "edits": [
    {{"id": "<clip id>", "text": "新しいテロップ or 省略", "style": {{"color":"#RRGGBB","fontSize":1.2,"position":"top|center|bottom","bold":true,"outlineColor":"#RRGGBB","outlineWidth":1.0}}, "timeline_start": <sec or 省略>, "timeline_end": <sec or 省略>, "remove": true/false}}
  ],
  "new_captions": [ {{"text": "...", "timeline_start": <sec>, "timeline_end": <sec>}} ],
  "blur_objects": [ {{"target": "<SHORT ENGLISH noun phrase for the VISUAL thing to blur. Use '<noun> in <attribute>' form, e.g. 'person in red shirt', 'license plate', 'face' — NEVER the word 'wearing'>", "timeline_start": <sec>, "timeline_end": <sec>}} ]
}}
Rules:
- 「〜をぼかして/隠して」で見た目の物体（人・顔・服装で特定された人・ナンバー・商品など）を指され
  たら "blur_objects" を出す。target はあなたが英語の短い名詞句に翻訳する。timeline_start/end は
  ユーザーが範囲を指定していればその範囲、なければタイムライン全体。AIトラッカーが該当する物体を
  全部追跡してぼかす（blur_objects は視覚的な物体専用。特定の文字列はここでは扱わない）。
- Caption text/style/position/size: edit the caption clip's fields.
- IMPORTANT — style is MERGED, not replaced: only include the style fields you are CHANGING.
  The clip's other existing style fields (shown above) are kept automatically. e.g. to move a
  red, large caption to the center, return only {{"style": {{"position": "center"}}}} — do NOT
  re-send color/fontSize; they are preserved. Never blank out a field the user didn't mention.
- "この部分を消して/カット": set remove:true on the clips in that range.
- Trim timing with timeline_start/timeline_end (seconds on the timeline).
- Only output ids from EDITABLE CLIPS. Output valid JSON, json LAST.
""".strip()

    async def run_dan(prompt_text: str) -> str:
        from app.agent.cli_runner import process_message_cli
        chunks: list[str] = []
        async for event in process_message_cli(
            room_id=room_id, user_id=user_id, content=prompt_text,
            project_title=str(instruction.get("content_title") or "Revision"),
            project_description=text, project_status="in_progress",
            skip_save=True, skip_resume=True, cwd="D:/dan-workspace",
        ):
            et = str(event.get("type") or "")
            if et in {"text", "reasoning", "tool_use", "result", "error"}:
                _append_job_event(room_id, job_id, {"type": et, "text": str(event.get("text") or event.get("message") or "")[:4000], "name": event.get("name") or event.get("tool_name")})
            if et in {"text", "result"} and event.get("text"):
                chunks.append(str(event.get("text")))
        return "\n".join(chunks).strip()

    output = asyncio.run(run_dan(prompt))
    patch = _extract_json_object(output)
    if not isinstance(patch, dict):
        return None
    merged = _merge_revision_patch(sequence, patch, allowed)
    # visual-object blur requests ride the same patch: start SAM bakes + bind effect clips
    blur_objects = patch.get("blur_objects") if isinstance(patch.get("blur_objects"), list) else []
    if merged and blur_objects:
        n_blur = _apply_blur_objects(merged, blur_objects, room_id)
        if n_blur:
            _append_job_event(room_id, job_id, {
                "type": "status",
                "text": f"追従ぼかしを{n_blur}箇所に適用（AIが対象を追跡中。ベイク完了までプレビューは仮矩形）。",
            })
    _append_job_event(room_id, job_id, {"type": "status", "text": f"部分編集を適用（対象クリップ {len(allowed)}個・範囲外は保持）。"})
    return merged


def _run_production_job(room_id: str, job_id: str, content_id: str, instruction: dict[str, Any], user_id: str) -> None:
    _update_job(room_id, job_id, {"status": "running"})
    # NEVER blow away the stored timeline with an empty/partial instruction payload —
    # a job posted without a full timeline (e.g. plain export test) must not wipe the
    # user's edit (this exact accident deleted a rebuilt 324-clip timeline once)
    def _timeline_patch() -> dict:
        tl = instruction.get("timeline")
        if isinstance(tl, dict) and isinstance(tl.get("sequence"), dict) and tl["sequence"].get("tracks"):
            return {"timeline": tl}
        return {}

    _update_content(room_id, content_id, {"status": "running", **_timeline_patch()})
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
            # Keep the decisions on the content so the cut-adjust UI can re-assemble with a new
            # silence threshold / pads later (no re-running Dan or Whisper).
            timeline_result = {"sequence": sequence_result, "decisions": decisions}
            dan_timeline_path.write_text(
                json.dumps({"decisions": decisions, "sequence": sequence_result}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            _append_job_event(room_id, job_id, {"type": "status", "text": "編集判断からタイムラインを組み立てました（MP4は未生成）。"})
        elif mode == "dan_revise":
            # Partial, non-destructive edit: Dan patches only the in-scope clips; everything
            # else is preserved. The deliverable is the updated TIMELINE — no MP4 is rendered
            # (the user sees the change in the live preview; export to MP4 is a separate step).
            merged = _build_dan_revision(room_id, user_id, job_id, instruction, instruction_path)
            if not merged:
                raise RuntimeError("部分編集の適用に失敗しました（対象クリップなし or 差分なし）")
            sequence_result = merged
            timeline_result = {"sequence": merged}
            _append_job_event(room_id, job_id, {"type": "status", "text": "指示した箇所だけ反映しました（MP4は未生成・プレビューで確認できます）。"})
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
        _update_content(room_id, content_id, {"status": "ready", **_timeline_patch()})
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

        # fps=30 forces a CONSTANT frame rate. Source phone screen recordings are often
        # variable-frame-rate (VFR), and VFR breaks seek-by-time everywhere: the editor's
        # preview seeks to the wrong frame / freezes, and our OCR/ffmpeg trackers land on the
        # wrong timestamp. A CFR proxy makes seeking reliable across the board.
        #
        # LONG SIDE 1920 + high quality (was 720p CRF28): this proxy is what the native
        # editor shows WHILE SCRUBBING (originals are long-GOP 4K = ~200ms per seek flush,
        # physically unable to track a fast drag; the proxy seeks in ~20ms). At preview-pane
        # size a 1080x1920 cq16 proxy is indistinguishable from the original — the old
        # 406x720 CRF28 one is what read as "proxy-ish mush". Filmora ships the same trick:
        # its MediaProxy cache holds 1080x1920 ~19Mbps files for 4K sources (verified with
        # ffprobe on a real install) — its "4K scrubbing" runs on those.
        #
        # SHORT GOP (keyframe every 15 frames = 0.5s) + no B-frames: any frame is cheap to
        # reach from a keyframe, which is what makes scrub seeks ~20ms.
        _common = ["-g", "15", "-bf", "0", "-vsync", "cfr",
                   "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(proxy)]
        _vf = ["-vf", "scale=w=1920:h=1920:force_original_aspect_ratio=decrease:force_divisible_by=2,fps=30"]
        _encoders = [
            ["-c:v", "h264_nvenc", "-rc", "vbr", "-cq", "16", "-b:v", "0", "-preset", "p4"],
            ["-c:v", "libx264", "-preset", "veryfast", "-crf", "17"],
        ]
        _done = False
        for _enc in _encoders:
            _r = subprocess.run(
                [_ffmpeg(), "-y", "-i", str(src), *_vf, *_enc, *_common],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                check=False,
            )
            if _r.returncode == 0 and proxy.exists() and proxy.stat().st_size > 0:
                _done = True
                break
        if not _done:
            raise RuntimeError("proxy encode failed (nvenc and libx264)")
        # PTS sidecar (Filmora keeps the same table next to its proxies): every source video
        # frame's pts in seconds. The native editor snaps proxy->original switches to these
        # so VFR sources can't flicker by one frame when a scrub settles.
        try:
            _pr = subprocess.run(
                [_ffmpeg().replace("ffmpeg.exe", "ffprobe.exe"), "-v", "error",
                 "-select_streams", "v:0", "-show_entries", "packet=pts_time",
                 "-of", "csv=p=0", str(src)],
                capture_output=True, text=True, creationflags=creationflags, check=False,
            )
            _pts = sorted(float(x) for x in _pr.stdout.split() if x and x != "N/A")
            if _pts:
                _tmp = out_dir / f"{asset_id}_proxy.pts.json.tmp"
                _tmp.write_text(json.dumps({"v": 1, "pts": [round(x, 6) for x in _pts]}))
                _tmp.replace(out_dir / f"{asset_id}_proxy.pts.json")
        except Exception:
            pass  # sidecar is an enhancement, never block the proxy
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


def _contents_using_asset(room_id: str, asset_id: str) -> list[dict[str, Any]]:
    """Contents (projects) whose timeline references this asset — so deleting it doesn't silently
    break a project the user still wants."""
    out: list[dict[str, Any]] = []
    for content in _read_contents(room_id):
        ids: set[str] = {str(a) for a in (content.get("asset_ids") or [])}
        seq = (content.get("timeline") or {}).get("sequence") or {}
        for track in seq.get("tracks", []) or []:
            for clip in track.get("clips", []) or []:
                if clip.get("asset_id"):
                    ids.add(str(clip["asset_id"]))
        if asset_id in ids:
            out.append({"id": content.get("id"), "title": content.get("title") or "(無題)"})
    return out


@router.delete("/{asset_id}")
async def delete_asset(
    asset_id: str,
    room_id: str = Query(...),
    force: bool = Query(False),
    current_user: TokenData = Depends(get_current_user),
):
    """Delete a source asset: removes its record AND its files (local copy, proxy, thumbnail).
    Refuses (409) if a project still uses it, unless `force=true`."""
    assets = _read_assets(room_id)
    asset = next((a for a in assets if a.get("id") == asset_id), None)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    using = _contents_using_asset(room_id, asset_id)
    if using and not force:
        raise HTTPException(status_code=409, detail={"message": "asset in use", "contents": using})
    _remove_asset_files(asset)
    _write_assets(room_id, [a for a in assets if a.get("id") != asset_id])
    return {"ok": True, "removed_from_contents": using}


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


# --- pop-out overlay bake (v4) -------------------------------------------------------------
# One bake per (asset, padded source range, card box, canvas, look) produces a single
# `{key}.pv.mp4` with TWO H.264 tracks (v:0 color / v:1 alpha-as-luma). Everything derives
# from it with no re-matting: the native engine composites it directly (HW decode — the old
# ProRes 4444 .mov was 200+Mbps CPU-only and dragged the whole timeline down), the browser
# preview plays per-track `-c copy` remuxes, and the export alphamerges the two tracks.
# The range is padded so trim/split/move NEVER re-bake (only growing past the pad does).
POPOUT_BAKE_PAD_S = 3.0
_POPOUT_BAKING: dict[str, bool] = {}  # f"{room_id}/{key}" -> in-flight (this process)


def _popout_cache_dir(room_id: str) -> Path:
    d = ASSET_ROOT / room_id / "popout-cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _popout_box_px(box: dict[str, Any] | None, W: int, H: int) -> tuple[int, int, int, int]:
    b = box if isinstance(box, dict) else {}
    ow = max(2, round(float(b.get("width") or 0.46) * W))
    oh = max(2, round(float(b.get("height") or 0.145) * H))
    px = round(float(b.get("x") or 0.27) * W)
    py = round(float(b.get("y") or 0.835) * H)
    return px, py, ow, oh


def _popout_bake_range(asset: dict[str, Any], ss: float, se: float) -> tuple[float, float]:
    """Padded bake window clamped to the asset, so trims within the pad need no re-bake."""
    bs = max(0.0, ss - POPOUT_BAKE_PAD_S)
    be = se + POPOUT_BAKE_PAD_S
    meta = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
    dur = float(meta.get("duration") or 0)
    if dur > 0:
        be = min(be, dur)
    return round(bs, 3), round(max(be, bs + 0.1), 3)


def _popout_key(asset_id: str, bs: float, be: float, box_px: tuple[int, int, int, int],
                W: int, H: int, intensity: str, shadow: Any) -> str:
    # v7: accurate-seek time base (lipsync) + matte-only twin for the native live
    # compositor. v6 short-GOP, v5 full-range alpha +
    # auto-extended canvas (margins). Bumping re-bakes older caches on next editor open.
    px, py, ow, oh = box_px
    key_src = f"v7|{asset_id}|{bs:.3f}|{be:.3f}|{px},{py},{ow},{oh}|{W}x{H}|{intensity}|{bool(shadow is not False)}"
    return hashlib.sha1(key_src.encode()).hexdigest()[:16]


def _popout_bake_sync(source_path: Path, out_pv: Path, box_px: tuple[int, int, int, int],
                      W: int, H: int, bs: float, be: float, intensity: str, shadow: Any,
                      progress_file: Path | None) -> None:
    """Run the bake script to a temp file, then atomically publish. Blocking — call in a thread."""
    px, py, ow, oh = box_px
    part = out_pv.with_suffix(".part.mp4")
    script = PROJECT_ROOT / "scripts" / "popout_overlay.py"
    args = [sys.executable, str(script), str(source_path), "--out", str(part),
            "--W", str(W), "--H", str(H), "--box", f"{px},{py},{ow},{oh}",
            "--start", f"{bs:.3f}", "--duration", f"{max(0.1, be - bs):.3f}",
            "--intensity", intensity, "--fps", "30",
            "--meta-file", str(out_pv.parent / f"{out_pv.name.split('.')[0]}.json"),
            "--matte-out", str(out_pv.parent / f"{out_pv.name.split('.')[0]}.mt.mp4")]
    if shadow is False:
        args.append("--no-shadow")
    if progress_file is not None:
        args.extend(["--progress-file", str(progress_file)])
    subprocess.run(args, check=True)
    os.replace(part, out_pv)


def _popout_margins(cache_dir: Path, key: str) -> dict[str, float]:
    """Canvas-extension margins the bake recorded ({key}.json), normalized to the base frame.
    The editor composes these into the clip's display position so the extended canvas lands
    exactly where the un-extended one did."""
    try:
        with open(cache_dir / f"{key}.json", encoding="utf-8") as f:
            m = (json.load(f) or {}).get("margins") or {}
    except (OSError, ValueError):
        m = {}
    return {k: float(m.get(k) or 0.0) for k in ("l", "t", "r", "b")}


def _popout_read_progress(progress_file: Path) -> dict[str, Any]:
    try:
        with open(progress_file, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


@router.post("/popout-overlay")
async def generate_popout_overlay(payload: dict = Body(...)):
    """Start (or reuse) the pop-out overlay bake for one clip and return immediately with the
    cache key + bake window; the editor polls /popout-overlay/status and shows a progress bar.
    The card box / intensity / shadow are captured once at apply (template look) — the display
    position is the user's and never triggers a re-bake; neither do trims within the pad."""
    room_id = str(payload.get("room_id") or "")
    asset_id = str(payload.get("asset_id") or "")
    if not room_id or not asset_id:
        raise HTTPException(status_code=400, detail="room_id and asset_id required")
    asset = next((a for a in _read_assets(room_id) if a.get("id") == asset_id), None)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    source_path = _asset_hires_path(asset)  # matte from the ORIGINAL, not the low-res proxy
    fmt = str(payload.get("format") or "9:16")
    W, H = _output_size(fmt)
    box_px = _popout_box_px(payload.get("position"), W, H)
    ss = max(0.0, float(payload.get("source_start") or 0.0))
    se = max(ss + 0.1, float(payload.get("source_end") or (ss + 4.0)))
    intensity = str(payload.get("intensity") or "mid")
    # contact shadow is opt-in now (user: no black ring / no translucent silhouette)
    shadow = payload.get("shadow") is True
    bs, be = _popout_bake_range(asset, ss, se)
    key = _popout_key(asset_id, bs, be, box_px, W, H, intensity, shadow)
    cache_dir = _popout_cache_dir(room_id)
    out_pv = cache_dir / f"{key}.pv.mp4"
    progress_file = cache_dir / f"{key}.progress.json"
    resp = {"key": key, "bake_start": bs, "bake_end": be, "format": fmt, "bake_v": 6,
            "url": f"/api/v1/production-assets/popout-overlay/media?room_id={room_id}&key={key}"}
    if out_pv.exists() and out_pv.stat().st_size > 0:
        return {**resp, "ready": True, "progress": 100, "cached": True,
                "margins": _popout_margins(cache_dir, key)}
    flight_key = f"{room_id}/{key}"
    prog = _popout_read_progress(progress_file)
    if _POPOUT_BAKING.get(flight_key):
        return {**resp, "ready": False, "progress": int(prog.get("pct") or 0)}

    async def _bake() -> None:
        try:
            await asyncio.to_thread(
                _popout_bake_sync, source_path, out_pv, box_px, W, H, bs, be,
                intensity, shadow, progress_file)
        except Exception as exc:  # noqa: BLE001
            logger.warning("popout overlay generation failed (%s): %s", key, exc)
            try:
                with open(progress_file, "w", encoding="utf-8") as f:
                    json.dump({"done": 0, "total": 1, "pct": 0, "error": str(exc)}, f)
            except OSError:
                pass
        finally:
            _POPOUT_BAKING.pop(flight_key, None)

    _POPOUT_BAKING[flight_key] = True
    asyncio.create_task(_bake())
    return {**resp, "ready": False, "progress": 0}


@router.get("/popout-overlay/status")
async def get_popout_overlay_status(room_id: str = Query(...), key: str = Query(...)):
    safe = re.sub(r"[^0-9a-f]", "", key)[:32]
    cache_dir = ASSET_ROOT / room_id / "popout-cache"
    out_pv = cache_dir / f"{safe}.pv.mp4"
    if out_pv.exists() and out_pv.stat().st_size > 0:
        return {"ready": True, "progress": 100, "margins": _popout_margins(cache_dir, safe)}
    prog = _popout_read_progress(cache_dir / f"{safe}.progress.json")
    if prog.get("error"):
        return {"ready": False, "progress": 0, "error": str(prog["error"])}
    running = _POPOUT_BAKING.get(f"{room_id}/{safe}", False)
    # a progress file without a live bake (e.g. server restarted mid-bake) is stale — tell the
    # editor so it can re-POST instead of watching a frozen bar
    if not running and prog:
        return {"ready": False, "progress": int(prog.get("pct") or 0), "stale": True}
    return {"ready": False, "progress": int(prog.get("pct") or 0), "running": running}


@router.get("/popout-overlay/media")
async def get_popout_overlay(request: Request, room_id: str = Query(...), key: str = Query(...),
                             stream: str = Query("color")):
    """Serve a single-track remux of the bake for the browser preview: `stream=color` (v:0) or
    `stream=alpha` (v:1, matte in luma). Both are plain H.264 → HW-decoded <video> elements;
    the editor merges them on a canvas (no VP9 encode anywhere). Legacy pre-v4 keys still serve
    their .webm so old clips keep previewing until they are auto-upgraded."""
    safe = re.sub(r"[^0-9a-f]", "", key)[:32]
    cache_dir = ASSET_ROOT / room_id / "popout-cache"
    out_pv = cache_dir / f"{safe}.pv.mp4"
    if not out_pv.exists():
        # legacy fallback serves the .webm for the COLOR stream only — it carries its own alpha,
        # and handing it out as the matte would cut the color by its luma (wrong)
        legacy = (cache_dir / f"{safe}.webm").resolve()
        if stream != "alpha" and legacy.exists() and legacy.is_file():
            return _range_file_response(legacy, request)
        raise HTTPException(status_code=404, detail="overlay not found")
    which = "alpha" if stream == "alpha" else "color"
    track = 1 if which == "alpha" else 0
    remux = cache_dir / f"{safe}.{which}.mp4"
    if not remux.exists() or remux.stat().st_size == 0 or remux.stat().st_mtime < out_pv.stat().st_mtime:
        part = cache_dir / f"{safe}.{which}.part.mp4"
        await asyncio.to_thread(subprocess.run, [
            _ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(out_pv),
            "-map", f"0:v:{track}", "-c", "copy", "-movflags", "+faststart", str(part)], check=True)
        os.replace(part, remux)
    return _range_file_response(remux.resolve(), request)


# --- SAM 3 tracked blur-mask bake ------------------------------------------------------------
# One bake per (asset, padded source range, target spec) produces `{key}.mask.mp4` — a
# grayscale H.264 mask video (255 = blur here), CFR 30, aligned to the padded window.
# scripts/blur_mask_bake.py runs in the dedicated venv_sam3 env (SAM 3.1 needs py3.12+;
# the sandbox is py3.10). Two engines inside the script: box/points-only -> fast
# tracker-only (~0.5s/frame), text concept -> multiplex PCS (~4s/frame/object).
# The native editor and export consume the mask directly (mask x blur / maskedmerge).
BLUR_BAKE_PAD_S = 1.5
_BLUR_BAKING: dict[str, bool] = {}  # f"{room_id}/{key}" -> in-flight (this process)
VENV_SAM3_PY = PROJECT_ROOT / "venv_sam3" / "Scripts" / "python.exe"


def _blur_cache_dir(room_id: str) -> Path:
    d = ASSET_ROOT / room_id / "blur-cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _blur_read_progress(progress_file: Path) -> dict[str, Any]:
    """blur_mask_bake.py writes {"stage": str, "progress": 0..1}."""
    try:
        with open(progress_file, encoding="utf-8") as f:
            p = json.load(f) or {}
        return {"pct": int(float(p.get("progress") or 0) * 100), "stage": p.get("stage")}
    except (OSError, ValueError):
        return {}


BLUR_WORKER_PORT = 8876


def _blur_job_payload(source_path: Path, out_mask: Path, spec: dict[str, Any],
                      bs: float, be: float, progress_file: Path) -> dict[str, Any]:
    """The bake job in blur_mask_bake CLI vocabulary (shared by the resident worker and
    the classic one-shot subprocess)."""
    job: dict[str, Any] = {
        "src": str(source_path), "out": str(out_mask),
        "start": round(bs, 3), "duration": round(max(0.1, be - bs), 3), "fps": 30,
        "feather": int(spec.get("feather") or 3), "dilate": int(spec.get("dilate") or 2),
        "progress_file": str(progress_file),
    }
    # anchor = the SOURCE second whose frame defines "the object inside the box"
    # (the editor sends the playhead frame the user was looking at). Script wants it
    # relative to the window start.
    if spec.get("anchor") is not None:
        job["anchor"] = round(min(max(0.0, float(spec["anchor"]) - bs), max(0.0, be - bs - 0.05)), 3)
    if spec.get("prompt"):
        job["prompt"] = str(spec["prompt"])
    if spec.get("box"):
        x, y, w, h = [float(v) for v in spec["box"]]
        job["box"] = f"{x:.4f},{y:.4f},{w:.4f},{h:.4f}"
    pts = [f"{float(p[0]):.4f},{float(p[1]):.4f},{'+' if int(p[2]) else '-'}"
           for p in (spec.get("points") or [])]
    if pts:
        job["point"] = pts
    if spec.get("keep_ids"):
        job["keep_ids"] = ",".join(str(int(v)) for v in spec["keep_ids"])
    return job


def _blur_worker_post(path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any] | None:
    """POST to the resident worker; None when it is not reachable (spawn or fall back)."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        f"http://127.0.0.1:{BLUR_WORKER_PORT}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        # worker reached but the bake failed — surface it, don't silently re-run cold
        try:
            detail = json.loads(e.read() or b"{}").get("error")
        except ValueError:
            detail = str(e)
        raise RuntimeError(f"blur worker bake failed: {detail}")
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return None


def _ensure_blur_worker() -> bool:
    """Spawn the resident worker DETACHED (it must survive sandbox restarts) and wait for
    /health. Returns False when it cannot be started (caller falls back to one-shot)."""
    import urllib.request
    script = PROJECT_ROOT / "scripts" / "blur_mask_worker.py"
    if not VENV_SAM3_PY.exists() or not script.exists():
        return False
    try:
        # `cmd /c start` breaks the parent-child chain: the sandbox restarts with
        # taskkill /T (tree kill) and a directly-spawned worker died with it every time.
        # cmd exits immediately, the worker is orphaned, the tree walk can't reach it.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            ["cmd", "/c", "start", "/b", "", str(VENV_SAM3_PY), "-u", str(script)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags, close_fds=True)
    except OSError as exc:
        logger.warning("blur worker spawn failed: %s", exc)
        return False
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{BLUR_WORKER_PORT}/health", timeout=2):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def _blur_mask_bake_sync(source_path: Path, out_mask: Path, spec: dict[str, Any],
                         bs: float, be: float, progress_file: Path) -> None:
    """Blocking bake — call in a thread. Three rungs: resident worker (models stay on the
    GPU, ~0s start) -> spawn the worker then retry -> classic one-shot subprocess (pays
    the ~24s model load). Files are published atomically by the bake itself."""
    job = _blur_job_payload(source_path, out_mask, spec, bs, be, progress_file)
    r = _blur_worker_post("/bake", job, timeout=3600)
    if r is None and _ensure_blur_worker():
        r = _blur_worker_post("/bake", job, timeout=3600)
    if r is not None:
        if not r.get("ok"):
            raise RuntimeError(f"blur worker bake failed: rc={r.get('rc')}")
        return
    logger.warning("blur worker unavailable — one-shot subprocess fallback (cold load)")
    script = PROJECT_ROOT / "scripts" / "blur_mask_bake.py"
    if not VENV_SAM3_PY.exists():
        raise RuntimeError(f"venv_sam3 missing ({VENV_SAM3_PY}) — see scripts/blur_mask_bake.py header")
    args = [str(VENV_SAM3_PY), "-u", str(script), job["src"], "--out", job["out"],
            "--start", str(job["start"]), "--duration", str(job["duration"]),
            "--fps", "30", "--feather", str(job["feather"]), "--dilate", str(job["dilate"]),
            "--progress-file", job["progress_file"]]
    if "anchor" in job:
        args += ["--anchor", str(job["anchor"])]
    if job.get("prompt"):
        args += ["--prompt", job["prompt"]]
    if job.get("box"):
        args += ["--box", job["box"]]
    for p in job.get("point") or []:
        args += ["--point", p]
    if job.get("keep_ids"):
        args += ["--keep-ids", job["keep_ids"]]
    subprocess.run(args, check=True)


def _blur_prompt_to_english(prompt: str) -> str:
    """SAM 3's text encoder is trained on ENGLISH noun phrases — translate non-ASCII
    prompts via the flat-rate CLI (never the metered API). Blocking; call in a thread."""
    p = (prompt or "").strip()
    if not p or all(ord(ch) < 128 for ch in p):
        return p
    try:
        from app.agent.cli_runner import run_oneshot_cli
        out = run_oneshot_cli(
            "Translate this Japanese description of a VISUAL object into a SHORT English "
            "noun phrase for an open-vocabulary object detector (examples: 'person in red "
            "shirt', 'license plate', 'coffee cup'). Use the pattern '<noun> in <attribute>' "
            "for clothing/appearance — NEVER the word 'wearing' (it breaks the detector). "
            "Reply with the noun phrase ONLY.\n\n" + p,
            "haiku", 45)
        out = (out or "").strip().strip('"').strip()
        return out or p
    except Exception as exc:  # noqa: BLE001
        logger.warning("blur prompt translation failed (%s); using raw prompt", exc)
        return p


def _ensure_blur_mask_started(room_id: str, asset: dict[str, Any], spec: dict[str, Any],
                              ss: float, se: float) -> dict[str, Any]:
    """Start (or reuse) a tracked blur-mask bake. Sync-safe: usable from the async endpoint
    AND from the Dan assembler (plain thread, no event loop needed). Returns the same shape
    the endpoint responds with; the mask lands in blur-cache/{key}.mask.mp4."""
    source_path = _asset_hires_path(asset)
    asset_id = str(asset.get("id"))
    bs = max(0.0, ss - BLUR_BAKE_PAD_S)
    be = se + BLUR_BAKE_PAD_S
    meta = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
    dur = float(meta.get("duration") or 0)
    if dur > 0:
        be = min(be, dur)
    bs, be = round(bs, 3), round(max(be, bs + 0.1), 3)
    key_src = f"v2|{asset_id}|{bs:.3f}|{be:.3f}|{json.dumps(spec, sort_keys=True)}"
    key = hashlib.sha1(key_src.encode()).hexdigest()[:16]
    cache_dir = _blur_cache_dir(room_id)
    out_mask = cache_dir / f"{key}.mask.mp4"
    progress_file = cache_dir / f"{key}.progress.json"
    resp = {"key": key, "bake_start": bs, "bake_end": be, "fps": 30,
            "path": str(out_mask),
            "url": f"/api/v1/production-assets/blur-mask/media?room_id={room_id}&key={key}"}
    if out_mask.exists() and out_mask.stat().st_size > 0:
        return {**resp, "ready": True, "progress": 100, "cached": True}
    flight_key = f"{room_id}/{key}"
    prog = _blur_read_progress(progress_file)
    if _BLUR_BAKING.get(flight_key):
        return {**resp, "ready": False, "progress": int(prog.get("pct") or 0)}

    def _bake() -> None:
        try:
            _blur_mask_bake_sync(source_path, out_mask, spec, bs, be, progress_file)
        except Exception as exc:  # noqa: BLE001
            logger.warning("blur mask bake failed (%s): %s", key, exc)
            try:
                with open(progress_file, "w", encoding="utf-8") as f:
                    json.dump({"stage": "error", "progress": 0, "error": str(exc)}, f)
            except OSError:
                pass
        finally:
            _BLUR_BAKING.pop(flight_key, None)

    _BLUR_BAKING[flight_key] = True
    threading.Thread(target=_bake, daemon=True, name=f"blur-bake-{key}").start()
    return {**resp, "ready": False, "progress": 0}


@router.post("/blur-mask")
async def generate_blur_mask(payload: dict = Body(...)):
    """Start (or reuse) a tracked blur-mask bake for one clip window and return immediately
    with the cache key; the editor polls /blur-mask/status. Target = box (fast single-object)
    or prompt (noun phrase -> ALL instances; Japanese is auto-translated) or points."""
    room_id = str(payload.get("room_id") or "")
    asset_id = str(payload.get("asset_id") or "")
    if not room_id or not asset_id:
        raise HTTPException(status_code=400, detail="room_id and asset_id required")
    asset = next((a for a in _read_assets(room_id) if a.get("id") == asset_id), None)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    prompt = str(payload.get("prompt") or "").strip() or None
    if prompt:
        prompt = await asyncio.to_thread(_blur_prompt_to_english, prompt)
    spec = {
        "prompt": prompt,
        "box": payload.get("box"),
        "points": payload.get("points"),
        "keep_ids": payload.get("keep_ids"),
        "feather": payload.get("feather"),
        "dilate": payload.get("dilate"),
        "anchor": payload.get("anchor"),
    }
    if not spec["prompt"] and not spec["box"] and not spec["points"]:
        raise HTTPException(status_code=400, detail="prompt, box or points required")
    ss = max(0.0, float(payload.get("source_start") or 0.0))
    se = max(ss + 0.1, float(payload.get("source_end") or (ss + 4.0)))
    resp = _ensure_blur_mask_started(room_id, asset, spec, ss, se)
    return {**resp, "prompt_used": prompt} if prompt else resp


@router.get("/blur-mask/status")
async def get_blur_mask_status(room_id: str = Query(...), key: str = Query(...)):
    safe = re.sub(r"[^0-9a-f]", "", key)[:16]
    cache_dir = ASSET_ROOT / room_id / "blur-cache"
    out_mask = cache_dir / f"{safe}.mask.mp4"
    if out_mask.exists() and out_mask.stat().st_size > 0:
        return {"ready": True, "progress": 100, "path": str(out_mask)}
    prog = _blur_read_progress(cache_dir / f"{safe}.progress.json")
    try:
        with open(cache_dir / f"{safe}.progress.json", encoding="utf-8") as f:
            err = (json.load(f) or {}).get("error")
    except (OSError, ValueError):
        err = None
    if err:
        return {"ready": False, "progress": 0, "error": str(err)}
    running = _BLUR_BAKING.get(f"{room_id}/{safe}", False)
    if not running and prog:
        return {"ready": False, "progress": int(prog.get("pct") or 0), "stale": True}
    return {"ready": False, "progress": int(prog.get("pct") or 0),
            "stage": prog.get("stage"), "running": running}


@router.get("/blur-mask/media")
async def get_blur_mask_media(request: Request, room_id: str = Query(...), key: str = Query(...)):
    safe = re.sub(r"[^0-9a-f]", "", key)[:16]
    out_mask = (ASSET_ROOT / room_id / "blur-cache" / f"{safe}.mask.mp4").resolve()
    if not out_mask.exists():
        raise HTTPException(status_code=404, detail="mask not found")
    return _range_file_response(out_mask, request)


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


def _load_content_decisions(room_id: str, content_id: str, timeline: dict[str, Any]) -> dict[str, Any] | None:
    """The editing decisions for a content: prefer the copy stored on the timeline; fall back to
    the latest dan_plan job's dan_timeline.json (for contents generated before we stored it)."""
    d = timeline.get("decisions")
    if isinstance(d, dict) and d.get("spine"):
        return d
    jobs = [j for j in _read_jobs(room_id) if j.get("content_id") == content_id]
    jobs.sort(key=lambda j: str(j.get("created_at") or ""), reverse=True)
    for j in jobs:
        jid = str(j.get("id") or "")
        if not jid:
            continue
        p = _room_dir(room_id) / "jobs" / jid / "dan_timeline.json"
        if p.exists():
            try:
                saved = json.loads(p.read_text(encoding="utf-8"))
                dd = saved.get("decisions") if isinstance(saved, dict) else None
                if isinstance(dd, dict) and dd.get("spine"):
                    return dd
            except Exception:
                continue
    return None


def _recut_assemble(room_id: str, content_id: str, decisions: dict[str, Any], asset_ids: list[str], fmt: str) -> dict[str, Any] | None:
    """Re-assemble a content's timeline from stored decisions with (possibly) new cut params.
    Whisper analysis is cached on asset metadata, so this is fast and uses no LLM."""
    assets = _read_assets(room_id)
    wanted = {str(a) for a in asset_ids}
    src_assets = [
        {"id": a.get("id"), "kind": a.get("kind"), "filename": a.get("filename"),
         "local_path": a.get("local_path"), "proxy_path": a.get("proxy_path"), "metadata": a.get("metadata")}
        for a in assets if str(a.get("id")) in wanted
    ]
    transcripts = _run_audio_analysis(room_id, f"recut_{content_id}", src_assets)
    return _assemble_sequence_from_decisions(decisions, transcripts, room_id, fmt)


_CAPTION_CACHE_GUARD = __import__("threading").Lock()
_CAPTION_INFLIGHT: set[str] = set()


@router.post("/caption-cache")
async def caption_cache(
    payload: dict[str, Any] = Body(...),
    current_user: TokenData = Depends(get_current_user),
):
    """Designed-caption PNGs for the NATIVE preview — the exact /caption-frame render the
    export burns in, cached per (canvas, text, words, design). Returns key/path/ready per
    item immediately; missing ones render in a background thread (one browser launch for
    the whole batch) and appear on disk, where the native app picks them up."""
    room_id = str(payload.get("room_id") or "")
    if not room_id:
        raise HTTPException(status_code=400, detail="room_id required")
    out_w = int(payload.get("outW") or 1080)
    out_h = int(payload.get("outH") or 1920)
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    cache_dir = _room_dir(room_id) / "caption-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    to_render: list[dict[str, Any]] = []
    render_keys: list[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        text = str(it.get("text") or "").strip()
        design = it.get("design") if isinstance(it.get("design"), dict) else {}
        words = it.get("words") if isinstance(it.get("words"), list) else []
        key_src = json.dumps(
            {"w": out_w, "h": out_h, "t": text, "d": design, "words": words},
            ensure_ascii=False, sort_keys=True,
        )
        key = hashlib.sha1(key_src.encode()).hexdigest()[:16]
        png = cache_dir / f"{key}.png"
        ready = png.exists() and png.stat().st_size > 0
        results.append({"key": key, "ready": ready})
        if not ready and text:
            with _CAPTION_CACHE_GUARD:
                if key in _CAPTION_INFLIGHT:
                    continue
                _CAPTION_INFLIGHT.add(key)
            render_keys.append(key)
            # animated designs get their MID frame — a designed still beats plain text;
            # the export still burns the full animation
            to_render.append({"png": str(png), "text": text, "time": 0.0,
                              "design": design, "words": words})
    if to_render:
        spec_path = cache_dir / f"_spec_{render_keys[0]}.json"
        spec_path.write_text(
            json.dumps({"outW": out_w, "outH": out_h,
                        "web_base": os.environ.get("DAN_CAPTION_RENDER_BASE", "http://127.0.0.1:3000"),
                        "items": to_render}, ensure_ascii=False),
            encoding="utf-8",
        )

        def _run(spec=spec_path, keys=tuple(render_keys)) -> None:
            try:
                script = PROJECT_ROOT / "scripts" / "render_caption_pngs.py"
                cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                subprocess.run([sys.executable, str(script), str(spec)],
                               capture_output=True, timeout=600, creationflags=cflags)
            except Exception as exc:  # noqa: BLE001
                logger.warning("caption-cache render failed: %s", exc)
            finally:
                with _CAPTION_CACHE_GUARD:
                    for k in keys:
                        _CAPTION_INFLIGHT.discard(k)
                try:
                    spec.unlink()
                except Exception:  # noqa: BLE001
                    pass

        __import__("threading").Thread(target=_run, daemon=True).start()
    return {"results": results, "rendering": len(to_render)}


@router.post("/contents/{content_id}/recut")
async def recut_content(
    content_id: str,
    payload: dict[str, Any] = Body(default={}),
    room_id: str = Query(...),
    current_user: TokenData = Depends(get_current_user),
):
    """Re-cut (re-assemble) the timeline with adjusted silence threshold / pads, FireCut-style.
    Rebuilds from the stored editing decisions + cached transcript — Dan's semantic decisions
    (what to keep/drop) are unchanged; only the silence/dead-air tightness is re-applied."""
    contents = _read_contents(room_id)
    content = next((c for c in contents if c.get("id") == content_id), None)
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
    timeline = dict(content.get("timeline") or {})
    decisions = _load_content_decisions(room_id, content_id, timeline)
    if not decisions:
        raise HTTPException(status_code=400, detail="この素材は自動カット情報が無いため再カットできません（ダンで作り直してください）")
    d = dict(decisions)
    if payload.get("silence_threshold") is not None:
        try:
            d["silence_threshold"] = max(0.2, min(3.0, float(payload["silence_threshold"])))
        except Exception:
            pass
    if payload.get("lead") is not None:
        try:
            d["lead"] = max(0.0, min(1.0, float(payload["lead"])))
        except Exception:
            pass
    if payload.get("tail") is not None:
        try:
            d["tail"] = max(0.0, min(1.5, float(payload["tail"])))
        except Exception:
            pass
    fmt = str(timeline.get("format") or content.get("format") or "9:16")
    asset_ids = content.get("asset_ids") or []
    try:
        sequence = await asyncio.to_thread(_recut_assemble, room_id, content_id, d, asset_ids, fmt)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"再カットに失敗しました: {exc}")
    if not sequence:
        raise HTTPException(status_code=500, detail="再カットの組み立てに失敗しました（解析データが無い可能性）")
    timeline["sequence"] = sequence
    timeline["decisions"] = d
    _update_content(room_id, content_id, {"timeline": timeline})
    return {
        "ok": True,
        "cut_params": sequence.get("cut_params"),
        "removed_total": sequence.get("removed_total"),
        "cut_count": len(sequence.get("cut_meta") or []),
        "clip_count": sum(len(t.get("clips") or []) for t in sequence.get("tracks", [])),
        "duration": sequence.get("duration"),
        "sequence": sequence,
    }


def _caption_sync_source_clips(sequence: dict[str, Any]) -> list[dict[str, Any]]:
    """Clips carrying the speech + source mapping used to time a caption: prefer dialogue audio
    clips; fall back to base (non-PiP) video clips. One set only, so words aren't double-counted."""
    audio: list[dict[str, Any]] = []
    video: list[dict[str, Any]] = []
    for track in sequence.get("tracks") or []:
        tt = track.get("type")
        for cl in track.get("clips") or []:
            if not isinstance(cl, dict):
                continue
            if tt == "audio" and cl.get("role") in (None, "dialogue", "main"):
                audio.append(cl)
            elif tt == "video" and str(cl.get("composition") or "") != "pip":
                video.append(cl)
    return audio or video


def _words_for_caption(
    sequence: dict[str, Any], caption: dict[str, Any], analysis_by_asset: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Per-word timeline timings for a caption, by reading the Whisper words of the speech clips
    under it and mapping their asset-seconds to the timeline via each clip's source mapping."""
    cts = float(caption.get("timeline_start") or 0)
    cte = float(caption.get("timeline_end") or cts)
    out: list[dict[str, Any]] = []
    for cl in _caption_sync_source_clips(sequence):
        ts = float(cl.get("timeline_start") or 0)
        te = float(cl.get("timeline_end") or ts)
        if te <= cts or ts >= cte:
            continue
        analysis = analysis_by_asset.get(str(cl.get("asset_id") or ""))
        if not analysis:
            continue
        src0 = float(cl.get("source_start") or 0)
        s_lo = src0 + (max(cts, ts) - ts)
        s_hi = src0 + (min(cte, te) - ts)
        for seg in analysis.get("segments") or []:
            for w in seg.get("words") or []:
                ws = float(w.get("start") or 0)
                we = float(w.get("end") or ws)
                if ws < s_hi and we > s_lo:
                    txt = str(w.get("word") or "").strip()
                    if not txt:
                        continue
                    t0 = ts + (max(ws, s_lo) - src0)
                    t1 = ts + (min(we, s_hi) - src0)
                    out.append({"text": txt, "start": round(t0, 3), "end": round(max(t1, t0 + 0.05), 3)})
    out.sort(key=lambda x: x["start"])
    return out


def _ensure_audio_analysis(room_id: str, asset_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Return {asset_id: analysis(segments with words)} using cached metadata.audio_analysis when
    present, else running dan_audio_check --words once and caching it on the asset."""
    whisper_model = os.environ.get("DAN_PLAN_WHISPER_MODEL", "medium")
    assets = _read_assets(room_id)
    by_id = {a.get("id"): a for a in assets}
    script = PROJECT_ROOT / "scripts" / "dan_audio_check.py"
    cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    out: dict[str, dict[str, Any]] = {}
    dirty = False
    for aid in dict.fromkeys(asset_ids):
        a = by_id.get(aid)
        if not a or a.get("kind") != "video":
            continue
        meta = a.get("metadata") if isinstance(a.get("metadata"), dict) else {}
        src = a.get("proxy_path") or a.get("local_path")
        cached = meta.get("audio_analysis")
        if (isinstance(cached, dict) and cached.get("segments")
                and meta.get("audio_analysis_src") == str(src) and meta.get("audio_analysis_model") == whisper_model):
            out[aid] = cached
            continue
        if not src or not Path(src).exists():
            continue
        out_json = Path(src).with_name(Path(src).stem + "_audiocheck.json")
        try:
            subprocess.run(
                [sys.executable, str(script), str(src), "--words", "--json-only", "--model", whisper_model],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900, check=False, creationflags=cflags,
            )
            data = json.loads(out_json.read_text(encoding="utf-8")) if out_json.exists() else {}
        except Exception:
            data = {}
        entry = {"asset_id": aid, "duration": data.get("duration"), "segments": data.get("segments") or []}
        out[aid] = entry
        meta = dict(meta)
        meta["audio_analysis"] = entry
        meta["audio_analysis_src"] = str(src)
        meta["audio_analysis_model"] = whisper_model
        a["metadata"] = meta
        dirty = True
    if dirty:
        _write_assets(room_id, assets)
    return out


class CaptionSyncRequest(BaseModel):
    room_id: str
    caption_ids: list[str] | None = None  # None / empty = all captions


@router.post("/contents/{content_id}/caption-sync")
async def caption_sync(
    content_id: str,
    payload: CaptionSyncRequest,
    current_user: TokenData = Depends(get_current_user),
):
    """Attach per-word timings (from the speech under each caption) so karaoke / typewriter sync
    to the actual voice. Uses cached Whisper analysis when available (instant), else runs it."""
    contents = _read_contents(payload.room_id)
    content = next((c for c in contents if c.get("id") == content_id), None)
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
    timeline = dict(content.get("timeline") or {})
    sequence = timeline.get("sequence")
    if not isinstance(sequence, dict):
        raise HTTPException(status_code=400, detail="シーケンスがありません")
    caps = _sequence_caption_clips(sequence)
    want = set(payload.caption_ids or [])
    targets = [c for c in caps if not want or str(c.get("id")) in want]
    if not targets:
        raise HTTPException(status_code=400, detail="対象のテロップがありません")
    asset_ids = [str(c.get("asset_id")) for c in _caption_sync_source_clips(sequence) if c.get("asset_id")]
    analysis = await asyncio.to_thread(_ensure_audio_analysis, payload.room_id, asset_ids)
    words_by_caption: dict[str, list[dict[str, Any]]] = {}
    for cap in targets:
        cid = str(cap.get("id"))
        words = _words_for_caption(sequence, cap, analysis)
        words_by_caption[cid] = words
    return {"words_by_caption": words_by_caption, "synced": sum(1 for v in words_by_caption.values() if v)}


class ScreenBlurRequest(BaseModel):
    room_id: str
    enabled: bool = True
    targets: list[str] = Field(default_factory=list)   # exact strings to hide
    patterns: list[str] = Field(default_factory=list)  # email / digits / key
    regex: str | None = None
    style: str = "mosaic"
    pad: float = 0.35
    fps: float = 4.0


class TrackBlurRequest(BaseModel):
    room_id: str
    x: float           # normalized 0-1 box the user drew
    y: float
    width: float
    height: float
    anchor: float = 0.0  # time (s) the box was drawn = the frame to read the target text from
    start: float = 0.0   # scan window start (0 = whole clip)
    end: float = 0.0     # scan window end (0 = to the end)
    fps: float = 4.0


def _content_source_video(room_id: str, content: dict[str, Any]) -> str | None:
    assets = _assets_by_id(room_id)
    for aid in content.get("asset_ids") or []:
        a = assets.get(str(aid))
        if a and a.get("kind") == "video":
            src = a.get("proxy_path") or a.get("local_path")
            if src and Path(src).exists():
                return str(src)
    return None


@router.post("/contents/{content_id}/screen-blur")
async def set_screen_blur(
    content_id: str, payload: ScreenBlurRequest, current_user: TokenData = Depends(get_current_user)
):
    """Save the screen-blur spec on the content; it is baked into the next export (post-pass)."""
    contents = _read_contents(payload.room_id)
    content = next((c for c in contents if c.get("id") == content_id), None)
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
    timeline = dict(content.get("timeline") or {})
    timeline["screen_blur"] = {
        "enabled": bool(payload.enabled), "targets": payload.targets, "patterns": payload.patterns,
        "regex": payload.regex, "style": payload.style, "pad": payload.pad, "fps": payload.fps,
    }
    _update_content(payload.room_id, content_id, {"timeline": timeline})
    return {"ok": True, "screen_blur": timeline["screen_blur"]}


@router.post("/contents/{content_id}/screen-blur/probe")
async def probe_screen_blur(
    content_id: str, payload: ScreenBlurRequest, current_user: TokenData = Depends(get_current_user)
):
    """Detect-only: report which on-screen texts WOULD be blurred (+ a sample of all detected text)
    so the editor can show the user what will be hidden before exporting."""
    contents = _read_contents(payload.room_id)
    content = next((c for c in contents if c.get("id") == content_id), None)
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
    src = _content_source_video(payload.room_id, content)
    if not src:
        raise HTTPException(status_code=400, detail="解析できる動画素材がありません")
    script = PROJECT_ROOT / "scripts" / "screen_blur.py"
    cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # 8 frames keeps the interactive probe under the dev proxy's ~30s timeout (OCR ~2.8s/frame on
    # CPU). The probe is only a PREVIEW of what will be hidden; the export post-pass checks the
    # whole video (no timeout) and is authoritative.
    args = [sys.executable, str(script), str(src), "--probe", "--probe-frames", "8"]
    if payload.targets:
        args += ["--targets", ",".join(payload.targets)]
    if payload.patterns:
        args += ["--patterns", ",".join(payload.patterns)]
    if payload.regex:
        args += ["--regex", payload.regex]
    r = await asyncio.to_thread(
        subprocess.run, args, capture_output=True, text=True, timeout=300, creationflags=cflags
    )
    data: dict[str, Any] = {"matched": [], "sample_texts": [], "frames": 0}
    try:
        lines = [ln for ln in (r.stdout or "").strip().splitlines() if ln.strip().startswith("{")]
        if lines:
            data = json.loads(lines[-1])
    except Exception:  # noqa: BLE001
        pass
    return data


def _active_video_clip_at(sequence: dict[str, Any], anchor: float, box_cx: float, box_cy: float) -> dict[str, Any] | None:
    """The video clip the user is actually looking at: among clips active at the anchor timeline
    time, prefer an overlay/PiP whose output rect contains the box centre (higher layer wins),
    else the fullscreen base clip. Returns None if there's no usable sequence."""
    active = [c for c in _sequence_video_clips(sequence)
              if float(c.get("timeline_start") or 0) <= anchor < float(c.get("timeline_end") or 0)]
    if not active:
        return None
    def rect(c: dict[str, Any]) -> tuple[float, float, float, float]:
        p = c.get("position") if isinstance(c.get("position"), dict) else None
        if p:
            return float(p.get("x") or 0), float(p.get("y") or 0), float(p.get("width") or 1), float(p.get("height") or 1)
        return 0.0, 0.0, 1.0, 1.0
    overlays = sorted([c for c in active if _is_overlay_clip(c)], key=lambda c: -(c.get("layer") or 0))
    for c in overlays:
        rx, ry, rw, rh = rect(c)
        if rx <= box_cx <= rx + rw and ry <= box_cy <= ry + rh:
            return c
    base = [c for c in active if not _is_overlay_clip(c)]
    return base[0] if base else active[0]


@router.post("/contents/{content_id}/blur/track")
async def track_blur_region(
    content_id: str, payload: TrackBlurRequest, current_user: TokenData = Depends(get_current_user)
):
    """OCR-track the TEXT inside the drawn box, ACROSS the composition. Finds the clip shown at the
    playhead, uses THAT asset, maps playhead-time -> that clip's source-time, and maps the drawn box
    (output coords) -> source coords via the clip's cover-fit — so we read the right asset, the right
    frame, the right region even when clips have source offsets or a different aspect. Returns the
    output-normalized path keyed by TIMELINE time + the visible time range (which DEFINES the clip)."""
    contents = _read_contents(payload.room_id)
    content = next((c for c in contents if c.get("id") == content_id), None)
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
    timeline = content.get("timeline") if isinstance(content.get("timeline"), dict) else {}
    sequence = timeline.get("sequence") if isinstance(timeline, dict) else None
    out_w, out_h = _output_size(str((sequence or {}).get("format") or timeline.get("format") or content.get("format") or "9:16"))

    box_cx = payload.x + payload.width / 2.0
    box_cy = payload.y + payload.height / 2.0
    clip = _active_video_clip_at(sequence, payload.anchor, box_cx, box_cy) if isinstance(sequence, dict) else None

    if clip:
        assets = _assets_by_id(payload.room_id)
        asset = assets.get(str(clip.get("asset_id") or ""))
        if not asset:
            raise HTTPException(status_code=400, detail="クリップの素材が見つかりません")
        try:
            src = str(_asset_source_path(asset))
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="解析できる動画素材がありません")
        tl_start = float(clip.get("timeline_start") or 0)
        tl_end = float(clip.get("timeline_end") or 0)
        src_start = float(clip.get("source_start") or 0)
        # The renderer trims a long source to the SLOT length at 1x speed (see _clip_source_range),
        # so source time maps 1:1 and the effective source range is just the timeline span.
        clip_src_end = src_start + max(0.05, tl_end - tl_start)
        src_anchor = src_start + max(0.0, payload.anchor - tl_start)
        t_offset = tl_start - src_start
        # Scan a BOUNDED window around the anchor (not the whole clip) so the interactive call stays
        # responsive — OCR costs ~1s PER FRAME (fixed model cost), so a full-clip scan timed out
        # (300s). Keep the frame count small; the user re-analyses elsewhere if the text spans more.
        scan_lead, scan_window = 1.0, 9.0
        src_scan_start = max(src_start, src_anchor - scan_lead)
        src_end = min(clip_src_end, src_anchor + scan_window)
        pos = clip.get("position") if isinstance(clip.get("position"), dict) else None
        clip_rect = (
            f"{float(pos.get('x') or 0)},{float(pos.get('y') or 0)},{float(pos.get('width') or 1)},{float(pos.get('height') or 1)}"
            if pos else "0,0,1,1"
        )
    else:
        # No sequence (single raw clip) — fall back to the first source, anchor as source time.
        src = _content_source_video(payload.room_id, content)
        if not src:
            raise HTTPException(status_code=400, detail="解析できる動画素材がありません")
        src_anchor, t_offset, clip_rect = payload.anchor, 0.0, "0,0,1,1"
        src_scan_start = max(0.0, payload.anchor - 1.5)
        src_end = (payload.anchor + 18.0) if payload.end <= 0 else min(payload.end, payload.anchor + 18.0)

    script = PROJECT_ROOT / "scripts" / "screen_blur.py"
    cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    scan_fps = min(max(0.5, payload.fps), 1.5)  # cap: OCR is ~1s/frame, so keep the sample count low
    args = [
        sys.executable, str(script), str(src), "--ocr-track",
        "--box", f"{payload.x},{payload.y},{payload.width},{payload.height}",
        "--anchor", str(src_anchor), "--start", str(src_scan_start), "--end", str(src_end),
        "--out-w", str(out_w), "--out-h", str(out_h), "--clip-rect", clip_rect,
        "--t-offset", str(t_offset), "--fps", str(scan_fps), "--ffmpeg", _ffmpeg(),
    ]
    try:
        r = await asyncio.to_thread(
            subprocess.run, args, capture_output=True, text=True, timeout=90, creationflags=cflags
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="解析がタイムアウトしました（範囲を狭めて再試行してください）")
    data: dict[str, Any] = {"found": False, "boxes": {}}
    try:
        lines = [ln for ln in (r.stdout or "").strip().splitlines() if ln.strip().startswith("{")]
        if lines:
            data = json.loads(lines[-1])
    except Exception:  # noqa: BLE001
        logger.warning("ocr-track parse failed: %s | %s", (r.stdout or "")[-200:], (r.stderr or "")[-200:])
    return data


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
