"""
公開フロー (Phase 3) のAPIエンドポイント

- POST /publish/check        ドメイン空き確認・価格・サジェスト
- POST /publish/run          実行 (orchestrator)

create_feature の自動生成 CRUD は本機能の構造と合わないため上書き済み。
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.models.publish_schemas import (
    DeliveryUrlRequest,
    DeliveryUrlResponse,
    DnsRecordDTO,
    DomainCheckCandidate,
    DomainCheckRequest,
    DomainCheckResponse,
    DomainSetupCreateRequest,
    DomainSetupResponse,
    PublishRequest,
    PublishResponse,
    PublishStepDTO,
    RegistrarLinkDTO,
)
from app.services.auth_service import TokenData, decode_access_token
from app.services.chat_artifact_service import ChatArtifactService
from app.tools.publish_site.orchestrator import (
    check_domain,
    create_domain_setup,
    get_domain_setup_state,
    issue_dedicated_delivery_url,
    publish_with_custom_domain,
    verify_domain_setup,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/publish", tags=["publish"])
security = HTTPBearer(auto_error=False)
ACCESS_TOKEN_COOKIE = "done_access_token"


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
    result = await publish_with_custom_domain(
        artifact_id=data.artifact_id,
        domain=data.domain,
        vercel_project=data.vercel_project,
        business_info=data.business_info,  # type: ignore[arg-type]
        contact=data.contact,  # type: ignore[arg-type]
        years=data.years,
        auto_renew=data.auto_renew,
        artifact_dir=data.artifact_dir,
        write_seo_files=data.write_seo_files,
        dry_run=data.dry_run,
        user_id=user.user_id,
    )
    return PublishResponse(
        success=result.success,
        artifact_id=result.artifact_id,
        domain=result.domain,
        deploy_url=result.deploy_url,
        steps=[PublishStepDTO(**s.__dict__) for s in result.steps],
        error=result.error,
        pricing=result.pricing,
    )


@router.post("/delivery-url", response_model=DeliveryUrlResponse)
async def delivery_url(
    data: DeliveryUrlRequest,
    user: TokenData = Depends(get_current_user),
):
    """Issue a dedicated vercel.app delivery URL for a tool/dashboard artifact."""
    try:
        result = await issue_dedicated_delivery_url(
            artifact_id=data.artifact_id,
            slug=data.slug,
            vercel_project=data.vercel_project,
            user_id=user.user_id,
        )
        return DeliveryUrlResponse(
            success=True,
            artifact_id=data.artifact_id,
            url=result["url"],
            alias=result["alias"],
        )
    except Exception as e:
        logger.exception("issue_dedicated_delivery_url failed")
        return DeliveryUrlResponse(success=False, artifact_id=data.artifact_id, error=str(e))


# ============================================
# クライアント所有ドメインの案内フロー
# ============================================
#
# /domain-setup        : オーナーが案内URLを発行 (要認証)
# /domain-setup/{token}: クライアントが状態取得 (公開・認証なし)
# .../{token}/verify   : クライアントが DNS 設定後に接続確認 (公開・認証なし)


def _setup_to_response(
    *,
    success: bool,
    token: Optional[str] = None,
    artifact_id: Optional[str] = None,
    artifact_label: Optional[str] = None,
    setup: Optional[dict] = None,
    production_url: Optional[str] = None,
    verified: bool = False,
    detail: Optional[str] = None,
    error: Optional[str] = None,
) -> DomainSetupResponse:
    """orchestrator の setup dict を API レスポンスに変換する。"""
    setup = setup or {}
    return DomainSetupResponse(
        success=success,
        token=token,
        setup_path=f"/domain-setup/{token}" if token else None,
        artifact_id=artifact_id,
        artifact_label=artifact_label,
        domain=setup.get("domain"),
        status=setup.get("status"),
        availability=setup.get("availability"),
        registrar_links=[RegistrarLinkDTO(**r) for r in setup.get("registrar_links", [])],
        dns_records=[DnsRecordDTO(**r) for r in setup.get("dns_records", [])],
        production_url=production_url,
        verified=verified,
        detail=detail,
        error=error,
    )


@router.post("/domain-setup", response_model=DomainSetupResponse)
async def domain_setup_create(
    data: DomainSetupCreateRequest,
    user: TokenData = Depends(get_current_user),
):
    """クライアント向けドメイン設定の案内URLを発行する (オーナー操作)。"""
    try:
        result = await create_domain_setup(
            artifact_id=data.artifact_id,
            domain=data.domain,
            vercel_project=data.vercel_project,
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
    )


@router.get("/domain-setup/{token}", response_model=DomainSetupResponse)
async def domain_setup_get(token: str):
    """クライアント案内ページの状態を取得する (公開・認証なし)。"""
    state = await get_domain_setup_state(token)
    if state is None:
        return DomainSetupResponse(success=False, error="案内ページが見つかりません")
    setup = state["setup"]
    return _setup_to_response(
        success=True,
        token=token,
        artifact_id=state["artifact_id"],
        artifact_label=state["artifact_label"],
        setup=setup,
        production_url=state.get("production_url"),
        verified=(setup.get("status") == "live"),
        detail=setup.get("last_error"),
    )


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


@router.post("/domain-setup/{token}/verify", response_model=DomainSetupResponse)
async def domain_setup_verify(token: str):
    """クライアントが DNS 設定後に押す接続確認 (公開・認証なし)。"""
    try:
        result = await verify_domain_setup(token)
    except Exception as e:
        logger.exception("verify_domain_setup failed")
        return DomainSetupResponse(success=False, token=token, error=str(e))
    if not result.get("found"):
        return DomainSetupResponse(
            success=False, token=token, error=result.get("detail", "見つかりません")
        )
    return _setup_to_response(
        success=True,
        token=token,
        setup=result.get("setup"),
        production_url=result.get("production_url"),
        verified=result.get("verified", False),
        detail=result.get("detail"),
    )
