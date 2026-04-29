"""
IMAP Email Sync Routes: Gmail / iCloud などを IMAP で fetch して
dan-notion inbox に投入する。手動トリガー用。後で cron で自動実行する。
"""
from fastapi import APIRouter, Depends
from app.api.chat_routes import get_current_user
from app.services.auth_service import TokenData
from app.services.imap_email_service import fetch_all, fetch_provider, _load_state

router = APIRouter(prefix="/email", tags=["email"])


@router.post("/sync")
async def email_sync(
    provider: str | None = None,
    max_messages: int = 30,
    user: TokenData = Depends(get_current_user),
):
    """
    IMAP で全 provider (Gmail / iCloud) を fetch、または指定 provider のみ。
    新着メールは detected_messages → dan-notion inbox に流入。
    """
    if provider:
        result = [await fetch_provider(user.user_id, provider, max_messages)]
    else:
        result = await fetch_all(user.user_id, max_messages)
    return {"results": result}


@router.get("/sync/state")
async def email_sync_state(user: TokenData = Depends(get_current_user)):
    """provider 別の最終 sync 状態を返す"""
    return _load_state()
