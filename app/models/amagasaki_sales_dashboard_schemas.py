"""
amagasaki_sales_dashboard のデータスキーマ
create_feature で自動生成。中身を実装してください。
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class AmagasakiSalesDashboardCreate(BaseModel):
    """新規作成リクエスト"""
    # TODO: フィールドを定義してください
    # 例:
    # title: str = Field(..., min_length=1)
    # content: Optional[dict] = None
    pass


class AmagasakiSalesDashboardUpdate(BaseModel):
    """更新リクエスト"""
    # TODO: 更新可能なフィールドを定義してください
    pass


class AmagasakiSalesDashboardResponse(BaseModel):
    """レスポンス"""
    id: UUID
    created_at: datetime
    updated_at: datetime
    # TODO: レスポンスフィールドを定義してください

    class Config:
        from_attributes = True
