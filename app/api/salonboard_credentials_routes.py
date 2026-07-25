"""
salonboard_credentials のAPIエンドポイント。

アプリ自身にログイン機能を持たない設計のため、識別はブラウザが生成する
device_id (UUID) を使う。平文の login_id / password は GET レスポンスに
決して含めない。復号は自動投稿処理 (将来実装) からのみ呼ぶ。
"""
import logging
import os

from fastapi import APIRouter, HTTPException, Query, Request, Response

logger = logging.getLogger(__name__)

from app.models.salonboard_credentials_schemas import (
    SalonboardCredentialsSet,
    SalonboardCredentialsStatus,
)
from app.services.salonboard_credentials_service import (
    SalonboardCredentialsService,
)

router = APIRouter(
    prefix="/salonboard-credentials",
    tags=["salonboard-credentials"],
)

# サーバー発行の長期クッキー。端末側(localStorage)の記憶は iOS Safari が約7日で
# 自動削除するため、それに強い HttpOnly クッキーで device_id を保持し、記憶が
# 消えても同じ端末なら無入力で本人を復元できるようにする（first-party想定）。
COOKIE_NAME = "sb_device_id"
COOKIE_MAX_AGE = 60 * 60 * 24 * 400  # 約400日


def _set_device_cookie(response: Response, device_id: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=device_id,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def _get_service() -> SalonboardCredentialsService:
    return SalonboardCredentialsService()


@router.get("/status", response_model=SalonboardCredentialsStatus)
async def get_status(
    request: Request,
    response: Response,
    device_id: str = Query(..., min_length=8, max_length=128),
):
    """device_id に紐づく設定状態を返す。平文は含まない。
    端末側の記憶が消えていても、長期クッキーの device_id で本人を復元できれば
    無入力で復帰させ、採用すべき device_id をレスポンスで返す。"""
    svc = _get_service()
    status = await svc.get_status(device_id)
    effective_id = device_id if status.get("has_credentials") else None

    if not status.get("has_credentials"):
        cookie_id = request.cookies.get(COOKIE_NAME)
        if cookie_id and cookie_id != device_id and 8 <= len(cookie_id) <= 128:
            recovered = await svc.get_status(cookie_id)
            if recovered.get("has_credentials"):
                status = recovered
                effective_id = cookie_id

    if status.get("has_credentials") and effective_id:
        _set_device_cookie(response, effective_id)  # クッキー延命/再発行
        status["device_id"] = effective_id
    return status


@router.post("", response_model=SalonboardCredentialsStatus)
async def set_credentials(payload: SalonboardCredentialsSet, response: Response):
    """サロンボードのログイン情報を暗号化して保存する。
    同じ device_id があれば上書き。保存時に長期クッキーも発行する。"""
    if not payload.consent:
        raise HTTPException(
            status_code=400, detail="秘密保持と取扱いへの同意が必要です"
        )
    svc = _get_service()
    saved = await svc.save(
        device_id=payload.device_id,
        stylist_name=payload.stylist_name,
        login_id=payload.login_id,
        password=payload.password,
        email=payload.email,
    )
    if not saved:
        raise HTTPException(status_code=500, detail="保存に失敗しました")
    _set_device_cookie(response, payload.device_id)
    status = await svc.get_status(payload.device_id)
    status["device_id"] = payload.device_id
    return status


@router.delete("")
async def delete_credentials(
    device_id: str = Query(..., min_length=8, max_length=128),
):
    """設定を削除する。"""
    svc = _get_service()
    deleted = await svc.delete(device_id)
    return {"deleted": deleted}


# Stripe webhook 署名シークレット(whsec_)の保存先。
# 環境変数が無くても再起動不要で反映できるよう、運営者の認証ストアにも保存する。
_WEBHOOK_OPERATOR_USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"  # 0aw325171@gmail.com
_WEBHOOK_CREDENTIAL_SERVICE = "stripe_styleup_webhook"


async def _get_webhook_secret() -> str:
    """Stripe webhook 署名シークレットを取得する。
    環境変数を優先し、無ければ運営者の認証ストア(暗号化)から読む。"""
    env_secret = os.environ.get("STRIPE_STYLEUP_WEBHOOK_SECRET", "").strip()
    if env_secret:
        return env_secret
    try:
        from app.services.credentials_service import get_credentials_service

        cred = await get_credentials_service().get_credential(
            _WEBHOOK_OPERATOR_USER_ID, _WEBHOOK_CREDENTIAL_SERVICE
        )
        if cred and cred.get("password"):
            return str(cred["password"]).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("failed to load webhook secret from store: %s", e)
    return ""


@router.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    """Stripe の決済完了通知を受け取り、そのメールの利用者を課金済みにする。
    署名シークレット(whsec_)で検証する。秘密鍵(sk)は不要。
    公開URL: <host>/api/v1/salonboard-credentials/stripe-webhook を Stripe の
    Webhook 送信先に設定する。"""
    secret = await _get_webhook_secret()
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    if not secret:
        # 検証できない状態で課金解放するのは危険なので拒否する。
        raise HTTPException(status_code=503, detail="webhook secret 未設定")

    import stripe  # 遅延import（stripe未使用時の起動コスト回避）
    try:
        event = stripe.Webhook.construct_event(payload, sig, secret)
    except Exception as e:  # noqa: BLE001
        logger.warning("stripe webhook signature verification failed: %s", e)
        raise HTTPException(status_code=400, detail="署名検証に失敗しました")

    etype = event.get("type")
    obj = (event.get("data") or {}).get("object") or {}

    # 支払い完了系イベントで、購入者のメールを取り出して課金済みにする。
    if etype in {
        "checkout.session.completed",
        "invoice.paid",
        "invoice.payment_succeeded",
    }:
        email = (
            (obj.get("customer_details") or {}).get("email")
            or obj.get("customer_email")
            or ""
        ).strip()
        if email:
            try:
                n = await _get_service().mark_paid_by_email(email)
                logger.info("stripe webhook %s: marked paid for %s (rows=%s)", etype, email, n)
            except Exception as e:  # noqa: BLE001
                logger.error("mark_paid_by_email failed: %s", e)
        else:
            logger.warning("stripe webhook %s: email not found on event", etype)

    return {"received": True}
