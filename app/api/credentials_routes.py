"""
Credentials API Routes for Phase 3B: Execution Engine
認証情報の保存・取得・削除API
"""
from fastapi import APIRouter, Depends, HTTPException

from app.models.schemas import (
    CredentialRequest,
    CredentialResponse,
    CredentialListResponse,
    CredentialListItem,
)
from app.services.credentials_service import get_credentials_service
from app.api.secret_vault_routes import require_owner
from app.services.auth_service import TokenData

router = APIRouter()

# 2026-10-21 まで認証なしで外から呼べた（user_id をクエリで渡せば本人の保管庫を
# 一覧・上書き・削除できた）。本人のログインだけを通し、本人の user_id で扱う。


@router.post("/credentials", response_model=CredentialResponse)
async def save_credentials(request: CredentialRequest, user: TokenData = Depends(require_owner)):
    """
    認証情報を暗号化して保存
    
    Request:
    ```json
    {
      "service": "ex_reservation",
      "credentials": {
        "email": "user@example.com",
        "password": "secret123"
      }
    }
    ```
    
    Response:
    ```json
    {
      "success": true,
      "service": "ex_reservation",
      "message": "認証情報を保存しました"
    }
    ```
    """
    try:
        uid = user.user_id
        service = get_credentials_service()
        result = await service.save_credential(
            user_id=uid,
            service=request.service,
            credentials=request.credentials,
        )
        return CredentialResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/credentials", response_model=CredentialListResponse)
async def list_credentials(user: TokenData = Depends(require_owner)):
    """
    保存済みサービス一覧を取得
    
    Response:
    ```json
    {
      "services": [
        {
          "service": "ex_reservation",
          "created_at": "2024-12-21T10:00:00Z",
          "updated_at": "2024-12-21T10:00:00Z"
        },
        {
          "service": "amazon",
          "created_at": "2024-12-20T09:00:00Z",
          "updated_at": null
        }
      ]
    }
    ```
    """
    try:
        uid = user.user_id
        service = get_credentials_service()
        credentials = await service.list_credentials(user_id=uid)
        
        items = [
            CredentialListItem(
                service=c["service"],
                created_at=c["created_at"],
                updated_at=c.get("updated_at"),
            )
            for c in credentials
        ]
        
        return CredentialListResponse(services=items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/credentials/{service}", response_model=CredentialResponse)
async def delete_credentials(service: str, user: TokenData = Depends(require_owner)):
    """
    認証情報を削除
    
    Response:
    ```json
    {
      "success": true,
      "service": "ex_reservation",
      "message": "認証情報を削除しました"
    }
    ```
    """
    try:
        uid = user.user_id
        cred_service = get_credentials_service()
        result = await cred_service.delete_credential(user_id=uid, service=service)
        
        if not result["success"]:
            raise HTTPException(status_code=404, detail=result["message"])
        
        return CredentialResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
