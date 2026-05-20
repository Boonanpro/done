"""
Client messaging service.

Responsibilities:
  - client_accounts management (owner-side registration, lookup)
  - magic-link issuance + consumption
  - session management (refresh-token rotation, revocation)
  - direct-room bootstrap (owner ↔ client friend relationship)
  - access-token (JWT) creation and decoding

JWT design:
  Access tokens are short-lived JWTs (1h) with `type: "client_access"`. They
  sit in a separate type namespace from owner tokens (`type: "access"`) so
  owner and client tokens can never be confused.

  Refresh tokens are random opaque strings (32+ bytes), stored sha256-hashed
  in client_sessions, and rotated on each refresh. This way a leaked refresh
  token is single-use.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import settings
from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


MAGIC_LINK_TTL = timedelta(minutes=15)
CLIENT_ACCESS_TOKEN_TTL = timedelta(hours=1)
CLIENT_REFRESH_TOKEN_TTL = timedelta(days=30)


# ==================== Tokens ====================


class ClientTokenData(BaseModel):
    """Decoded payload from a client access token."""
    client_account_id: str
    email: str
    exp: datetime


def _get_jwt_secret() -> str:
    return settings.JWT_SECRET_KEY or settings.APP_SECRET_KEY


def _generate_opaque_token() -> str:
    return secrets.token_urlsafe(48)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_client_access_token(client_account_id: str, email: str) -> str:
    expire = datetime.now(timezone.utc) + CLIENT_ACCESS_TOKEN_TTL
    payload = {
        "sub": client_account_id,
        "email": email,
        "exp": expire,
        "type": "client_access",
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=settings.JWT_ALGORITHM)


def decode_client_access_token(token: str) -> Optional[ClientTokenData]:
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != "client_access":
        return None
    account_id = payload.get("sub")
    email = payload.get("email")
    exp_ts = payload.get("exp")
    if account_id is None or exp_ts is None:
        return None
    return ClientTokenData(
        client_account_id=account_id,
        email=email or "",
        exp=datetime.fromtimestamp(exp_ts, tz=timezone.utc),
    )


# ==================== Service ====================


class ClientMessagingService:
    def __init__(self):
        self.supabase = get_supabase_client().client

    # ---------- Account ----------

    def create_or_get_account(
        self,
        client_id: str,
        email: str,
        display_name: Optional[str] = None,
        locale: str = "ja",
    ) -> dict:
        """Idempotent on email: returns existing account if email is registered."""
        email_norm = email.strip().lower()
        existing = (
            self.supabase.table("client_accounts")
            .select("*")
            .eq("email", email_norm)
            .limit(1)
            .execute()
        )
        if existing.data:
            return existing.data[0]
        result = (
            self.supabase.table("client_accounts")
            .insert(
                {
                    "client_id": client_id,
                    "email": email_norm,
                    "display_name": display_name,
                    "locale": locale,
                }
            )
            .execute()
        )
        return result.data[0] if result.data else None

    def get_account_by_email(self, email: str) -> Optional[dict]:
        result = (
            self.supabase.table("client_accounts")
            .select("*")
            .eq("email", email.strip().lower())
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def get_account(self, account_id: str) -> Optional[dict]:
        result = (
            self.supabase.table("client_accounts")
            .select("*")
            .eq("id", account_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    # ---------- Magic Link ----------

    def issue_magic_link(
        self,
        client_account_id: str,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> str:
        token = _generate_opaque_token()
        expires_at = datetime.now(timezone.utc) + MAGIC_LINK_TTL
        self.supabase.table("client_magic_links").insert(
            {
                "client_account_id": client_account_id,
                "token": token,
                "expires_at": expires_at.isoformat(),
                "request_ip": ip,
                "request_user_agent": user_agent,
            }
        ).execute()
        return token

    def consume_magic_link(self, token: str) -> Optional[dict]:
        """Returns the linked client_account row if the token is valid and unused.
        Marks the token consumed atomically."""
        now = datetime.now(timezone.utc)
        result = (
            self.supabase.table("client_magic_links")
            .select("*")
            .eq("token", token)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        link = result.data[0]
        if link.get("consumed_at"):
            return None
        expires_at = datetime.fromisoformat(link["expires_at"].replace("Z", "+00:00"))
        if expires_at < now:
            return None
        # Mark consumed
        upd = (
            self.supabase.table("client_magic_links")
            .update({"consumed_at": now.isoformat()})
            .eq("id", link["id"])
            .is_("consumed_at", "null")
            .execute()
        )
        if not upd.data:
            # Race: someone else consumed it
            return None
        return self.get_account(link["client_account_id"])

    # ---------- Sessions ----------

    def create_session(
        self,
        client_account_id: str,
        user_agent: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> str:
        """Create a session and return the raw refresh token."""
        refresh_token = _generate_opaque_token()
        token_hash = _hash_token(refresh_token)
        expires_at = datetime.now(timezone.utc) + CLIENT_REFRESH_TOKEN_TTL
        self.supabase.table("client_sessions").insert(
            {
                "client_account_id": client_account_id,
                "refresh_token_hash": token_hash,
                "user_agent": user_agent,
                "ip_address": ip,
                "expires_at": expires_at.isoformat(),
            }
        ).execute()
        self.supabase.table("client_accounts").update(
            {"last_login_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", client_account_id).execute()
        return refresh_token

    def rotate_refresh_token(
        self,
        refresh_token: str,
        user_agent: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> Optional[tuple[str, str]]:
        """Rotate the refresh token: validate, revoke old, create new.
        Returns (new_refresh_token, client_account_id) or None."""
        token_hash = _hash_token(refresh_token)
        now = datetime.now(timezone.utc)
        result = (
            self.supabase.table("client_sessions")
            .select("*")
            .eq("refresh_token_hash", token_hash)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        session = result.data[0]
        if session.get("revoked_at"):
            return None
        expires_at = datetime.fromisoformat(session["expires_at"].replace("Z", "+00:00"))
        if expires_at < now:
            return None
        # Revoke old
        self.supabase.table("client_sessions").update(
            {"revoked_at": now.isoformat()}
        ).eq("id", session["id"]).execute()
        # Create new with updated UA/IP if provided
        new_token = self.create_session(
            session["client_account_id"],
            user_agent=user_agent or session.get("user_agent"),
            ip=ip or session.get("ip_address"),
        )
        return (new_token, session["client_account_id"])

    def revoke_session(self, refresh_token: str) -> bool:
        token_hash = _hash_token(refresh_token)
        result = (
            self.supabase.table("client_sessions")
            .update({"revoked_at": datetime.now(timezone.utc).isoformat()})
            .eq("refresh_token_hash", token_hash)
            .is_("revoked_at", "null")
            .execute()
        )
        return bool(result.data)

    # ---------- Direct Room ----------

    def ensure_direct_room(
        self,
        owner_id: str,
        client_account_id: str,
        title: str,
    ) -> dict:
        """Ensure a direct collab_room exists between owner and client_account.
        Idempotent: unique index uniq_collab_rooms_owner_client_direct enforces
        at most one direct room per (owner, client) pair."""
        existing = (
            self.supabase.table("collab_rooms")
            .select("*")
            .eq("owner_id", owner_id)
            .eq("client_account_id", client_account_id)
            .eq("room_type", "direct")
            .limit(1)
            .execute()
        )
        if existing.data:
            return existing.data[0]
        result = (
            self.supabase.table("collab_rooms")
            .insert(
                {
                    "owner_id": owner_id,
                    "client_account_id": client_account_id,
                    "title": title,
                    "room_type": "direct",
                }
            )
            .execute()
        )
        return result.data[0] if result.data else None

    def get_direct_room_for_client(self, client_account_id: str) -> Optional[dict]:
        result = (
            self.supabase.table("collab_rooms")
            .select("*")
            .eq("client_account_id", client_account_id)
            .eq("room_type", "direct")
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None


# ==================== Email Sending ====================


def send_magic_link_email(
    to_email: str,
    magic_link_url: str,
    display_name: Optional[str] = None,
) -> bool:
    """Send the magic-link email via Gmail API.
    Returns True on success, False on failure (logs error)."""
    try:
        from app.tools.email_tool import get_gmail_service
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        import base64

        service = get_gmail_service()
        greeting = f"{display_name} 様" if display_name else "こんにちは"
        body_text = (
            f"{greeting}\n\n"
            f"ログインリンクをお送りします。下記のURLをクリックしてログインしてください。\n\n"
            f"{magic_link_url}\n\n"
            f"このリンクは15分間のみ有効です。心当たりがない場合はこのメールを無視してください。\n"
        )
        body_html = (
            f"<p>{greeting}</p>"
            f"<p>下記のボタンからログインしてください。</p>"
            f"<p><a href=\"{magic_link_url}\" "
            f"style=\"display:inline-block;padding:12px 24px;"
            f"background:#4f46e5;color:#fff;text-decoration:none;border-radius:8px;\">"
            f"ログイン</a></p>"
            f"<p style=\"color:#666;font-size:12px;\">"
            f"このリンクは15分間のみ有効です。<br/>"
            f"ボタンが押せない場合は次のURLをコピーしてください: <br/>"
            f"<code>{magic_link_url}</code></p>"
        )
        message = MIMEMultipart("alternative")
        message["to"] = to_email
        message["subject"] = "ログインリンクをお送りしました"
        message.attach(MIMEText(body_text, "plain", "utf-8"))
        message.attach(MIMEText(body_html, "html", "utf-8"))
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True
    except Exception as e:
        logger.exception("Failed to send magic link email to %s: %s", to_email, e)
        return False
