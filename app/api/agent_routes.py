"""Agent API Routes — Dan Workspace Phase 4.

エージェントトレースの一覧取得と SSE ライブストリーム。
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.chat_routes import TokenData, get_current_user
from app.services.agent_service import get_agent_service

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/traces")
async def list_traces(
    trigger_run_id: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    current_user: TokenData = Depends(get_current_user),
):
    svc = get_agent_service()
    traces = await svc.list_traces(current_user.user_id, trigger_run_id, limit)
    return {"traces": traces}


@router.get("/traces/stream")
async def stream_traces(
    current_user: TokenData = Depends(get_current_user),
):
    svc = get_agent_service()
    q = svc.subscribe()
    uid = current_user.user_id

    async def gen():
        try:
            yield "event: ready\ndata: {}\n\n"
            while True:
                try:
                    trace = await asyncio.wait_for(q.get(), timeout=25.0)
                    if trace.get("user_id") != uid:
                        continue
                    yield f"data: {json.dumps(trace, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            svc.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")
