from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.services.auth_service import TokenData, decode_access_token
from app.services.contacts_service import ContactsService
from app.models.contacts_schemas import ContactCreate, ContactUpdate, ContactResponse

router = APIRouter(prefix="/contacts", tags=["contacts"])
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


def get_service():
    return ContactsService()


@router.get("", response_model=List[ContactResponse])
async def list_contacts(
    user: TokenData = Depends(get_current_user),
    service: ContactsService = Depends(get_service),
):
    return await service.list(user.user_id)


@router.post("", response_model=ContactResponse)
async def create_contact(
    data: ContactCreate,
    user: TokenData = Depends(get_current_user),
    service: ContactsService = Depends(get_service),
):
    result = await service.create(data.model_dump(), user.user_id)
    if not result:
        raise HTTPException(status_code=400, detail="作成に失敗しました")
    return result


@router.get("/{id}", response_model=ContactResponse)
async def get_contact(
    id: str,
    user: TokenData = Depends(get_current_user),
    service: ContactsService = Depends(get_service),
):
    result = await service.get(id, user.user_id)
    if not result:
        raise HTTPException(status_code=404, detail="見つかりません")
    return result


@router.patch("/{id}", response_model=ContactResponse)
async def update_contact(
    id: str,
    data: ContactUpdate,
    user: TokenData = Depends(get_current_user),
    service: ContactsService = Depends(get_service),
):
    result = await service.update(id, data.model_dump(exclude_unset=True), user.user_id)
    if not result:
        raise HTTPException(status_code=404, detail="見つかりません")
    return result


@router.delete("/{id}")
async def delete_contact(
    id: str,
    user: TokenData = Depends(get_current_user),
    service: ContactsService = Depends(get_service),
):
    if not await service.delete(id, user.user_id):
        raise HTTPException(status_code=404, detail="見つかりません")
    return {"ok": True}
