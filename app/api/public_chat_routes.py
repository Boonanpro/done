"""
public_chat の API エンドポイント
無認証・IP単位スライディングウィンドウでレート制限 (30 req/hour)。
"""
import time
import logging
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import APIRouter, Depends, HTTPException, Request

from app.models.public_chat_schemas import PublicChatRequest, PublicChatResponse
from app.services.public_chat_service import PublicChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public-chat", tags=["public-chat"])

WINDOW_SECONDS = 60 * 60
MAX_REQUESTS_PER_WINDOW = 30
MAX_BURST_PER_MINUTE = 6

_ip_history: Dict[str, Deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _check_rate_limit(ip: str) -> None:
    now = time.time()
    hist = _ip_history[ip]
    cutoff = now - WINDOW_SECONDS
    while hist and hist[0] < cutoff:
        hist.popleft()
    if len(hist) >= MAX_REQUESTS_PER_WINDOW:
        raise HTTPException(
            status_code=429,
            detail="利用回数の上限に達しました。しばらく時間をおいて再度お試しください。",
        )
    recent = sum(1 for t in hist if t > now - 60)
    if recent >= MAX_BURST_PER_MINUTE:
        raise HTTPException(
            status_code=429,
            detail="連続送信が多すぎます。少し待ってから再度お試しください。",
        )
    hist.append(now)


def get_service() -> PublicChatService:
    return PublicChatService()


@router.post("/messages", response_model=PublicChatResponse)
async def post_message(
    data: PublicChatRequest,
    request: Request,
    service: PublicChatService = Depends(get_service),
):
    _check_rate_limit(_client_ip(request))
    try:
        result = await service.respond(
            scope=data.scope,
            messages=data.messages,
            system_context=data.system_context,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("public_chat failed")
        raise HTTPException(status_code=500, detail=f"チャット応答失敗: {e}")
