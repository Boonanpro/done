"""
予約ブロックのビジネスロジック。

backend が service-role キーで bookings テーブルを読み書きする。
空き枠の定義（営業時間・枠長・定員）はフロント側 (<BookingCalendar>) が持ち、
ここでは「その日の予約一覧」と「枠の予約数」を提供するだけに留める。
"""
from typing import List, Optional

from app.services.supabase_client import get_supabase_client


class BookingsService:
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.table = "bookings"

    async def list_for_date(self, artifact_slug: str, booking_date: str) -> List[dict]:
        """空き枠算出用: その店舗・その日の有効予約（個人情報は含めない）。"""
        result = (
            self.supabase.table(self.table)
            .select("booking_date,start_time,staff,party_size,status")
            .eq("artifact_slug", artifact_slug)
            .eq("booking_date", booking_date)
            .neq("status", "cancelled")
            .execute()
        )
        return result.data or []

    async def count_slot(
        self,
        artifact_slug: str,
        booking_date: str,
        start_time: str,
        staff: Optional[str],
    ) -> int:
        """同じ枠（店舗・日・時刻[・指名スタッフ]）の有効予約数。満席判定に使う。"""
        query = (
            self.supabase.table(self.table)
            .select("id", count="exact")
            .eq("artifact_slug", artifact_slug)
            .eq("booking_date", booking_date)
            .eq("start_time", start_time)
            .neq("status", "cancelled")
        )
        if staff:
            query = query.eq("staff", staff)
        result = query.execute()
        return result.count or 0

    async def create(self, data: dict) -> dict:
        """予約を作成する。"""
        result = self.supabase.table(self.table).insert(data).execute()
        return result.data[0] if result.data else {}

    async def list_for_slug(self, artifact_slug: str, limit: int = 200) -> List[dict]:
        """管理用: その店舗の予約一覧（日付の新しい順）。"""
        result = (
            self.supabase.table(self.table)
            .select("*")
            .eq("artifact_slug", artifact_slug)
            .order("booking_date", desc=True)
            .order("start_time", desc=False)
            .limit(limit)
            .execute()
        )
        return result.data or []
