"""Trigger Service — Dan Workspace Phase 3.

ユーザー定義トリガーのCRUDと手動発火を担当する。
実際のイベント監視 (gmail/calendar/file/cron/collab) は別ワーカーで行う想定。
ここではトリガー定義の管理と trigger_runs の記録だけを扱う。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class TriggerService:
    def __init__(self) -> None:
        self.supabase = get_supabase_client().client

    def _t(self):
        return self.supabase.table("triggers")

    def _r(self):
        return self.supabase.table("trigger_runs")

    # ------------------------------------------------------
    # Triggers CRUD
    # ------------------------------------------------------
    async def create(self, user_id: str, data: dict[str, Any]) -> dict:
        payload = {**data, "user_id": user_id}
        res = self._t().insert(payload).execute()
        return res.data[0]

    async def list(self, user_id: str, kind: Optional[str] = None) -> list[dict]:
        q = self._t().select("*").eq("user_id", user_id)
        if kind:
            q = q.eq("kind", kind)
        res = q.order("created_at", desc=True).execute()
        return res.data or []

    async def get(self, user_id: str, trigger_id: str) -> dict | None:
        res = self._t().select("*").eq("id", trigger_id).eq("user_id", user_id).execute()
        return res.data[0] if res.data else None

    async def update(self, user_id: str, trigger_id: str, patch: dict[str, Any]) -> dict | None:
        patch = {k: v for k, v in patch.items() if v is not None}
        if not patch:
            return await self.get(user_id, trigger_id)
        patch["updated_at"] = datetime.now(timezone.utc).isoformat()
        res = (
            self._t()
            .update(patch)
            .eq("id", trigger_id)
            .eq("user_id", user_id)
            .execute()
        )
        return res.data[0] if res.data else None

    async def delete(self, user_id: str, trigger_id: str) -> bool:
        res = self._t().delete().eq("id", trigger_id).eq("user_id", user_id).execute()
        return bool(res.data)

    # ------------------------------------------------------
    # Runs
    # ------------------------------------------------------
    async def start_run(
        self, user_id: str, trigger_id: str, payload: dict[str, Any]
    ) -> dict:
        row = {
            "trigger_id": trigger_id,
            "user_id": user_id,
            "status": "running",
            "payload": payload,
        }
        res = self._r().insert(row).execute()
        return res.data[0]

    async def finish_run(
        self,
        run_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict | None:
        patch = {
            "status": status,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "result": result or {},
            "error": error,
        }
        res = self._r().update(patch).eq("id", run_id).execute()
        return res.data[0] if res.data else None

    async def list_runs(
        self, user_id: str, trigger_id: Optional[str] = None, limit: int = 50
    ) -> list[dict]:
        q = self._r().select("*").eq("user_id", user_id)
        if trigger_id:
            q = q.eq("trigger_id", trigger_id)
        res = q.order("started_at", desc=True).limit(limit).execute()
        return res.data or []

    async def bump_fire_count(self, trigger_id: str) -> None:
        cur = self._t().select("fire_count").eq("id", trigger_id).execute()
        if not cur.data:
            return
        n = (cur.data[0].get("fire_count") or 0) + 1
        self._t().update(
            {
                "fire_count": n,
                "last_fired_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", trigger_id).execute()

    # ------------------------------------------------------
    # Manual fire (synchronous stub — actual action dispatch is Phase 4)
    # ------------------------------------------------------
    async def fire(
        self, user_id: str, trigger_id: str, payload: dict[str, Any]
    ) -> dict:
        trig = await self.get(user_id, trigger_id)
        if not trig:
            raise ValueError("trigger not found")
        run = await self.start_run(user_id, trigger_id, payload)
        try:
            from app.services.agent_service import get_agent_service
            agent = get_agent_service()
            result = await agent.orchestrate(user_id, trig, payload, run["id"])
            await self.finish_run(run["id"], "succeeded", result=result)
            await self.bump_fire_count(trigger_id)
            return {**run, "status": "succeeded", "result": result}
        except Exception as e:  # pragma: no cover
            logger.exception("trigger fire failed")
            await self.finish_run(run["id"], "failed", error=str(e))
            raise


_singleton: TriggerService | None = None


def get_trigger_service() -> TriggerService:
    global _singleton
    if _singleton is None:
        _singleton = TriggerService()
    return _singleton
