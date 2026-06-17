from __future__ import annotations

import hashlib
import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.api.chat_artifact_routes import get_current_user
from app.services.auth_service import TokenData


router = APIRouter(prefix="/video-review", tags=["video-review"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UPLOADS_DIR = PROJECT_ROOT / "uploads"
DAN_WORKSPACE = Path("D:/dan-workspace")
SESSION_DIR = UPLOADS_DIR / "video-review-sessions"
SESSION_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
ALLOWED_ROOTS = [
    PROJECT_ROOT.resolve(),
    UPLOADS_DIR.resolve(),
    DAN_WORKSPACE.resolve(),
]


class VideoReviewAnnotation(BaseModel):
    id: str
    kind: str = Field(pattern="^(rect|freehand|marker|note)$")
    intent: str = "comment"
    label: str | None = None
    note: str | None = None
    start: float = 0
    end: float | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class VideoReviewSession(BaseModel):
    video_path: str | None = None
    video_url: str | None = None
    duration: float | None = None
    annotations: list[VideoReviewAnnotation] = Field(default_factory=list)
    updated_at: str | None = None


def _session_id(video_path: str | None, video_url: str | None) -> str:
    raw = (video_path or video_url or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="video_path or video_url is required")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _session_file(video_path: str | None, video_url: str | None) -> Path:
    return SESSION_DIR / f"{_session_id(video_path, video_url)}.json"


def _resolve_video_path(path_value: str) -> Path:
    if not path_value:
        raise HTTPException(status_code=400, detail="path is required")

    normalized = path_value.replace("\\", "/")
    if normalized.startswith("/api/v1/files/"):
        filename = normalized.rstrip("/").split("/")[-1]
        candidate = UPLOADS_DIR / filename
    else:
        candidate = Path(path_value)
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate

    resolved = candidate.resolve()
    if resolved.suffix.lower() not in ALLOWED_VIDEO_SUFFIXES:
        raise HTTPException(status_code=400, detail="Only video files are supported")
    if not any(resolved.is_relative_to(root) for root in ALLOWED_ROOTS):
        raise HTTPException(status_code=400, detail="Video path is outside allowed roots")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Video file not found")
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


@router.get("/media")
async def serve_review_media(request: Request, path: str = Query(...)):
    video_path = _resolve_video_path(path)
    return _range_file_response(video_path, request)


@router.get("/sessions")
async def get_review_session(
    video_path: str | None = Query(None),
    video_url: str | None = Query(None),
    current_user: TokenData = Depends(get_current_user),
):
    session_path = _session_file(video_path, video_url)
    if not session_path.exists():
        return {
            "id": _session_id(video_path, video_url),
            "video_path": video_path,
            "video_url": video_url,
            "annotations": [],
            "updated_at": None,
        }
    data = json.loads(session_path.read_text(encoding="utf-8"))
    return data


@router.post("/sessions")
async def save_review_session(
    data: VideoReviewSession,
    request: Request,
    current_user: TokenData = Depends(get_current_user),
):
    session_path = _session_file(data.video_path, data.video_url)
    payload = data.model_dump()
    payload["id"] = _session_id(data.video_path, data.video_url)
    payload["user_id"] = current_user.user_id
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload["client_host"] = request.client.host if request.client else None
    session_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
