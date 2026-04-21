"""
chat_artifact のAPIエンドポイント
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.services.auth_service import TokenData, decode_access_token
from app.services.chat_artifact_service import ChatArtifactService
from app.models.chat_artifact_schemas import (
    ChatArtifactCreate,
    ChatArtifactUpdate,
    ChatArtifactResponse,
)

router = APIRouter(prefix="/chat-artifact", tags=["chat_artifact"])
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


def get_service() -> ChatArtifactService:
    return ChatArtifactService()


@router.get("", response_model=List[ChatArtifactResponse])
async def list_chat_artifact(
    project_id: Optional[str] = Query(None),
    user: TokenData = Depends(get_current_user),
    service: ChatArtifactService = Depends(get_service),
):
    return await service.list(user.user_id, project_id=project_id)


@router.post("", response_model=ChatArtifactResponse)
async def create_chat_artifact(
    data: ChatArtifactCreate,
    user: TokenData = Depends(get_current_user),
    service: ChatArtifactService = Depends(get_service),
):
    result = await service.create(data.model_dump(), user.user_id)
    if not result:
        raise HTTPException(status_code=400, detail="作成に失敗しました")
    return result


@router.get("/{artifact_id}", response_model=ChatArtifactResponse)
async def get_chat_artifact(
    artifact_id: str,
    user: TokenData = Depends(get_current_user),
    service: ChatArtifactService = Depends(get_service),
):
    result = await service.get(artifact_id, user.user_id)
    if not result:
        raise HTTPException(status_code=404, detail="見つかりません")
    return result


@router.patch("/{artifact_id}", response_model=ChatArtifactResponse)
async def update_chat_artifact(
    artifact_id: str,
    data: ChatArtifactUpdate,
    user: TokenData = Depends(get_current_user),
    service: ChatArtifactService = Depends(get_service),
):
    result = await service.update(
        artifact_id, data.model_dump(exclude_unset=True), user.user_id
    )
    if not result:
        raise HTTPException(status_code=404, detail="見つかりません")
    return result


@router.delete("/{artifact_id}")
async def delete_chat_artifact(
    artifact_id: str,
    user: TokenData = Depends(get_current_user),
    service: ChatArtifactService = Depends(get_service),
):
    if not await service.delete(artifact_id, user.user_id):
        raise HTTPException(status_code=404, detail="見つかりません")
    return {"ok": True}
