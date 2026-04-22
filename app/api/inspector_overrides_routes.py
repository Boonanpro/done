"""
inspector_overrides の API エンドポイント
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.services.auth_service import TokenData, decode_access_token
from app.services.inspector_overrides_service import InspectorOverridesService
from app.models.inspector_overrides_schemas import (
    OverrideUpsert,
    OverrideResponse,
)

router = APIRouter(prefix="/inspector-overrides", tags=["inspector-overrides"])
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


def get_service() -> InspectorOverridesService:
    return InspectorOverridesService()


@router.post("", response_model=OverrideResponse)
async def upsert_override(
    data: OverrideUpsert,
    user: TokenData = Depends(get_current_user),
    service: InspectorOverridesService = Depends(get_service),
):
    result = await service.upsert(
        artifact_slug=data.artifact_slug,
        element_key=data.element_key,
        styles=data.styles,
        attrs=data.attrs,
        user_id=user.user_id,
        project_id=str(data.project_id) if data.project_id else None,
    )
    return result


@router.get("", response_model=List[OverrideResponse])
async def list_overrides(
    slug: str = Query(..., min_length=1),
    user: TokenData = Depends(get_current_user),
    service: InspectorOverridesService = Depends(get_service),
):
    return await service.list_by_slug(slug, user.user_id)


@router.delete("")
async def clear_overrides(
    slug: str = Query(..., min_length=1),
    element_key: Optional[str] = Query(None),
    user: TokenData = Depends(get_current_user),
    service: InspectorOverridesService = Depends(get_service),
):
    if element_key:
        ok = await service.delete_one(slug, element_key, user.user_id)
        return {"deleted": 1 if ok else 0}
    count = await service.delete_by_slug(slug, user.user_id)
    return {"deleted": count}
