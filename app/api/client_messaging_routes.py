"""
Client messaging API.

Two groups of endpoints:
  - Public client auth (no auth required):     /api/v1/client-messaging/auth/*
  - Owner-side account management (owner JWT): /api/v1/client-messaging/accounts/*
"""
from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.models.client_messaging_schemas import (
    ClientAccountCreate,
    ClientAccountResponse,
    ClientLogoutRequest,
    ClientRefreshRequest,
    ClientTokenPair,
    MagicLinkRequest,
    MagicLinkRequestResponse,
    MagicLinkVerifyRequest,
)
from app.services.auth_service import TokenData, decode_access_token
from app.services.client_messaging_service import (
    CLIENT_ACCESS_TOKEN_TTL,
    ClientMessagingService,
    ClientTokenData,
    create_client_access_token,
    decode_client_access_token,
    send_magic_link_email,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/client-messaging", tags=["client_messaging"])

security = HTTPBearer(auto_error=False)
ACCESS_TOKEN_COOKIE = "done_access_token"


def get_service() -> ClientMessagingService:
    return ClientMessagingService()


# ==================== Auth dependencies ====================


async def get_current_owner(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> TokenData:
    """Resolve the owner (Dan user) from cookie or Bearer header."""
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token and credentials:
        token = credentials.credentials
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    td = decode_access_token(token)
    if not td:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return td


async def get_current_client(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> ClientTokenData:
    """Resolve the client account from a client-access JWT (Bearer only)."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    td = decode_client_access_token(credentials.credentials)
    if not td:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return td


# ==================== Helpers ====================


def _build_token_pair(
    service: ClientMessagingService,
    account: dict,
    user_agent: Optional[str],
    ip: Optional[str],
) -> ClientTokenPair:
    refresh_token = service.create_session(
        client_account_id=account["id"],
        user_agent=user_agent,
        ip=ip,
    )
    access_token = create_client_access_token(account["id"], account["email"])
    return ClientTokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=int(CLIENT_ACCESS_TOKEN_TTL.total_seconds()),
        client_account=ClientAccountResponse.model_validate(account),
    )


def _request_metadata(request: Request) -> tuple[Optional[str], Optional[str]]:
    user_agent = request.headers.get("user-agent")
    ip = request.headers.get("x-forwarded-for") or (
        request.client.host if request.client else None
    )
    if ip and "," in ip:
        ip = ip.split(",", 1)[0].strip()
    return user_agent, ip


def _build_magic_link_url(token: str) -> str:
    base = settings.FRONTEND_URL or "http://localhost:3000"
    base = base.rstrip("/")
    return f"{base}/client/login?token={quote(token, safe='')}"


# ==================== Owner-side: account management ====================


@router.post("/accounts", response_model=ClientAccountResponse)
async def create_client_account(
    data: ClientAccountCreate,
    owner: TokenData = Depends(get_current_owner),
    service: ClientMessagingService = Depends(get_service),
):
    """Owner registers a client_account for one of their clients, and
    bootstraps the direct collab_room. Idempotent on email."""
    # Verify client belongs to the owner
    client_row = (
        service.supabase.table("clients")
        .select("id, name, user_id")
        .eq("id", str(data.client_id))
        .limit(1)
        .execute()
    )
    if not client_row.data or client_row.data[0]["user_id"] != owner.user_id:
        raise HTTPException(status_code=404, detail="クライアントが見つかりません")
    client = client_row.data[0]

    account = service.create_or_get_account(
        client_id=str(data.client_id),
        email=str(data.email),
        display_name=data.display_name,
        locale=data.locale,
    )
    if not account:
        raise HTTPException(status_code=500, detail="アカウント作成に失敗しました")

    # Make sure the direct room exists
    service.ensure_direct_room(
        owner_id=owner.user_id,
        client_account_id=account["id"],
        title=client["name"],
    )

    return ClientAccountResponse.model_validate(account)


@router.get("/accounts", response_model=list[ClientAccountResponse])
async def list_client_accounts(
    owner: TokenData = Depends(get_current_owner),
    service: ClientMessagingService = Depends(get_service),
):
    """List client accounts the owner has direct rooms with."""
    rooms = (
        service.supabase.table("collab_rooms")
        .select("client_account_id")
        .eq("owner_id", owner.user_id)
        .eq("room_type", "direct")
        .not_.is_("client_account_id", "null")
        .execute()
    )
    account_ids = [r["client_account_id"] for r in (rooms.data or []) if r.get("client_account_id")]
    if not account_ids:
        return []
    accounts = (
        service.supabase.table("client_accounts")
        .select("*")
        .in_("id", account_ids)
        .order("created_at", desc=True)
        .execute()
    )
    return [ClientAccountResponse.model_validate(a) for a in (accounts.data or [])]


@router.post("/accounts/{account_id}/resend-link", response_model=MagicLinkRequestResponse)
async def resend_magic_link(
    account_id: str,
    request: Request,
    owner: TokenData = Depends(get_current_owner),
    service: ClientMessagingService = Depends(get_service),
):
    """Owner-initiated: send a fresh magic link to a client account."""
    # Verify ownership via direct room
    room = (
        service.supabase.table("collab_rooms")
        .select("id")
        .eq("owner_id", owner.user_id)
        .eq("client_account_id", account_id)
        .eq("room_type", "direct")
        .limit(1)
        .execute()
    )
    if not room.data:
        raise HTTPException(status_code=404, detail="クライアントが見つかりません")

    account = service.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="アカウントが見つかりません")

    user_agent, ip = _request_metadata(request)
    token = service.issue_magic_link(account["id"], ip=ip, user_agent=user_agent)
    link = _build_magic_link_url(token)
    if not send_magic_link_email(account["email"], link, account.get("display_name")):
        raise HTTPException(status_code=502, detail="メール送信に失敗しました")
    return MagicLinkRequestResponse(ok=True, message=f"ログインリンクを {account['email']} に送信しました。")


# ==================== Client-side: auth ====================


@router.post("/auth/request", response_model=MagicLinkRequestResponse)
async def request_magic_link(
    data: MagicLinkRequest,
    request: Request,
    service: ClientMessagingService = Depends(get_service),
):
    """Public: client submits email to receive a magic link.
    Response is generic regardless of whether the email is registered,
    to avoid leaking account existence."""
    account = service.get_account_by_email(str(data.email))
    if account:
        user_agent, ip = _request_metadata(request)
        token = service.issue_magic_link(account["id"], ip=ip, user_agent=user_agent)
        link = _build_magic_link_url(token)
        sent = send_magic_link_email(account["email"], link, account.get("display_name"))
        if not sent:
            logger.warning("Magic link email failed for %s", account["email"])
    # Always return the same generic response
    return MagicLinkRequestResponse()


@router.post("/auth/verify", response_model=ClientTokenPair)
async def verify_magic_link(
    data: MagicLinkVerifyRequest,
    request: Request,
    service: ClientMessagingService = Depends(get_service),
):
    """Public: exchange a magic-link token for access + refresh tokens."""
    account = service.consume_magic_link(data.token)
    if not account:
        raise HTTPException(status_code=400, detail="リンクが無効または期限切れです")
    user_agent, ip = _request_metadata(request)
    return _build_token_pair(service, account, user_agent, ip)


@router.post("/auth/refresh", response_model=ClientTokenPair)
async def refresh_client_session(
    data: ClientRefreshRequest,
    request: Request,
    service: ClientMessagingService = Depends(get_service),
):
    user_agent, ip = _request_metadata(request)
    rotated = service.rotate_refresh_token(data.refresh_token, user_agent=user_agent, ip=ip)
    if not rotated:
        raise HTTPException(status_code=401, detail="セッションが無効です")
    new_refresh, account_id = rotated
    account = service.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="アカウントが見つかりません")
    access_token = create_client_access_token(account["id"], account["email"])
    return ClientTokenPair(
        access_token=access_token,
        refresh_token=new_refresh,
        expires_in=int(CLIENT_ACCESS_TOKEN_TTL.total_seconds()),
        client_account=ClientAccountResponse.model_validate(account),
    )


@router.post("/auth/logout")
async def client_logout(
    data: ClientLogoutRequest,
    service: ClientMessagingService = Depends(get_service),
):
    service.revoke_session(data.refresh_token)
    return {"ok": True}


@router.get("/auth/me", response_model=ClientAccountResponse)
async def client_me(
    token: ClientTokenData = Depends(get_current_client),
    service: ClientMessagingService = Depends(get_service),
):
    account = service.get_account(token.client_account_id)
    if not account:
        raise HTTPException(status_code=404, detail="アカウントが見つかりません")
    return ClientAccountResponse.model_validate(account)
