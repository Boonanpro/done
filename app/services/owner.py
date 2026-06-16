"""オーナー(運用者本人)の user_id を解決する。

フォーム着信やメール常駐ポーラーなど「ログインユーザーが居ない文脈」で、
提案(dan_proposals)や検知メッセージの宛先となる owner の user_id が必要になる。
本システムは実質シングルオーナーなので、email から1件引いてキャッシュする。

優先順位:
1. 環境変数 DAN_OWNER_USER_ID（UUID を直接指定）
2. 環境変数 DAN_OWNER_EMAIL（既定: 0aw325171@gmail.com）から users を引く
"""
import logging
import os
from typing import Optional

from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

DEFAULT_OWNER_EMAIL = "0aw325171@gmail.com"

_cached_owner_id: Optional[str] = None


def resolve_owner_user_id() -> Optional[str]:
    """オーナーの user_id を返す。解決できなければ None。"""
    global _cached_owner_id
    if _cached_owner_id:
        return _cached_owner_id

    explicit = os.getenv("DAN_OWNER_USER_ID")
    if explicit:
        _cached_owner_id = explicit.strip()
        return _cached_owner_id

    email = os.getenv("DAN_OWNER_EMAIL", DEFAULT_OWNER_EMAIL).strip()
    try:
        sb = get_supabase_client().client
        res = sb.table("users").select("id").eq("email", email).limit(1).execute()
        if res.data:
            _cached_owner_id = res.data[0]["id"]
            return _cached_owner_id
        logger.warning("resolve_owner_user_id: email=%s のユーザーが見つかりません", email)
    except Exception as e:  # noqa: BLE001
        logger.warning("resolve_owner_user_id failed: %s", e)
    return None
