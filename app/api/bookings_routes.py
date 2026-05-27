"""
予約ブロックのAPIエンドポイント。

クライアントHP/ツールに埋め込む <BookingCalendar> 用。来店客はアカウントを持たない
ため public（認証なし）。どの店舗/サイトかは slug で区別する。
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from app.models.bookings_schemas import BookingCreate, BookingResponse, SlotBooking
from app.services.bookings_service import BookingsService

# main.py 側で prefix="/api/v1" を付けて登録するため、ここは "/bookings" のみ。
router = APIRouter(prefix="/bookings", tags=["bookings"])


def get_service() -> BookingsService:
    return BookingsService()


@router.get("/slots", response_model=List[SlotBooking])
async def get_slots(
    slug: str = Query(..., min_length=1),
    date: str = Query(..., description="YYYY-MM-DD"),
    service: BookingsService = Depends(get_service),
):
    """指定日の既存予約を返す。空き枠の算出はフロント側（設定の営業時間・枠長・定員）で行う。"""
    return await service.list_for_date(slug, date)


@router.post("", response_model=BookingResponse)
async def create_booking(
    data: BookingCreate,
    service: BookingsService = Depends(get_service),
):
    taken = await service.count_slot(
        data.artifact_slug, data.booking_date, data.start_time, data.staff
    )
    if taken >= data.capacity:
        raise HTTPException(
            status_code=409,
            detail="この時間帯は満席です。別の時間を選んでください。",
        )
    payload = data.model_dump(exclude={"capacity"})
    result = await service.create(payload)
    if not result:
        raise HTTPException(status_code=400, detail="予約の作成に失敗しました")
    return result


@router.get("", response_model=List[BookingResponse])
async def list_bookings(
    slug: str = Query(..., min_length=1),
    service: BookingsService = Depends(get_service),
):
    """管理用: 店舗の予約一覧。MVP では公開（slug を知っていれば閲覧可）。
    将来オーナー認証でガードする。"""
    return await service.list_for_slug(slug)
