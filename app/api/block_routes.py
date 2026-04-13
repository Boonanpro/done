"""Block API Routes — Dan Workspace (Notion-style information hub)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.api.chat_routes import TokenData, get_current_user
from app.models.block_schemas import (
    BlockCreate,
    BlockMove,
    BlockUpdate,
)
from app.services.block_service import get_block_service

router = APIRouter(prefix="/blocks", tags=["blocks"])


@router.post("")
async def create_block(
    payload: BlockCreate,
    current_user: TokenData = Depends(get_current_user),
):
    service = get_block_service()
    data = payload.model_dump(mode="json", exclude_none=False)
    try:
        block = await service.create_block(current_user.user_id, data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return block


@router.get("/tree")
async def get_tree(current_user: TokenData = Depends(get_current_user)):
    service = get_block_service()
    return {"nodes": await service.get_tree(current_user.user_id)}


@router.get("/starred")
async def get_starred(current_user: TokenData = Depends(get_current_user)):
    service = get_block_service()
    return {"blocks": await service.get_starred(current_user.user_id)}


@router.get("/recent")
async def get_recent(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: TokenData = Depends(get_current_user),
):
    service = get_block_service()
    return {"blocks": await service.get_recent(current_user.user_id, limit=limit)}


@router.get("/children")
async def list_children(
    parent_id: str | None = Query(default=None),
    current_user: TokenData = Depends(get_current_user),
):
    service = get_block_service()
    blocks = await service.list_children(current_user.user_id, parent_id)
    return {"blocks": blocks, "total": len(blocks)}


@router.get("/{block_id}")
async def get_block(
    block_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    service = get_block_service()
    block = await service.get_block(current_user.user_id, block_id)
    if not block:
        raise HTTPException(status_code=404, detail="block not found")
    return block


@router.patch("/{block_id}")
async def update_block(
    block_id: str,
    payload: BlockUpdate,
    current_user: TokenData = Depends(get_current_user),
):
    service = get_block_service()
    updates = payload.model_dump(mode="json", exclude_none=True)
    block = await service.update_block(current_user.user_id, block_id, updates)
    if not block:
        raise HTTPException(status_code=404, detail="block not found")
    return block


@router.delete("/{block_id}")
async def delete_block(
    block_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    service = get_block_service()
    ok = await service.delete_block(current_user.user_id, block_id)
    if not ok:
        raise HTTPException(status_code=404, detail="block not found")
    return {"deleted": True}


@router.post("/{block_id}/restore")
async def restore_block(
    block_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    service = get_block_service()
    ok = await service.restore_block(current_user.user_id, block_id)
    if not ok:
        raise HTTPException(status_code=404, detail="block not found")
    return {"restored": True}


@router.post("/{block_id}/move")
async def move_block(
    block_id: str,
    payload: BlockMove,
    current_user: TokenData = Depends(get_current_user),
):
    service = get_block_service()
    block = await service.move_block(
        user_id=current_user.user_id,
        block_id=block_id,
        parent_id=str(payload.parent_id) if payload.parent_id else None,
        after_block_id=str(payload.after_block_id) if payload.after_block_id else None,
        before_block_id=str(payload.before_block_id) if payload.before_block_id else None,
    )
    if not block:
        raise HTTPException(status_code=404, detail="block not found")
    return block


@router.post("/{block_id}/files")
async def attach_file(
    block_id: str,
    file: UploadFile = File(...),
    current_user: TokenData = Depends(get_current_user),
):
    service = get_block_service()
    suffix = Path(file.filename or "").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    try:
        result = await service.attach_file(
            user_id=current_user.user_id,
            block_id=block_id,
            source_path=tmp_path,
            original_name=file.filename or "unnamed",
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if not result:
        raise HTTPException(status_code=404, detail="block not found")
    return result


@router.get("/{block_id}/files")
async def list_files(
    block_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    service = get_block_service()
    files = await service.list_files(current_user.user_id, block_id)
    return {"files": files}
