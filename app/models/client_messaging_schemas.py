"""
Pydantic schemas for client_messaging feature.

Persistent client accounts + magic-link auth for friend-style direct chat
between an owner (Dan user) and a client.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# ==================== Client Account ====================


class ClientAccountCreate(BaseModel):
    """Owner-side request to register a client account against an existing client."""
    client_id: UUID
    email: EmailStr
    display_name: Optional[str] = None
    locale: str = "ja"


class ClientAccountResponse(BaseModel):
    id: UUID
    client_id: UUID
    email: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    locale: str
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ==================== Magic Link ====================


class MagicLinkRequest(BaseModel):
    """Public endpoint: client submits their email to receive a login link."""
    email: EmailStr


class MagicLinkRequestResponse(BaseModel):
    """Generic response — same shape whether the email is registered or not
    (avoid leaking which emails have accounts)."""
    ok: bool = True
    message: str = "ログインリンクをメールで送信しました。受信箱を確認してください。"


class MagicLinkVerifyRequest(BaseModel):
    token: str = Field(..., min_length=16, max_length=256)


class ClientTokenPair(BaseModel):
    """Issued after successful magic-link verification."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    client_account: ClientAccountResponse


class ClientRefreshRequest(BaseModel):
    refresh_token: str


class ClientLogoutRequest(BaseModel):
    refresh_token: str
