"""
AIX事業ダッシュボードのAPIエンドポイント。
- /api/v1/aix/snapshot              全テーブル一括取得
- /api/v1/aix/clients               クライアントCRUD
- /api/v1/aix/{kind}                子テーブル CRUD (hypotheses / proposals / activities / contracts / engagements / tasks)

すべて認証必須・本人スコープ。
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.services.auth_service import TokenData, decode_access_token
from app.services.aix_dashboard_service import AixDashboardService, TABLES
from app.services.aix_client_chat_service import AixClientChatService

router = APIRouter(prefix="/aix", tags=["aix-dashboard"])
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


def get_service() -> AixDashboardService:
    return AixDashboardService()


def get_chat_service() -> AixClientChatService:
    return AixClientChatService()


CHILD_KINDS = {k for k in TABLES if k != "clients"}


@router.get("/snapshot")
async def snapshot(
    user: TokenData = Depends(get_current_user),
    svc: AixDashboardService = Depends(get_service),
) -> Dict[str, List[Dict[str, Any]]]:
    return await svc.snapshot(user.user_id)


# ── clients ──
@router.get("/clients")
async def list_clients(
    user: TokenData = Depends(get_current_user),
    svc: AixDashboardService = Depends(get_service),
) -> List[Dict[str, Any]]:
    return await svc.list_clients(user.user_id)


@router.post("/clients")
async def create_client(
    payload: Dict[str, Any],
    user: TokenData = Depends(get_current_user),
    svc: AixDashboardService = Depends(get_service),
) -> Dict[str, Any]:
    if not payload.get("name"):
        raise HTTPException(status_code=400, detail="name is required")
    return await svc.create_client(user.user_id, payload)


@router.patch("/clients/{client_id}")
async def update_client(
    client_id: str,
    payload: Dict[str, Any],
    user: TokenData = Depends(get_current_user),
    svc: AixDashboardService = Depends(get_service),
) -> Dict[str, Any]:
    updated = await svc.update_client(user.user_id, client_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="client not found")
    return updated


@router.delete("/clients/{client_id}")
async def delete_client(
    client_id: str,
    user: TokenData = Depends(get_current_user),
    svc: AixDashboardService = Depends(get_service),
) -> Dict[str, Any]:
    ok = await svc.delete_client(user.user_id, client_id)
    return {"deleted": 1 if ok else 0}


# ── クライアント別チャット ──
@router.get("/clients/{client_id}/chat")
async def list_client_chat(
    client_id: str,
    user: TokenData = Depends(get_current_user),
    chat: AixClientChatService = Depends(get_chat_service),
) -> List[Dict[str, Any]]:
    return await chat.list_messages(user.user_id, client_id)


@router.post("/clients/{client_id}/chat")
async def send_client_chat(
    client_id: str,
    payload: Dict[str, Any],
    user: TokenData = Depends(get_current_user),
    chat: AixClientChatService = Depends(get_chat_service),
) -> Dict[str, Any]:
    msg = (payload.get("message") or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="message is required")
    try:
        return await chat.send(user.user_id, client_id, msg)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── 子テーブル共通ルート ──
@router.get("/{kind}")
async def list_children(
    kind: str,
    client_id: Optional[str] = Query(None),
    user: TokenData = Depends(get_current_user),
    svc: AixDashboardService = Depends(get_service),
) -> List[Dict[str, Any]]:
    if kind not in CHILD_KINDS:
        raise HTTPException(status_code=404, detail=f"unknown kind: {kind}")
    return await svc.list_children(kind, user.user_id, client_id)


@router.post("/{kind}")
async def create_child(
    kind: str,
    payload: Dict[str, Any],
    user: TokenData = Depends(get_current_user),
    svc: AixDashboardService = Depends(get_service),
) -> Dict[str, Any]:
    if kind not in CHILD_KINDS:
        raise HTTPException(status_code=404, detail=f"unknown kind: {kind}")
    return await svc.create_child(kind, user.user_id, payload)


@router.patch("/{kind}/{row_id}")
async def update_child(
    kind: str,
    row_id: str,
    payload: Dict[str, Any],
    user: TokenData = Depends(get_current_user),
    svc: AixDashboardService = Depends(get_service),
) -> Dict[str, Any]:
    if kind not in CHILD_KINDS:
        raise HTTPException(status_code=404, detail=f"unknown kind: {kind}")
    updated = await svc.update_child(kind, user.user_id, row_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="row not found")
    return updated


@router.delete("/{kind}/{row_id}")
async def delete_child(
    kind: str,
    row_id: str,
    user: TokenData = Depends(get_current_user),
    svc: AixDashboardService = Depends(get_service),
) -> Dict[str, Any]:
    if kind not in CHILD_KINDS:
        raise HTTPException(status_code=404, detail=f"unknown kind: {kind}")
    ok = await svc.delete_child(kind, user.user_id, row_id)
    return {"deleted": 1 if ok else 0}
