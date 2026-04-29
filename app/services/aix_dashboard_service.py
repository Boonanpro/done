"""
AIX事業ダッシュボードのビジネスロジック。
7テーブル (clients/hypotheses/proposals/activities/contracts/engagements/tasks) の CRUD を提供する。

- すべて created_by = user_id でスコープ分離（RLSと多重防御）
- snapshot() で全テーブルを1往復で取得する（フロント起動時用）
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

TABLES = {
    "clients": "aix_clients",
    "hypotheses": "aix_hypotheses",
    "proposals": "aix_proposals",
    "activities": "aix_activities",
    "contracts": "aix_contracts",
    "engagements": "aix_engagements",
    "tasks": "aix_tasks",
}


class AixDashboardService:
    def __init__(self):
        self.sb = get_supabase_client().client

    async def _list(
        self,
        kind: str,
        user_id: str,
        client_id: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        table = TABLES[kind]

        def _q():
            q = self.sb.table(table).select("*").eq("created_by", user_id)
            if client_id and kind != "clients":
                q = q.eq("client_id", client_id)
            return q.order("created_at", desc=True).limit(limit).execute()

        r = await asyncio.to_thread(_q)
        return r.data or []

    async def _get(self, kind: str, user_id: str, row_id: str) -> Optional[Dict[str, Any]]:
        table = TABLES[kind]

        def _q():
            return (
                self.sb.table(table)
                .select("*")
                .eq("created_by", user_id)
                .eq("id", row_id)
                .limit(1)
                .execute()
            )

        r = await asyncio.to_thread(_q)
        return (r.data or [None])[0]

    async def _create(self, kind: str, user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        table = TABLES[kind]
        row = {**payload, "created_by": user_id}
        row = {k: v for k, v in row.items() if v is not None}

        def _insert():
            return self.sb.table(table).insert(row).execute()

        r = await asyncio.to_thread(_insert)
        created = r.data[0] if r.data else row
        logger.info("aix %s created id=%s", kind, created.get("id"))
        return created

    async def _update(
        self, kind: str, user_id: str, row_id: str, patch: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        table = TABLES[kind]
        clean = {k: v for k, v in patch.items() if v is not None}
        if not clean:
            return await self._get(kind, user_id, row_id)

        def _u():
            return (
                self.sb.table(table)
                .update(clean)
                .eq("created_by", user_id)
                .eq("id", row_id)
                .execute()
            )

        r = await asyncio.to_thread(_u)
        return (r.data or [None])[0]

    async def _delete(self, kind: str, user_id: str, row_id: str) -> bool:
        table = TABLES[kind]

        def _d():
            return (
                self.sb.table(table)
                .delete()
                .eq("created_by", user_id)
                .eq("id", row_id)
                .execute()
            )

        r = await asyncio.to_thread(_d)
        return bool(r.data)

    # ── 公開API（clients）──
    async def list_clients(self, user_id: str) -> List[Dict[str, Any]]:
        return await self._list("clients", user_id)

    async def get_client(self, user_id: str, client_id: str) -> Optional[Dict[str, Any]]:
        return await self._get("clients", user_id, client_id)

    async def create_client(self, user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self._create("clients", user_id, payload)

    async def update_client(
        self, user_id: str, client_id: str, patch: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        return await self._update("clients", user_id, client_id, patch)

    async def delete_client(self, user_id: str, client_id: str) -> bool:
        return await self._delete("clients", user_id, client_id)

    # ── 子テーブル共通 ──
    async def list_children(
        self, kind: str, user_id: str, client_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if kind not in TABLES or kind == "clients":
            raise ValueError(f"unknown kind: {kind}")
        return await self._list(kind, user_id, client_id=client_id)

    async def create_child(
        self, kind: str, user_id: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        if kind not in TABLES or kind == "clients":
            raise ValueError(f"unknown kind: {kind}")
        return await self._create(kind, user_id, payload)

    async def update_child(
        self, kind: str, user_id: str, row_id: str, patch: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        if kind not in TABLES or kind == "clients":
            raise ValueError(f"unknown kind: {kind}")
        return await self._update(kind, user_id, row_id, patch)

    async def delete_child(self, kind: str, user_id: str, row_id: str) -> bool:
        if kind not in TABLES or kind == "clients":
            raise ValueError(f"unknown kind: {kind}")
        return await self._delete(kind, user_id, row_id)

    async def snapshot(self, user_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """全テーブル一括取得。フロントの起動時 1 リクで全データ揃える用途。"""
        kinds = list(TABLES.keys())
        results = await asyncio.gather(*[self._list(k, user_id) for k in kinds])
        return dict(zip(kinds, results))
