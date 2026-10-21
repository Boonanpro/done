"""保存済みパスワードを本人の画面にだけ出す API（/api/v1/credentials/vault/...）。

ダン（AI）を通さず、本人のブラウザに直接返す。毎回パスキー（PC は Windows の PIN、
スマホは指紋・顔認証）で本人確認してから返す。仕組みは app/services/secret_vault.py。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.chat_routes import get_current_user
from app.services import secret_vault as vault
from app.services.auth_service import TokenData
from app.services.owner import resolve_owner_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/credentials/vault", tags=["secret-vault"])


async def require_owner(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    owner = resolve_owner_user_id()
    if not owner or current_user.user_id != owner:
        raise HTTPException(status_code=403, detail="この画面は本人だけが使えます。")
    return current_user


def _origin(request: Request) -> str:
    return request.headers.get("origin") or ""


def _client_ip(request: Request) -> str:
    return (
        request.headers.get("cf-connecting-ip")
        or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        or (request.client.host if request.client else "")
    )


def _fail(exc: vault.VaultError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.get("/status")
async def status(user: TokenData = Depends(require_owner)) -> dict[str, Any]:
    from app.services.credentials_service import get_credentials_service

    services = await get_credentials_service().list_credentials(user_id=user.user_id)
    until = vault.enroll_open_until()
    return {
        "passkeys": [
            {
                "credential_id": p["credential_id"],
                "label": p.get("label"),
                "rp_id": p.get("rp_id"),
                "created_at": p.get("created_at"),
                "last_used_at": p.get("last_used_at"),
            }
            for p in vault.load_passkeys()
            if p.get("user_id") == user.user_id
        ],
        "enroll_open_until": until.isoformat() if until else None,
        "services": sorted(
            ({"service": s["service"], "updated_at": s.get("updated_at") or s.get("created_at")} for s in services),
            key=lambda s: s["service"].lower(),
        ),
        "recent": vault.recent_events(15),
    }


@router.post("/register/options")
async def register_options(request: Request, user: TokenData = Depends(require_owner)) -> dict[str, Any]:
    try:
        return vault.registration_options(user.user_id, _origin(request), user.email or "owner")
    except vault.VaultError as exc:
        raise _fail(exc) from exc


@router.post("/register/finish")
async def register_finish(body: dict[str, Any], user: TokenData = Depends(require_owner)) -> dict[str, Any]:
    try:
        result = vault.finish_registration(user.user_id, body)
    except vault.VaultError as exc:
        raise _fail(exc) from exc
    await vault.notify_owner(user.user_id, f"パスワード表示用の端末「{result['label']}」を登録しました")
    return {"ok": True, **result}


@router.post("/assert/options")
async def assert_options(body: dict[str, Any], request: Request, user: TokenData = Depends(require_owner)) -> dict[str, Any]:
    purpose = body.get("purpose")
    if purpose not in ("reveal", "enroll", "delete"):
        raise HTTPException(status_code=400, detail="purpose が不正です")
    try:
        return vault.assertion_options(user.user_id, _origin(request), purpose, str(body.get("target") or ""))
    except vault.VaultError as exc:
        raise _fail(exc) from exc


@router.post("/reveal")
async def reveal(body: dict[str, Any], request: Request, user: TokenData = Depends(require_owner)) -> dict[str, Any]:
    from app.services.credentials_service import get_credentials_service

    service = str(body.get("service") or "")
    if not service:
        raise HTTPException(status_code=400, detail="service が必要です")
    try:
        passkey = vault.verify_assertion(user.user_id, body, "reveal", service)
    except vault.VaultError as exc:
        raise _fail(exc) from exc
    creds = await get_credentials_service().get_credential(user.user_id, service)
    if not creds:
        raise HTTPException(status_code=404, detail=f"{service} は保存されていません。")
    vault.log_event("reveal", service=service, device=passkey.get("label"), ip=_client_ip(request))
    await vault.notify_owner(user.user_id, f"{service} のパスワードを「{passkey.get('label')}」で表示しました")
    return {
        "service": service,
        "login_id": creds.get("id") or "",
        "password": creds.get("password") or "",
        "login_url": creds.get("login_url") or "",
    }


@router.post("/enroll")
async def open_enroll(body: dict[str, Any], user: TokenData = Depends(require_owner)) -> dict[str, Any]:
    try:
        passkey = vault.verify_assertion(user.user_id, body, "enroll")
    except vault.VaultError as exc:
        raise _fail(exc) from exc
    until = vault.open_enroll_window(opened_by=f"passkey:{passkey.get('label')}")
    await vault.notify_owner(user.user_id, "パスワード表示用の端末の登録受付を10分間開けました")
    return {"ok": True, "enroll_open_until": until.isoformat()}


@router.post("/passkeys/delete")
async def delete_passkey(body: dict[str, Any], user: TokenData = Depends(require_owner)) -> dict[str, Any]:
    target = str(body.get("target") or "")
    try:
        passkey = vault.verify_assertion(user.user_id, body, "delete", target)
    except vault.VaultError as exc:
        raise _fail(exc) from exc
    removed = vault.delete_passkey(target)
    if not removed:
        raise HTTPException(status_code=404, detail="その端末は登録されていません。")
    vault.log_event("delete", label=removed.get("label"), by=passkey.get("label"))
    await vault.notify_owner(user.user_id, f"パスワード表示用の端末「{removed.get('label')}」を外しました")
    return {"ok": True}
