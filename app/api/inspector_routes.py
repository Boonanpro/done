"""
inspector の API エンドポイント
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.services.auth_service import TokenData, decode_access_token
from app.services import inspector_service
from app.models.inspector_schemas import (
    InspectorApplyRequest,
    InspectorApplyResponse,
)

router = APIRouter(prefix="/inspector", tags=["inspector"])
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


@router.post("/apply", response_model=InspectorApplyResponse)
async def apply_edit(
    data: InspectorApplyRequest,
    _user: TokenData = Depends(get_current_user),
):
    try:
        result = inspector_service.apply_edit(
            file_path=data.file_path,
            line_number=data.line_number,
            column_number=data.column_number,
            styles=data.styles,
            attrs=data.attrs,
        )
        return InspectorApplyResponse(**result)
    except (PermissionError, FileNotFoundError, ValueError) as e:
        return InspectorApplyResponse(
            success=False,
            file_path=data.file_path,
            line_number=data.line_number,
            error=str(e),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"適用失敗: {e}")
