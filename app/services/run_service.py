"""
Agent run persistence for project chat.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from app.models.project_schemas import AgentRunState
from app.services.supabase_client import get_supabase_client


ACTIVE_RUN_STATES = {
    AgentRunState.RUNNING.value,
    AgentRunState.AWAITING_APPROVAL.value,
    AgentRunState.AWAITING_CONFIRMATION.value,
    AgentRunState.PAUSED.value,
}


class RunService:
    """Persist the current authoritative run for a project."""

    def __init__(self):
        self.supabase = get_supabase_client().client

    async def create_run(
        self,
        project_id: str,
        room_id: str,
        claude_session_id: Optional[str] = None,
        parent_run_id: Optional[str] = None,
        state: str = AgentRunState.RUNNING.value,
        metadata: Optional[dict] = None,
    ) -> dict:
        row = {
            "project_id": project_id,
            "room_id": room_id,
            "claude_session_id": claude_session_id,
            "parent_run_id": parent_run_id,
            "state": state,
            "metadata": metadata or {},
        }
        query = self.supabase.table("agent_runs").insert(row)
        result = await asyncio.to_thread(query.execute)
        if not result.data:
            raise ValueError("Failed to create agent run")
        return result.data[0]

    async def get_run(self, run_id: str) -> Optional[dict]:
        query = self.supabase.table("agent_runs").select("*").eq("id", run_id).limit(1)
        result = await asyncio.to_thread(query.execute)
        return result.data[0] if result.data else None

    async def get_current_run(self, project_id: str) -> Optional[dict]:
        query = (
            self.supabase.table("agent_runs")
            .select("*")
            .eq("project_id", project_id)
            .order("created_at", desc=True)
            .limit(20)
        )
        result = await asyncio.to_thread(query.execute)
        rows = result.data or []
        if not rows:
            return None

        for row in rows:
            if row.get("state") in ACTIVE_RUN_STATES and not row.get("superseded_by_run_id"):
                return row
        for row in rows:
            if not row.get("superseded_by_run_id"):
                return row
        return rows[0]

    async def update_run(
        self,
        run_id: str,
        *,
        state: Optional[str] = None,
        claude_session_id: Optional[str] = None,
        active_proposal_id: Optional[str] = None,
        superseded_by_run_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Optional[dict]:
        updates = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if state is not None:
            updates["state"] = state
        if claude_session_id is not None:
            updates["claude_session_id"] = claude_session_id
        if active_proposal_id is not None:
            updates["active_proposal_id"] = active_proposal_id
        if superseded_by_run_id is not None:
            updates["superseded_by_run_id"] = superseded_by_run_id
        if metadata is not None:
            updates["metadata"] = metadata

        query = self.supabase.table("agent_runs").update(updates).eq("id", run_id)
        result = await asyncio.to_thread(query.execute)
        return result.data[0] if result.data else None

    async def attach_claude_session(self, run_id: str, claude_session_id: str) -> Optional[dict]:
        return await self.update_run(run_id, claude_session_id=claude_session_id)

    async def set_active_proposal(self, run_id: str, proposal_id: str) -> Optional[dict]:
        return await self.update_run(run_id, active_proposal_id=proposal_id)

    async def supersede_run(self, old_run_id: str, new_run_id: str) -> Optional[dict]:
        return await self.update_run(
            old_run_id,
            state=AgentRunState.SUPERSEDED.value,
            superseded_by_run_id=new_run_id,
        )
