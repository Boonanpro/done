"""Agent Service — Dan Workspace Phase 4.

自律エージェントのトレース記録と簡易オーケストレーション。
Claude Agent SDK の薄いラッパーを提供する。

現状の4エージェント:
- Orchestrator: トリガーペイロードを受け取り、下位エージェントを選んで呼び出す
- Classifier: 入力を分類する (例: メール → category)
- Organizer: ブロックを生成/整理する
- Notifier: Push/チャット通知を送る
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class AgentService:
    def __init__(self) -> None:
        self.supabase = get_supabase_client().client
        self._subscribers: list[asyncio.Queue] = []

    # ------------------------------------------------------
    # Trace storage + live fanout
    # ------------------------------------------------------
    def _table(self):
        return self.supabase.table("agent_traces")

    async def record(
        self,
        user_id: str,
        agent_name: str,
        event_type: str,
        content: dict[str, Any],
        trigger_run_id: Optional[str] = None,
        parent_trace_id: Optional[str] = None,
    ) -> dict:
        row = {
            "user_id": user_id,
            "agent_name": agent_name,
            "event_type": event_type,
            "content": content,
            "trigger_run_id": trigger_run_id,
            "parent_trace_id": parent_trace_id,
        }
        res = self._table().insert(row).execute()
        trace = res.data[0]
        for q in list(self._subscribers):
            try:
                q.put_nowait(trace)
            except Exception:
                pass
        return trace

    async def list_traces(
        self,
        user_id: str,
        trigger_run_id: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        q = self._table().select("*").eq("user_id", user_id)
        if trigger_run_id:
            q = q.eq("trigger_run_id", trigger_run_id)
        res = q.order("created_at", desc=False).limit(limit).execute()
        return res.data or []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    # ------------------------------------------------------
    # Agents (stubs for Phase 4 — real LLM calls are Phase 5)
    # ------------------------------------------------------
    async def classify(
        self, user_id: str, text: str, run_id: Optional[str], parent: Optional[str]
    ) -> dict:
        await self.record(
            user_id, "classifier", "thinking",
            {"input_len": len(text)}, run_id, parent,
        )
        # 単純ルールベース分類 (Phase 5 で LLM に差し替え)
        lower = text.lower()
        if any(k in lower for k in ("invoice", "請求", "領収")):
            category = "invoice"
        elif any(k in lower for k in ("meeting", "会議", "mtg")):
            category = "meeting"
        elif any(k in lower for k in ("task", "todo", "やる")):
            category = "task"
        else:
            category = "general"
        trace = await self.record(
            user_id, "classifier", "decision",
            {"category": category}, run_id, parent,
        )
        return {"category": category, "trace_id": trace["id"]}

    async def organize(
        self,
        user_id: str,
        payload: dict[str, Any],
        category: str,
        run_id: Optional[str],
        parent: Optional[str],
    ) -> dict:
        await self.record(
            user_id, "organizer", "thinking",
            {"category": category}, run_id, parent,
        )
        # ブロック作成: Phase 5 で block_service と連携
        result = {
            "block_created": False,
            "category": category,
            "reason": "organizer stub — Phase 5 で block_service 連携予定",
        }
        await self.record(
            user_id, "organizer", "complete", result, run_id, parent,
        )
        return result

    async def notify(
        self,
        user_id: str,
        message: str,
        run_id: Optional[str],
        parent: Optional[str],
    ) -> dict:
        result = {"sent": True, "message": message}
        await self.record(
            user_id, "notifier", "message", result, run_id, parent,
        )
        return result

    # ------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------
    async def orchestrate(
        self,
        user_id: str,
        trigger: dict[str, Any],
        payload: dict[str, Any],
        run_id: str,
    ) -> dict:
        root = await self.record(
            user_id, "orchestrator", "sub_agent_start",
            {"trigger_id": trigger.get("id"), "kind": trigger.get("kind")},
            run_id, None,
        )
        parent_id = root["id"]
        text = (
            payload.get("text")
            or payload.get("body")
            or payload.get("subject")
            or ""
        )
        outcome: dict[str, Any] = {"actions": []}
        for action in trigger.get("actions") or []:
            a_type = (action or {}).get("type")
            if a_type == "classify":
                cls = await self.classify(user_id, text, run_id, parent_id)
                outcome["classification"] = cls
            elif a_type == "organize":
                org = await self.organize(
                    user_id,
                    payload,
                    outcome.get("classification", {}).get("category", "general"),
                    run_id,
                    parent_id,
                )
                outcome["organize"] = org
            elif a_type == "notify":
                msg = (action or {}).get("message") or f"trigger {trigger.get('name')} fired"
                nt = await self.notify(user_id, msg, run_id, parent_id)
                outcome["notify"] = nt
            outcome["actions"].append(a_type)

        await self.record(
            user_id, "orchestrator", "complete", outcome, run_id, parent_id,
        )
        return outcome


_singleton: AgentService | None = None


def get_agent_service() -> AgentService:
    global _singleton
    if _singleton is None:
        _singleton = AgentService()
    return _singleton
