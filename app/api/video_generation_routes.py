"""
video_generation の API エンドポイント
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.services.auth_service import TokenData, decode_access_token
from app.services.video_generation_service import VideoGenerationService
from app.models.video_generation_schemas import (
    VideoGenerateRequest,
    GeneratedVideoResponse,
)

router = APIRouter(prefix="/videos", tags=["videos"])
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


def get_service() -> VideoGenerationService:
    return VideoGenerationService()


@router.post("/generate", response_model=GeneratedVideoResponse)
async def generate_video(
    data: VideoGenerateRequest,
    user: TokenData = Depends(get_current_user),
    service: VideoGenerationService = Depends(get_service),
):
    try:
        return await service.generate(
            prompt=data.prompt,
            user_id=user.user_id,
            project_id=str(data.project_id) if data.project_id else None,
            message_id=str(data.message_id) if data.message_id else None,
            aspect_ratio=data.aspect_ratio,
            reference_image_url=data.reference_image_url,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"動画生成失敗: {e}")


@router.get("", response_model=List[GeneratedVideoResponse])
async def list_generated_videos(
    project_id: Optional[str] = Query(None),
    user: TokenData = Depends(get_current_user),
    service: VideoGenerationService = Depends(get_service),
):
    return await service.list(user.user_id, project_id=project_id)
