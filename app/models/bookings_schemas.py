"""
予約ブロックのデータスキーマ。

クライアントHP/ツールに埋め込む <BookingCalendar> 用。エンドユーザー（来店客）は
アカウントを持たないため、識別は artifact_slug（どの店舗/サイトか）で行う。
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class BookingCreate(BaseModel):
    """予約作成リクエスト（来店客が送信）"""

    artifact_slug: str = Field(..., min_length=1, max_length=200)
    customer_name: str = Field(..., min_length=1, max_length=100)
    contact: str = Field(..., min_length=1, max_length=200)  # 電話 or メール
    booking_date: str = Field(..., description="YYYY-MM-DD")
    start_time: str = Field(..., description="HH:MM")
    service: Optional[str] = Field(None, max_length=200)
    staff: Optional[str] = Field(None, max_length=100)
    duration_min: int = Field(60, ge=5, le=600)
    party_size: int = Field(1, ge=1, le=100)
    notes: Optional[str] = Field(None, max_length=1000)
    # その枠の定員（<BookingCalendar> の設定値）。サーバーはこれで満席判定する。
    capacity: int = Field(1, ge=1, le=1000)


class BookingResponse(BaseModel):
    """予約レスポンス"""

    id: UUID
    artifact_slug: str
    customer_name: str
    contact: str
    service: Optional[str] = None
    staff: Optional[str] = None
    booking_date: str
    start_time: str
    duration_min: int
    party_size: int
    notes: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class SlotBooking(BaseModel):
    """空き枠算出用の最小情報（個人情報は返さない）"""

    booking_date: str
    start_time: str
    staff: Optional[str] = None
    party_size: int
    status: str
