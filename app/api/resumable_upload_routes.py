"""Bounded, resumable transport for chat attachments (including collab guests)."""
import asyncio
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field
from starlette.datastructures import Headers, UploadFile

router = APIRouter()
ROOT = Path(__file__).resolve().parents[2] / "uploads"
STAGING = ROOT / ".transfers"
CHUNK = 8 * 1024 * 1024
MAX_SIZE = 2 * 1024 * 1024 * 1024
TTL = 24 * 3600
_locks: dict[str, asyncio.Lock] = {}


class StartUpload(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0, le=MAX_SIZE)
    content_type: str = Field(default="application/octet-stream", max_length=160)
    room_id: str | None = None


async def identity(request: Request, room_id: str | None) -> str:
    credentials = await HTTPBearer(auto_error=False)(request)
    if room_id:
        from app.api.collab_routes import (
            ACCESS_TOKEN_COOKIE, _decode_guest_token, _get_guest_token_from_request,
            decode_access_token, get_collab_service,
        )
        if not room_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in room_id):
            raise HTTPException(400, "Invalid room")
        token = request.cookies.get(ACCESS_TOKEN_COOKIE) or (credentials.credentials if credentials else None)
        owner = decode_access_token(token) if token else None
        if owner and await get_collab_service().verify_room_access(room_id, user_id=owner.user_id):
            return "user:" + owner.user_id
        guest_token = _get_guest_token_from_request(request, credentials)
        guest = _decode_guest_token(guest_token) if guest_token else None
        if guest and guest.get("room_id") == room_id:
            return "guest:" + hashlib.sha256(guest_token.encode()).hexdigest()
        raise HTTPException(403, "Access denied")
    from app.api.chat_routes import get_current_user
    user = await get_current_user(request, credentials)
    return "user:" + user.user_id


def paths(upload_id: str):
    try:
        if str(uuid.UUID(upload_id)) != upload_id:
            raise ValueError()
    except ValueError:
        raise HTTPException(404, "Upload not found")
    return STAGING / (upload_id + ".json"), STAGING / (upload_id + ".part")


def save(path: Path, value: dict):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    os.replace(temporary, path)


async def load(request: Request, upload_id: str):
    meta, part = paths(upload_id)
    if not meta.exists():
        raise HTTPException(404, "Upload expired")
    data = json.loads(meta.read_text(encoding="utf-8"))
    if await identity(request, data.get("room_id")) != data["owner"]:
        raise HTTPException(403, "Access denied")
    if time.time() - data["created"] > TTL:
        raise HTTPException(410, "Upload expired")
    return meta, part, data


@router.post("/transfers")
async def start(body: StartUpload, request: Request):
    owner = await identity(request, body.room_id)
    from app.api.file_routes import is_allowed_file
    if not is_allowed_file(body.filename):
        raise HTTPException(415, "Unsupported file type")
    STAGING.mkdir(parents=True, exist_ok=True)
    # Remove only expired transport files. Published attachments are never removed.
    active = 0
    for meta in STAGING.glob("*.json"):
        data = json.loads(meta.read_text(encoding="utf-8"))
        if time.time() - data["created"] > TTL:
            meta.with_suffix(".part").unlink(missing_ok=True)
            meta.unlink(missing_ok=True)
            _locks.pop(meta.stem, None)
        elif data["owner"] == owner and not data.get("result"):
            active += 1
    if active >= 32:
        raise HTTPException(429, "Too many unfinished uploads")
    upload_id = str(uuid.uuid4())
    meta, part = paths(upload_id)
    data = {**body.model_dump(), "owner": owner, "created": time.time(), "offset": 0}
    part.touch()
    save(meta, data)
    return {"id": upload_id, "offset": 0, "chunk_size": CHUNK}


@router.get("/transfers/{upload_id}")
async def status(upload_id: str, request: Request):
    _, _, data = await load(request, upload_id)
    return {"offset": data["offset"], "chunk_size": CHUNK, "result": data.get("result")}


@router.put("/transfers/{upload_id}")
async def append(upload_id: str, offset: int, request: Request):
    paths(upload_id)
    async with _locks.setdefault(upload_id, asyncio.Lock()):
        meta, part, data = await load(request, upload_id)
        if data.get("result") or offset != data["offset"]:
            raise HTTPException(409, "Check upload progress before retrying")
        expected = min(CHUNK, data["size"] - offset)
        if expected <= 0:
            raise HTTPException(409, "Upload already received")
        received = 0
        # Any disconnected/partial request is truncated on the next retry.
        with part.open("r+b") as out:
            out.seek(offset)
            out.truncate()
            async for block in request.stream():
                received += len(block)
                if received > expected:
                    out.truncate(offset)
                    raise HTTPException(413, "Chunk too large")
                out.write(block)
            if received != expected:
                out.truncate(offset)
                raise HTTPException(400, "Incomplete chunk")
        data["offset"] += received
        save(meta, data)
        return {"offset": data["offset"]}


@router.post("/transfers/{upload_id}/complete")
async def complete(upload_id: str, request: Request):
    paths(upload_id)
    async with _locks.setdefault(upload_id, asyncio.Lock()):
        meta, part, data = await load(request, upload_id)
        if data.get("result"):
            return data["result"]
        if data["offset"] != data["size"]:
            raise HTTPException(409, "Upload is incomplete")
        if data.get("room_id"):
            from app.api.collab_routes import upload_file, get_collab_service
            credentials = await HTTPBearer(auto_error=False)(request)
            with part.open("rb") as source:
                uploaded = UploadFile(source, filename=data["filename"], headers=Headers({"content-type": data["content_type"]}))
                result = await upload_file(data["room_id"], uploaded, request, credentials, get_collab_service())
            result = result.model_dump(mode="json")
        else:
            name = upload_id + Path(data["filename"]).suffix.lower()
            destination = ROOT / name
            if part.exists():
                os.replace(part, destination)
            result = {"id": upload_id, "filename": data["filename"], "url": "/api/v1/files/" + name,
                      "content_type": data["content_type"], "size": data["size"],
                      "created_at": datetime.now(timezone.utc).isoformat()}
        data["result"] = result
        save(meta, data)
        part.unlink(missing_ok=True)
        return result
