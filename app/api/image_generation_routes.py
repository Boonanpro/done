"""
image_generation の API エンドポイント
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.services.auth_service import TokenData, decode_access_token
from app.services.image_generation_service import ImageGenerationService
from app.models.image_generation_schemas import (
    ImageGenerateRequest,
    ImageEditRequest,
    GeneratedImageResponse,
)

router = APIRouter(prefix="/images", tags=["images"])
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


def get_service() -> ImageGenerationService:
    return ImageGenerationService()


@router.post("/generate", response_model=GeneratedImageResponse)
async def generate_image(
    data: ImageGenerateRequest,
    user: TokenData = Depends(get_current_user),
    service: ImageGenerationService = Depends(get_service),
):
    try:
        return await service.generate(
            prompt=data.prompt,
            user_id=user.user_id,
            project_id=str(data.project_id) if data.project_id else None,
            message_id=str(data.message_id) if data.message_id else None,
            size=data.size,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"画像生成失敗: {e}")


@router.post("/edit", response_model=GeneratedImageResponse)
async def edit_image(
    data: ImageEditRequest,
    user: TokenData = Depends(get_current_user),
    service: ImageGenerationService = Depends(get_service),
):
    try:
        return await service.edit(
            prompt=data.prompt,
            reference_url=data.reference_url,
            user_id=user.user_id,
            project_id=str(data.project_id) if data.project_id else None,
            message_id=str(data.message_id) if data.message_id else None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"画像編集失敗: {e}")


@router.get("", response_model=List[GeneratedImageResponse])
async def list_generated_images(
    project_id: Optional[str] = Query(None),
    user: TokenData = Depends(get_current_user),
    service: ImageGenerationService = Depends(get_service),
):
    return await service.list(user.user_id, project_id=project_id)
