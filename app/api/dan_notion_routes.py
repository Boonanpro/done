"""ダン用Notion: API ルート"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.models.dan_notion_schemas import (
    BLOCK_TYPES,
    BlockCreate,
    BlockMove,
    BlockResponse,
    BlockUpdate,
    BlockVersionResponse,
    NotificationResponse,
    SearchHit,
    SearchRequest,
    TriggerCreate,
    TriggerResponse,
    TriggerRunResponse,
    TriggerUpdate,
)
from app.services.auth_service import TokenData, decode_access_token
from app.services.dan_notion_service import DanNotionService, get_dan_notion_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dan-notion", tags=["dan-notion"])

security = HTTPBearer(auto_error=False)
ACCESS_TOKEN_COOKIE = "done_access_token"


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> TokenData:
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token and credentials:
        token = credentials.credentials
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    td = decode_access_token(token)
    if not td:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return td


def _svc() -> DanNotionService:
    return get_dan_notion_service()


# ============================================================
# Blocks
# ============================================================

@router.get("/pages", response_model=list[BlockResponse])
async def list_root_pages(user: TokenData = Depends(get_current_user)):
    return _svc().list_root_pages(user.user_id)


@router.get("/blocks/{block_id}", response_model=BlockResponse)
async def get_block(block_id: str, user: TokenData = Depends(get_current_user)):
    block = _svc().get_block(user.user_id, block_id)
    if not block:
        raise HTTPException(status_code=404, detail="ブロックが見つかりません")
    return block


@router.get("/blocks/{block_id}/children", response_model=list[BlockResponse])
async def list_children(block_id: str, user: TokenData = Depends(get_current_user)):
    if not _svc().get_block(user.user_id, block_id):
        raise HTTPException(status_code=404, detail="ブロックが見つかりません")
    return _svc().list_children(user.user_id, block_id)


@router.post("/blocks", response_model=BlockResponse)
async def create_block(data: BlockCreate, user: TokenData = Depends(get_current_user)):
    if data.type not in BLOCK_TYPES:
        raise HTTPException(status_code=400, detail=f"不正な block type: {data.type}")
    payload = data.model_dump()
    result = _svc().create_block(user.user_id, payload)
    if not result:
        raise HTTPException(status_code=400, detail="作成に失敗しました")
    return result


@router.patch("/blocks/{block_id}", response_model=BlockResponse)
async def update_block(
    block_id: str, data: BlockUpdate, user: TokenData = Depends(get_current_user)
):
    result = _svc().update_block(user.user_id, block_id, data.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(status_code=404, detail="ブロックが見つかりません")
    return result


@router.delete("/blocks/{block_id}")
async def delete_block(block_id: str, user: TokenData = Depends(get_current_user)):
    if not _svc().soft_delete_block(user.user_id, block_id):
        raise HTTPException(status_code=404, detail="ブロックが見つかりません")
    return {"ok": True}


@router.post("/blocks/{block_id}/move", response_model=BlockResponse)
async def move_block(
    block_id: str, data: BlockMove, user: TokenData = Depends(get_current_user)
):
    result = _svc().move_block(
        user.user_id,
        block_id,
        str(data.parent_id) if data.parent_id else None,
        str(data.after_block_id) if data.after_block_id else None,
        str(data.before_block_id) if data.before_block_id else None,
    )
    if not result:
        raise HTTPException(status_code=404, detail="ブロックが見つかりません")
    return result


# ============================================================
# Versions
# ============================================================

@router.get("/blocks/{block_id}/versions", response_model=list[BlockVersionResponse])
async def list_versions(block_id: str, user: TokenData = Depends(get_current_user)):
    return _svc().list_versions(user.user_id, block_id)


@router.post("/blocks/{block_id}/restore/{version}", response_model=BlockResponse)
async def restore_version(
    block_id: str, version: int, user: TokenData = Depends(get_current_user)
):
    result = _svc().restore_version(user.user_id, block_id, version)
    if not result:
        raise HTTPException(status_code=404, detail="バージョンが見つかりません")
    return result


# ============================================================
# Triggers
# ============================================================

@router.get("/triggers", response_model=list[TriggerResponse])
async def list_triggers(user: TokenData = Depends(get_current_user)):
    return _svc().list_triggers(user.user_id)


@router.post("/triggers", response_model=TriggerResponse)
async def create_trigger(
    data: TriggerCreate, user: TokenData = Depends(get_current_user)
):
    result = _svc().create_trigger(user.user_id, data.model_dump())
    if not result:
        raise HTTPException(status_code=400, detail="作成に失敗しました")
    return result


@router.patch("/triggers/{trigger_id}", response_model=TriggerResponse)
async def update_trigger(
    trigger_id: str, data: TriggerUpdate, user: TokenData = Depends(get_current_user)
):
    result = _svc().update_trigger(
        user.user_id, trigger_id, data.model_dump(exclude_unset=True)
    )
    if not result:
        raise HTTPException(status_code=404, detail="トリガーが見つかりません")
    return result


@router.delete("/triggers/{trigger_id}")
async def delete_trigger(trigger_id: str, user: TokenData = Depends(get_current_user)):
    if not _svc().delete_trigger(user.user_id, trigger_id):
        raise HTTPException(status_code=404, detail="トリガーが見つかりません")
    return {"ok": True}


@router.post("/triggers/{trigger_id}/fire")
async def fire_trigger(trigger_id: str, user: TokenData = Depends(get_current_user)):
    """トリガーを手動で発火 (Autopilot ランナーをスレッド起動)"""
    triggers = _svc().list_triggers(user.user_id)
    trig = next((t for t in triggers if t["id"] == trigger_id), None)
    if not trig:
        raise HTTPException(status_code=404, detail="トリガーが見つかりません")
    from app.agent.autopilot.runner import execute_trigger_async
    handle = execute_trigger_async(user.user_id, trig, {"kind": "manual"})
    return {"ok": True, "handle": handle}


@router.get("/trigger-runs", response_model=list[TriggerRunResponse])
async def list_trigger_runs(
    trigger_id: Optional[str] = None,
    limit: int = 50,
    user: TokenData = Depends(get_current_user),
):
    return _svc().list_trigger_runs(user.user_id, trigger_id, limit)


@router.get("/trigger-runs/{run_id}/traces")
async def list_traces(run_id: str, user: TokenData = Depends(get_current_user)):
    return _svc().list_traces(user.user_id, run_id)


# ============================================================
# Notifications
# ============================================================

@router.get("/notifications", response_model=list[NotificationResponse])
async def list_notifications(
    unread_only: bool = False,
    limit: int = 50,
    user: TokenData = Depends(get_current_user),
):
    return _svc().list_notifications(user.user_id, unread_only, limit)


@router.post("/notifications/{notification_id}/read")
async def mark_read(notification_id: str, user: TokenData = Depends(get_current_user)):
    if not _svc().mark_notification_read(user.user_id, notification_id):
        raise HTTPException(status_code=404, detail="通知が見つかりません")
    return {"ok": True}


# ============================================================
# 自然言語検索 (Phase 7)
# ============================================================

@router.post("/search", response_model=list[SearchHit])
async def search_blocks(
    req: SearchRequest, user: TokenData = Depends(get_current_user)
):
    """pgvector + multilingual-e5-small で類似検索"""
    try:
        from app.services.dan_notion_search import search as vector_search
        return vector_search(user.user_id, req.query, req.limit)
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="sentence-transformers 未インストール。pip install sentence-transformers",
        )


@router.post("/reindex")
async def reindex(user: TokenData = Depends(get_current_user)):
    """全ブロックを再インデックス (初回 / バックフィル用)"""
    try:
        from app.services.dan_notion_search import reindex_user
        return reindex_user(user.user_id)
    except ImportError:
        raise HTTPException(status_code=503, detail="sentence-transformers 未インストール")
