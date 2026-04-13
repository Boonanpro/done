"""Trigger API Routes — Dan Workspace Phase 3."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.chat_routes import TokenData, get_current_user
from app.models.trigger_schemas import (
    TriggerCreate,
    TriggerFireRequest,
    TriggerUpdate,
)
from app.services.trigger_service import get_trigger_service

router = APIRouter(prefix="/triggers", tags=["triggers"])


@router.post("")
async def create_trigger(
    payload: TriggerCreate,
    current_user: TokenData = Depends(get_current_user),
):
    svc = get_trigger_service()
    return await svc.create(current_user.user_id, payload.model_dump(mode="json"))


@router.get("")
async def list_triggers(
    kind: Optional[str] = Query(None),
    current_user: TokenData = Depends(get_current_user),
):
    svc = get_trigger_service()
    return {"triggers": await svc.list(current_user.user_id, kind)}


@router.get("/{trigger_id}")
async def get_trigger(
    trigger_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    svc = get_trigger_service()
    trig = await svc.get(current_user.user_id, trigger_id)
    if not trig:
        raise HTTPException(404, "trigger not found")
    return trig


@router.patch("/{trigger_id}")
async def update_trigger(
    trigger_id: str,
    payload: TriggerUpdate,
    current_user: TokenData = Depends(get_current_user),
):
    svc = get_trigger_service()
    trig = await svc.update(
        current_user.user_id,
        trigger_id,
        payload.model_dump(mode="json", exclude_none=True),
    )
    if not trig:
        raise HTTPException(404, "trigger not found")
    return trig


@router.delete("/{trigger_id}")
async def delete_trigger(
    trigger_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    svc = get_trigger_service()
    ok = await svc.delete(current_user.user_id, trigger_id)
    if not ok:
        raise HTTPException(404, "trigger not found")
    return {"ok": True}


@router.post("/{trigger_id}/fire")
async def fire_trigger(
    trigger_id: str,
    payload: TriggerFireRequest,
    current_user: TokenData = Depends(get_current_user),
):
    svc = get_trigger_service()
    try:
        return await svc.fire(current_user.user_id, trigger_id, payload.payload)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/{trigger_id}/runs")
async def list_trigger_runs(
    trigger_id: str,
    limit: int = Query(50, ge=1, le=500),
    current_user: TokenData = Depends(get_current_user),
):
    svc = get_trigger_service()
    runs = await svc.list_runs(current_user.user_id, trigger_id, limit=limit)
    return {"runs": runs}


@router.get("/runs/recent")
async def list_recent_runs(
    limit: int = Query(50, ge=1, le=500),
    current_user: TokenData = Depends(get_current_user),
):
    svc = get_trigger_service()
    runs = await svc.list_runs(current_user.user_id, None, limit=limit)
    return {"runs": runs}
