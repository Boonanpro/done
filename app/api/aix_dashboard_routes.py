"""AIX事業ダッシュボード — APIエンドポイント

すべて認証必須。created_byスコープでユーザー専用。
"""
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.services.auth_service import TokenData, decode_access_token
from app.services.aix_dashboard_service import AIXDashboardService
from app.models.aix_dashboard_schemas import (
    ClientCreate, ClientUpdate, ClientResponse,
    HypothesisCreate, HypothesisUpdate, HypothesisResponse,
    ProposalCreate, ProposalUpdate, ProposalResponse,
    ActivityCreate, ActivityUpdate, ActivityResponse,
    ContractCreate, ContractUpdate, ContractResponse,
    EngagementCreate, EngagementUpdate, EngagementResponse,
    TaskCreate, TaskUpdate, TaskResponse,
    PipelineKPI, PipelineStageBucket,
)

logger = logging.getLogger(__name__)

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


def get_service() -> AIXDashboardService:
    return AIXDashboardService()


# ============================================================
# パイプライン（ダッシュボードトップ）
# ============================================================
@router.get("/pipeline/kpi", response_model=PipelineKPI)
async def pipeline_kpi(
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    return await service.get_pipeline_kpi(user.sub)


@router.get("/pipeline/stages", response_model=List[PipelineStageBucket])
async def pipeline_stages(
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    return await service.get_pipeline_stages(user.sub)


# ============================================================
# クライアント
# ============================================================
@router.get("/clients", response_model=List[ClientResponse])
async def list_clients(
    stage: Optional[str] = None,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    return await service.list_clients(user.sub, stage=stage)


@router.post("/clients", response_model=ClientResponse)
async def create_client(
    data: ClientCreate,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    return await service.create_client(data.model_dump(), user.sub)


@router.get("/clients/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: str,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    c = await service.get_client(client_id, user.sub)
    if not c:
        raise HTTPException(404, "client not found")
    return c


@router.patch("/clients/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: str,
    data: ClientUpdate,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    c = await service.update_client(client_id, data.model_dump(exclude_unset=True), user.sub)
    if not c:
        raise HTTPException(404, "client not found")
    return c


@router.delete("/clients/{client_id}")
async def delete_client(
    client_id: str,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    ok = await service.delete_client(client_id, user.sub)
    if not ok:
        raise HTTPException(404, "client not found")
    return {"ok": True}


# ============================================================
# 仮説
# ============================================================
@router.get("/clients/{client_id}/hypotheses", response_model=List[HypothesisResponse])
async def list_hypotheses(
    client_id: str,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    return await service.list_hypotheses(client_id, user.sub)


@router.post("/hypotheses", response_model=HypothesisResponse)
async def create_hypothesis(
    data: HypothesisCreate,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    return await service.create_hypothesis(data.model_dump(), user.sub)


@router.patch("/hypotheses/{h_id}", response_model=HypothesisResponse)
async def update_hypothesis(
    h_id: str,
    data: HypothesisUpdate,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    h = await service.update_hypothesis(h_id, data.model_dump(exclude_unset=True), user.sub)
    if not h:
        raise HTTPException(404, "hypothesis not found")
    return h


@router.delete("/hypotheses/{h_id}")
async def delete_hypothesis(
    h_id: str,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    ok = await service.delete_hypothesis(h_id, user.sub)
    if not ok:
        raise HTTPException(404, "hypothesis not found")
    return {"ok": True}


# ============================================================
# 提案
# ============================================================
@router.get("/proposals", response_model=List[ProposalResponse])
async def list_proposals(
    client_id: Optional[str] = Query(None),
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    return await service.list_proposals(client_id, user.sub)


@router.post("/proposals", response_model=ProposalResponse)
async def create_proposal(
    data: ProposalCreate,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    return await service.create_proposal(data.model_dump(), user.sub)


@router.patch("/proposals/{p_id}", response_model=ProposalResponse)
async def update_proposal(
    p_id: str,
    data: ProposalUpdate,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    p = await service.update_proposal(p_id, data.model_dump(exclude_unset=True), user.sub)
    if not p:
        raise HTTPException(404, "proposal not found")
    return p


@router.delete("/proposals/{p_id}")
async def delete_proposal(
    p_id: str,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    ok = await service.delete_proposal(p_id, user.sub)
    if not ok:
        raise HTTPException(404, "proposal not found")
    return {"ok": True}


# ============================================================
# 営業活動
# ============================================================
@router.get("/clients/{client_id}/activities", response_model=List[ActivityResponse])
async def list_activities(
    client_id: str,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    return await service.list_activities(client_id, user.sub)


@router.post("/activities", response_model=ActivityResponse)
async def create_activity(
    data: ActivityCreate,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    return await service.create_activity(data.model_dump(), user.sub)


@router.patch("/activities/{a_id}", response_model=ActivityResponse)
async def update_activity(
    a_id: str,
    data: ActivityUpdate,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    a = await service.update_activity(a_id, data.model_dump(exclude_unset=True), user.sub)
    if not a:
        raise HTTPException(404, "activity not found")
    return a


# ============================================================
# 契約
# ============================================================
@router.get("/contracts", response_model=List[ContractResponse])
async def list_contracts(
    client_id: Optional[str] = Query(None),
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    return await service.list_contracts(client_id, user.sub)


@router.post("/contracts", response_model=ContractResponse)
async def create_contract(
    data: ContractCreate,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    return await service.create_contract(data.model_dump(), user.sub)


@router.patch("/contracts/{c_id}", response_model=ContractResponse)
async def update_contract(
    c_id: str,
    data: ContractUpdate,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    c = await service.update_contract(c_id, data.model_dump(exclude_unset=True), user.sub)
    if not c:
        raise HTTPException(404, "contract not found")
    return c


# ============================================================
# 運用
# ============================================================
@router.get("/engagements", response_model=List[EngagementResponse])
async def list_engagements(
    client_id: Optional[str] = Query(None),
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    return await service.list_engagements(client_id, user.sub)


@router.post("/engagements", response_model=EngagementResponse)
async def create_engagement(
    data: EngagementCreate,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    return await service.create_engagement(data.model_dump(), user.sub)


@router.patch("/engagements/{e_id}", response_model=EngagementResponse)
async def update_engagement(
    e_id: str,
    data: EngagementUpdate,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    e = await service.update_engagement(e_id, data.model_dump(exclude_unset=True), user.sub)
    if not e:
        raise HTTPException(404, "engagement not found")
    return e


# ============================================================
# ダンタスクハブ
# ============================================================
@router.get("/tasks", response_model=List[TaskResponse])
async def list_tasks(
    client_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    zone: Optional[str] = Query(None),
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    return await service.list_tasks(user.sub, client_id=client_id, status=status, zone=zone)


@router.post("/tasks", response_model=TaskResponse)
async def create_task(
    data: TaskCreate,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    return await service.create_task(data.model_dump(), user.sub)


@router.patch("/tasks/{t_id}", response_model=TaskResponse)
async def update_task(
    t_id: str,
    data: TaskUpdate,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    t = await service.update_task(t_id, data.model_dump(exclude_unset=True), user.sub)
    if not t:
        raise HTTPException(404, "task not found")
    return t


@router.delete("/tasks/{t_id}")
async def delete_task(
    t_id: str,
    user: TokenData = Depends(get_current_user),
    service: AIXDashboardService = Depends(get_service),
):
    ok = await service.delete_task(t_id, user.sub)
    if not ok:
        raise HTTPException(404, "task not found")
    return {"ok": True}
