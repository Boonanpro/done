"""
inquiry のビジネスロジック
クライアントHPの問い合わせフォームを保存する。
通知は push_service 等で別途拡張可能。
"""
import asyncio
import logging
from typing import List, Optional

from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class InquiryService:
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.table = "inquiries"

    async def create(
        self,
        scope: str,
        name: str,
        message: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        company: Optional[str] = None,
        source_url: Optional[str] = None,
        user_agent: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> dict:
        row = {
            "scope": scope,
            "name": name,
            "message": message,
            "email": email,
            "phone": phone,
            "company": company,
            "source_url": source_url,
            "user_agent": user_agent,
            "client_ip": client_ip,
        }

        def _insert():
            return self.supabase.table(self.table).insert(row).execute()

        result = await asyncio.to_thread(_insert)
        created = result.data[0] if result.data else row
        logger.info("inquiry created scope=%s name=%s", scope, name)
        return created

    async def list(self, scope: Optional[str] = None, limit: int = 100) -> List[dict]:
        def _query():
            q = self.supabase.table(self.table).select("*")
            if scope:
                q = q.eq("scope", scope)
            return q.order("created_at", desc=True).limit(limit).execute()

        result = await asyncio.to_thread(_query)
        return result.data or []

    async def update_status(self, inquiry_id: str, status: str) -> Optional[dict]:
        def _update():
            return (
                self.supabase.table(self.table)
                .update({"status": status})
                .eq("id", inquiry_id)
                .execute()
            )

        result = await asyncio.to_thread(_update)
        return result.data[0] if result.data else None
