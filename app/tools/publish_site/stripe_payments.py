"""
Stripe 決済 — クライアントのドメイン代を案内ページ上でカード決済する。

## マルチテナント方針

Search Console と同様、運営者が 1 つの Stripe アカウントを登録すれば全テナントで
使える。credentials DB の運営者アカウント (OPERATOR_USER_ID) 配下、
service="stripe" の password フィールドに ``{"secret_key": "sk_..."}`` を
JSON 文字列で保存する（素のキー文字列も可）。未登録時は関数が「未設定」を
返し、フロー自体は止めない。

Webhook は使わない。決済完了後の success_url 復帰時に ``retrieve_session`` で
サーバ側から Stripe にセッションを照会し、支払い済みであることを検証する
（自宅PCの trycloudflare トンネルURLが不安定で、固定 Webhook URL を持てないため）。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from app.services.credentials_service import get_credentials_service

logger = logging.getLogger(__name__)

OPERATOR_USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"  # 0aw325171@gmail.com
CREDENTIAL_SERVICE = "stripe"


class StripeError(RuntimeError):
    """Stripe 関連のエラー"""


async def get_secret_key() -> Optional[str]:
    """運営者の Stripe シークレットキーを取得する。未登録なら None。"""
    cred = await get_credentials_service().get_credential(
        OPERATOR_USER_ID, CREDENTIAL_SERVICE
    )
    if not cred or not cred.get("password"):
        return None
    raw = cred["password"]
    # JSON 形式 {"secret_key": "..."} と素のキー文字列の両対応
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            key = parsed.get("secret_key") or parsed.get("password")
            if key:
                return str(key)
    except (json.JSONDecodeError, TypeError):
        pass
    return raw if isinstance(raw, str) and raw.startswith("sk_") else None


async def is_configured() -> bool:
    """Stripe シークレットキーが登録済みか。"""
    return (await get_secret_key()) is not None


def _stripe(secret_key: str):
    try:
        import stripe
    except ImportError as e:  # pragma: no cover
        raise StripeError(
            f"stripe ライブラリが見つかりません ({e})。requirements.txt を確認してください。"
        )
    stripe.api_key = secret_key
    return stripe


async def create_checkout_session(
    *,
    amount_cents: int,
    currency: str,
    product_name: str,
    success_url: str,
    cancel_url: str,
    metadata: dict[str, str],
) -> str:
    """Checkout Session を作成し、決済ページの URL を返す。"""
    secret_key = await get_secret_key()
    if not secret_key:
        raise StripeError("Stripe のシークレットキーが未設定です")

    def _work() -> str:
        stripe = _stripe(secret_key)
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": currency,
                        "product_data": {"name": product_name},
                        "unit_amount": amount_cents,
                    },
                    "quantity": 1,
                }
            ],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata,
        )
        url = session.get("url")
        if not url:
            raise StripeError("Checkout Session に URL がありません")
        return url

    return await asyncio.to_thread(_work)


async def retrieve_session(session_id: str) -> dict[str, Any]:
    """Checkout Session を Stripe から照会する（支払い検証用）。

    Returns:
        ``{"paid": bool, "metadata": {...}, "amount_total": int|None, "currency": str|None}``
    """
    secret_key = await get_secret_key()
    if not secret_key:
        raise StripeError("Stripe のシークレットキーが未設定です")

    def _work() -> dict[str, Any]:
        stripe = _stripe(secret_key)
        s = stripe.checkout.Session.retrieve(session_id)
        return {
            "paid": s.get("payment_status") == "paid",
            "metadata": dict(s.get("metadata") or {}),
            "amount_total": s.get("amount_total"),
            "currency": s.get("currency"),
        }

    return await asyncio.to_thread(_work)
