"""
inquiry の API エンドポイント
- POST /inquiries は無認証・IP単位レート制限。クライアントHPから叩く。
- GET /inquiries は認証必須。運用画面で閲覧する。
"""
import time
import logging
from collections import defaultdict, deque
from typing import Deque, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.services.auth_service import TokenData, decode_access_token
from app.services.inquiry_service import InquiryService
from app.models.inquiry_schemas import InquiryCreate, InquiryResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inquiries", tags=["inquiries"])
security = HTTPBearer(auto_error=False)
ACCESS_TOKEN_COOKIE = "done_access_token"

WINDOW_SECONDS = 60 * 60
MAX_REQUESTS_PER_WINDOW = 20
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
            detail="送信回数の上限に達しました。お手数ですが、しばらく時間をおいて再度お試しください。",
        )
    hist.append(now)


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


def get_service() -> InquiryService:
    return InquiryService()


@router.post("", response_model=InquiryResponse)
async def create_inquiry(
    data: InquiryCreate,
    request: Request,
    service: InquiryService = Depends(get_service),
):
    ip = _client_ip(request)
    _check_rate_limit(ip)
    ua = request.headers.get("user-agent", "")[:500]
    try:
        result = await service.create(
            scope=data.scope,
            name=data.name,
            email=data.email,
            phone=data.phone,
            company=data.company,
            message=data.message,
            source_url=data.source_url,
            user_agent=ua,
            client_ip=ip,
        )
        return result
    except Exception as e:
        logger.exception("inquiry create failed")
        raise HTTPException(status_code=500, detail=f"送信に失敗しました: {e}")


@router.get("", response_model=List[InquiryResponse])
async def list_inquiries(
    scope: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    user: TokenData = Depends(get_current_user),
    service: InquiryService = Depends(get_service),
):
    return await service.list(scope=scope, limit=limit)


@router.patch("/{inquiry_id}", response_model=InquiryResponse)
async def update_status(
    inquiry_id: str,
    status: str = Query(..., regex="^(new|read|replied|archived)$"),
    user: TokenData = Depends(get_current_user),
    service: InquiryService = Depends(get_service),
):
    result = await service.update_status(inquiry_id, status)
    if not result:
        raise HTTPException(status_code=404, detail="Inquiry not found")
    return result
