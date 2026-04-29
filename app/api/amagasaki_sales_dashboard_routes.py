"""
amagasaki_sales_dashboard のAPIエンドポイント
create_feature で自動生成。中身を実装してください。
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List
from app.services.auth_service import get_current_user, TokenData
from app.services.amagasaki_sales_dashboard_service import AmagasakiSalesDashboardService
from app.models.amagasaki_sales_dashboard_schemas import (
    AmagasakiSalesDashboardCreate,
    AmagasakiSalesDashboardUpdate,
    AmagasakiSalesDashboardResponse,
)

router = APIRouter(prefix="/api/v1/amagasaki-sales-dashboard", tags=["amagasaki_sales_dashboard"])


def get_service():
    return AmagasakiSalesDashboardService()


@router.get("", response_model=List[AmagasakiSalesDashboardResponse])
async def list_amagasaki_sales_dashboard(
    current_user: TokenData = Depends(get_current_user),
    service: AmagasakiSalesDashboardService = Depends(get_service),
):
    return await service.list(current_user.user_id)


@router.post("", response_model=AmagasakiSalesDashboardResponse)
async def create_amagasaki_sales_dashboard(
    data: AmagasakiSalesDashboardCreate,
    current_user: TokenData = Depends(get_current_user),
    service: AmagasakiSalesDashboardService = Depends(get_service),
):
    result = await service.create(data.model_dump(), current_user.user_id)
    if not result:
        raise HTTPException(status_code=400, detail="作成に失敗しました")
    return result


@router.get("/{id}", response_model=AmagasakiSalesDashboardResponse)
async def get_amagasaki_sales_dashboard(
    id: str,
    current_user: TokenData = Depends(get_current_user),
    service: AmagasakiSalesDashboardService = Depends(get_service),
):
    result = await service.get(id, current_user.user_id)
    if not result:
        raise HTTPException(status_code=404, detail="見つかりません")
    return result


@router.patch("/{id}", response_model=AmagasakiSalesDashboardResponse)
async def update_amagasaki_sales_dashboard(
    id: str,
    data: AmagasakiSalesDashboardUpdate,
    current_user: TokenData = Depends(get_current_user),
    service: AmagasakiSalesDashboardService = Depends(get_service),
):
    result = await service.update(id, data.model_dump(exclude_unset=True), current_user.user_id)
    if not result:
        raise HTTPException(status_code=404, detail="見つかりません")
    return result


@router.delete("/{id}")
async def delete_amagasaki_sales_dashboard(
    id: str,
    current_user: TokenData = Depends(get_current_user),
    service: AmagasakiSalesDashboardService = Depends(get_service),
):
    if not await service.delete(id, current_user.user_id):
        raise HTTPException(status_code=404, detail="見つかりません")
    return {"ok": True}
