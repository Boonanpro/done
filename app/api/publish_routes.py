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
    DomainCheckCandidate,
    DomainCheckRequest,
    DomainCheckResponse,
    PublishRequest,
    PublishResponse,
    PublishStepDTO,
)
from app.services.auth_service import TokenData, decode_access_token
from app.tools.publish_site.orchestrator import (
    check_domain,
    publish_with_custom_domain,
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
    """公開フロー実行 (購入→Vercel紐付け→DNS→SEO→DB更新)"""
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
