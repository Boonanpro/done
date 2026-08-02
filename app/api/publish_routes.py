"""
公開フロー (Phase 3) のAPIエンドポイント

- POST /publish/check        ドメイン空き確認・価格・サジェスト
- POST /publish/run          実行 (orchestrator)

create_feature の自動生成 CRUD は本機能の構造と合わないため上書き済み。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.models.publish_schemas import (
    ConnectDomainRequest,
    DomainCheckCandidate,
    DomainCheckRequest,
    DomainCheckResponse,
    DomainCheckoutRequest,
    DomainCheckoutResponse,
    DomainRegistrantRequest,
    DomainSetupCreateRequest,
    DomainSetupResponse,
    PaymentConfirmRequest,
    PublishRequest,
    PublishResponse,
    PublishStepDTO,
)
from app.services.auth_service import TokenData, decode_access_token
from app.services.chat_artifact_service import ChatArtifactService
from app.services.artifact_publication_service import ArtifactPublicationService
from app.config import settings
from app.tools.publish_site.orchestrator import (
    check_domain,
    confirm_domain_payment,
    connect_existing_domain,
    create_domain_checkout,
    create_domain_setup,
    create_owner_domain_registration,
    get_domain_setup_state,
    run_domain_registration,
    run_paid_registration,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/publish", tags=["publish"])
security = HTTPBearer(auto_error=False)
ACCESS_TOKEN_COOKIE = "done_access_token"


async def _delivery_project_for_artifact(artifact_id: str, user_id: str) -> str:
    """Authorize the artifact and resolve its delivery target server-side."""
    artifact = await ChatArtifactService().get(artifact_id, user_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    publications = ArtifactPublicationService()
    release = publications.latest(artifact_id)
    if release and release.get("deployment_project"):
        return str(release["deployment_project"])
    # A domain-publication request is the explicit opt-in to dedicated delivery.
    # Merely creating an artifact never creates a Vercel project or a billable
    # external resource.
    release = await publications.provision_dedicated_project(artifact, user_id=user_id)
    project = (release.get("deployment_project") or "").strip()
    if not project:
        raise HTTPException(status_code=500, detail="Dedicated delivery project was not created")
    return project


async def _deploy_dedicated_artifact(artifact_id: str, user_id: str) -> dict:
    artifact = await ChatArtifactService().get(artifact_id, user_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return await ArtifactPublicationService().deploy_dedicated_release(artifact, user_id=user_id)


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


@router.post("/check", response_model=DomainCheckResponse)
async def check(
    data: DomainCheckRequest,
    user: TokenData = Depends(get_current_user),
):
    """ドメイン空き確認・価格・サジェスト"""
    try:
        res = await check_domain(data.query, include_suggestions=data.include_suggestions)
    except Exception as e:
        logger.exception("check_domain failed")
        raise HTTPException(status_code=502, detail=str(e))

    exact_dto = DomainCheckCandidate(**res["exact"]) if res.get("exact") else None
    suggestions = [DomainCheckCandidate(**s) for s in res.get("suggestions", [])]
    return DomainCheckResponse(exact=exact_dto, suggestions=suggestions)


@router.post("/run", response_model=PublishResponse)
async def run(
    data: PublishRequest,
    user: TokenData = Depends(get_current_user),
):
    """公開フロー実行 (オーナーが取得・支払い: 購入→Vercel紐付け→DNS→SEO→Search Console→DB更新)。

    クライアントが自分でドメインを用意する場合は ``/publish/domain-setup`` を使う。
    """
    try:
        vercel_project = await _delivery_project_for_artifact(data.artifact_id, user.user_id)
        queued = await create_owner_domain_registration(
            artifact_id=data.artifact_id,
            domain=data.domain,
            vercel_project=vercel_project,
            user_id=user.user_id,
            years=data.years,
            auto_renew=data.auto_renew,
            artifact_dir=data.artifact_dir,
            write_seo_files=data.write_seo_files,
            dry_run=data.dry_run,
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("owner domain registration could not be started")
        return PublishResponse(
            success=False, artifact_id=data.artifact_id, domain=data.domain,
            error=str(e), status="failed",
        )
    if queued["start"]:
        asyncio.create_task(run_domain_registration(queued["token"]))
    return PublishResponse(
        success=True,
        artifact_id=data.artifact_id,
        domain=queued["setup"]["domain"],
        steps=[PublishStepDTO(name="start", status="running", detail="Publication continues even if this window is closed.")],
        status=queued["setup"].get("status", "registering"),
    )


@router.post("/connect", response_model=PublishResponse)
async def connect(
    data: ConnectDomainRequest,
    user: TokenData = Depends(get_current_user),
):
    """既に所有しているドメインを接続して公開する（購入なし）。

    Vercel紐付け→DNSをVercelへ向ける（Name.com/Cloudflareは自動・外部は手動レコード案内）
    →成果物にマッピング→反映確認。
    """
    vercel_project = await _delivery_project_for_artifact(data.artifact_id, user.user_id)
    await _deploy_dedicated_artifact(data.artifact_id, user.user_id)
    result = await connect_existing_domain(
        artifact_id=data.artifact_id,
        domain=data.domain,
        vercel_project=vercel_project,
        user_id=user.user_id,
        replace=data.replace,
    )
    return PublishResponse(
        success=result.success,
        artifact_id=result.artifact_id,
        domain=result.domain,
        deploy_url=result.deploy_url,
        steps=[PublishStepDTO(**s.__dict__) for s in result.steps],
        error=result.error,
        pricing=result.pricing,
        dns_instructions=result.dns_instructions,
        conflict_label=result.conflict_label,
        verified=result.verified,
    )


# 旧 /delivery-url エンドポイント（<slug>-done.vercel.app の専用 alias 発行）は
# 廃止。納品 URL は常に <host>/preview/<slug> に統一。独自ドメインを取って公開
# した時のみ custom_domain ベースの production_url が増える。
# 詳細: docs/architecture/artifact_urls.md を参照。


# ============================================
# クライアント向けドメイン取得の案内フロー（Stripe 決済）
# ============================================
#
# /domain-setup            : オーナーが案内URLを発行 (要認証)
# /domain-setup/{token}    : クライアントが状態取得 (公開・認証なし)
# .../{token}/checkout     : クライアントが決済ページへ進む (公開・認証なし)
# .../{token}/confirm      : 決済完了 → ドメイン取得・公開を開始 (公開・認証なし)
# /custom-domains          : middleware 用のドメイン→artifact マップ (公開・認証なし)


def _setup_to_response(
    *,
    success: bool,
    token: Optional[str] = None,
    artifact_id: Optional[str] = None,
    artifact_label: Optional[str] = None,
    setup: Optional[dict] = None,
    price: Optional[str] = None,
    production_url: Optional[str] = None,
    detail: Optional[str] = None,
    error: Optional[str] = None,
) -> DomainSetupResponse:
    """orchestrator の setup dict を API レスポンスに変換する。"""
    setup = setup or {}
    return DomainSetupResponse(
        success=success,
        token=token,
        setup_path=f"/domain-setup/{token}" if token else None,
        setup_url=(f"{settings.PUBLIC_APP_URL.rstrip('/')}/domain-setup/{token}" if token else None),
        artifact_id=artifact_id,
        artifact_label=artifact_label,
        domain=setup.get("domain"),
        status=setup.get("status"),
        price=price,
        test_mode=bool(setup.get("dry_run")),
        production_url=production_url,
        detail=detail or setup.get("last_error"),
        error=error,
        registrant_saved=bool(setup.get("registrant_saved")),
    )


@router.post("/domain-setup", response_model=DomainSetupResponse)
async def domain_setup_create(
    data: DomainSetupCreateRequest,
    user: TokenData = Depends(get_current_user),
):
    """クライアント向けドメイン取得の案内URLを発行する (オーナー操作)。"""
    try:
        vercel_project = await _delivery_project_for_artifact(data.artifact_id, user.user_id)
        result = await create_domain_setup(
            artifact_id=data.artifact_id,
            domain=data.domain,
            vercel_project=vercel_project,
            user_id=user.user_id,
        )
    except Exception as e:
        logger.exception("create_domain_setup failed")
        return DomainSetupResponse(success=False, error=str(e))
    return _setup_to_response(
        success=True,
        token=result["token"],
        artifact_id=data.artifact_id,
        artifact_label=result["artifact_label"],
        setup=result["setup"],
        price=result.get("price"),
    )


@router.get("/domain-setup/{token}", response_model=DomainSetupResponse)
async def domain_setup_get(token: str):
    """クライアント案内ページの状態を取得する (公開・認証なし)。"""
    state = await get_domain_setup_state(token)
    if state is None:
        return DomainSetupResponse(success=False, error="案内ページが見つかりません")
    return _setup_to_response(
        success=True,
        token=token,
        artifact_id=state["artifact_id"],
        artifact_label=state["artifact_label"],
        setup=state["setup"],
        price=state.get("price"),
        production_url=state.get("production_url"),
    )


@router.post("/domain-setup/{token}/checkout", response_model=DomainCheckoutResponse)
async def domain_setup_checkout(token: str, data: DomainCheckoutRequest):
    """クライアントが決済ページ (Stripe Checkout) へ進む (公開・認証なし)。"""
    try:
        result = await create_domain_checkout(token, return_origin=data.return_origin)
    except Exception as e:
        logger.exception("create_domain_checkout failed")
        return DomainCheckoutResponse(success=False, error=str(e))
    return DomainCheckoutResponse(
        success=result.get("success", False),
        checkout_url=result.get("checkout_url"),
        error=result.get("error"),
    )


@router.post("/domain-setup/{token}/registrant")
async def domain_setup_registrant(token: str, data: DomainRegistrantRequest):
    state = await get_domain_setup_state(token)
    if state is None:
        raise HTTPException(status_code=404, detail="Domain setup not found")
    setup = state["setup"]
    if setup.get("status") != "pending" or setup.get("registrant_mode") not in (None, "client"):
        raise HTTPException(status_code=409, detail="This invitation cannot accept registrant information")
    contact = {"email": data.email.strip(), "phone": data.phone.strip(), "postal_info": {"name": data.name.strip(), "organization": data.organization.strip(), "address": {"street": data.street.strip(), "city": data.city.strip(), "state": data.state.strip(), "postal_code": data.postal_code.strip(), "country_code": data.country_code.strip().upper()}}}
    from app.services.domain_registrant_profile_service import get_domain_registrant_profile_service
    await get_domain_registrant_profile_service().save_for_setup(token, contact)
    setup["registrant_mode"] = "client"
    setup["registrant_saved"] = True
    svc = ChatArtifactService()
    svc.supabase.table(svc.table).update({"domain_setup": setup}).eq("id", state["artifact_id"]).execute()
    return {"success": True}


@router.post("/domain-setup/{token}/confirm", response_model=DomainSetupResponse)
async def domain_setup_confirm(token: str, data: PaymentConfirmRequest):
    """決済完了の確認 → ドメイン取得・公開を開始する (公開・認証なし)。"""
    try:
        res = await confirm_domain_payment(token, data.session_id)
    except Exception as e:
        logger.exception("confirm_domain_payment failed")
        return DomainSetupResponse(success=False, token=token, error=str(e))

    if res.get("start"):
        # 取得〜公開は数分かかるためバックグラウンド実行。ページはポーリングで追う。
        asyncio.create_task(run_paid_registration(token))

    state = await get_domain_setup_state(token)
    if state is None:
        return DomainSetupResponse(
            success=res.get("success", False), token=token, error=res.get("error")
        )
    return _setup_to_response(
        success=res.get("success", False),
        token=token,
        artifact_id=state["artifact_id"],
        artifact_label=state["artifact_label"],
        setup=state["setup"],
        price=state.get("price"),
        production_url=state.get("production_url"),
        detail=res.get("error"),
        error=None if res.get("success") else res.get("error"),
    )


@router.post("/domain-setup/stripe-webhook")
async def domain_setup_stripe_webhook(request: Request):
    """Start registration from Stripe's signed payment event.

    The browser return is retained for immediate feedback, while this endpoint
    ensures a completed payment is still processed when the payer closes the
    Checkout tab before returning to the invitation page.
    """
    from app.tools.publish_site.stripe_payments import StripeError, verify_webhook

    try:
        event = await verify_webhook(
            await request.body(), request.headers.get("stripe-signature", "")
        )
    except StripeError as e:
        logger.error("domain Stripe webhook unavailable: %s", e)
        raise HTTPException(status_code=503, detail="domain payment webhook is not configured")
    except Exception as e:  # noqa: BLE001
        logger.warning("invalid domain Stripe webhook: %s", e)
        raise HTTPException(status_code=400, detail="invalid Stripe signature")

    if event.get("type") != "checkout.session.completed":
        return {"received": True, "started": False}

    session = ((event.get("data") or {}).get("object") or {})
    token = str(((session.get("metadata") or {}).get("token") or "")).strip()
    session_id = str(session.get("id") or "").strip()
    if not token or not session_id:
        logger.warning("domain Stripe event missing token or session id")
        return {"received": True, "started": False}

    result = await confirm_domain_payment(token, session_id)
    if not result.get("success"):
        # A stale or malformed event should be acknowledged so Stripe does not
        # retry it indefinitely; the application log retains the reason.
        logger.error("domain payment confirmation failed for %s: %s", token, result.get("error"))
        return {"received": True, "started": False}
    if result.get("start"):
        asyncio.create_task(run_paid_registration(token))
    return {"received": True, "started": bool(result.get("start"))}


@router.get("/custom-domains")
async def custom_domains_map():
    """カスタムドメイン → artifact slug のマップ (middleware 用・公開・認証なし)。

    middleware がこれを TTL 付きで取得し、接続済みの独自ドメインを
    正しい artifact にルーティングする。
    """
    try:
        mapping = await ChatArtifactService().list_custom_domain_map()
    except Exception as e:  # noqa: BLE001
        logger.warning("custom-domains map failed: %s", e)
        mapping = {}
    return {"map": mapping}


@router.get("/search-performance")
async def search_performance(
    domain: str,
    days: int = 28,
    user: TokenData = Depends(get_current_user),
):
    """独自ドメイン(domain) の検索パフォーマンスを Search Console から引き戻す。

    どの検索語で表示/クリックされているか（impressions/clicks/CTR/掲載順位）を返す。
    集客改善ループの土台。運営者の検索データが含まれるため認証必須。
    """
    from app.tools.publish_site.search_console import fetch_search_performance

    try:
        return await fetch_search_performance(domain, days=days)
    except Exception as e:  # noqa: BLE001
        logger.exception("search_performance failed")
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/status/{artifact_id}")
async def publication_status(
    artifact_id: str,
    user: TokenData = Depends(get_current_user),
):
    """Return one reconciled publication fact record for an artifact."""
    from app.services.publication_status_service import get_publication_status_service

    try:
        return await get_publication_status_service().reconcile(artifact_id, user_id=user.user_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("publication state reconciliation failed")
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/analytics-stats")
async def analytics_stats(
    domain: str,
    days: int = 28,
    user: TokenData = Depends(get_current_user),
):
    """独自ドメイン(domain) の訪問数を Umami から引き戻す（認証必須）。

    pageviews/visitors/visits/bounce_rate を返す。Search Console の検索データと並ぶ
    集客改善ループの土台で、将来のクライアント別ダッシュボードにも使う。
    """
    from app.services.umami_service import fetch_stats

    try:
        return await fetch_stats(domain, days=days)
    except Exception as e:  # noqa: BLE001
        logger.exception("analytics_stats failed")
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/analytics-tag")
async def analytics_tag(host: str = ""):
    """独自ドメイン(host) の Umami 計測タグ情報 {website_id, src} を返す（公開・認証なし）。

    成果物共通レイアウトが計測スクリプトを差し込むために使う。未登録なら meta=null。
    website_id はページに埋め込まれる公開値なので認証不要。
    """
    try:
        from app.services.umami_service import tracking_for_host

        tag = await tracking_for_host(host)
    except Exception as e:  # noqa: BLE001
        logger.warning("analytics-tag failed: %s", e)
        tag = None
    return {"tag": tag}


@router.get("/site-meta")
async def site_meta(host: str = ""):
    """独自ドメイン(host) のSEO用メタ {slug,name,type,url} を返す（公開・認証なし）。

    成果物共通レイアウトが JSON-LD 構造化データを自動生成するために使う。
    """
    try:
        meta = await ChatArtifactService().get_site_meta_by_host(host)
    except Exception as e:  # noqa: BLE001
        logger.warning("site-meta failed: %s", e)
        meta = None
    return {"meta": meta}
