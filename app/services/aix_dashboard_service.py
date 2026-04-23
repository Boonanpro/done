"""AIX事業ダッシュボード — サービス層

7テーブルへのCRUDと、パイプラインKPI集計を提供。
"""
import logging
from typing import Optional, List
from datetime import datetime, timezone

from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class AIXDashboardService:
    def __init__(self):
        self.supabase = get_supabase_client().client

    # ==========================================
    # クライアント
    # ==========================================
    async def list_clients(self, user_id: str, stage: Optional[str] = None) -> List[dict]:
        q = self.supabase.table("aix_clients").select("*").eq("created_by", user_id)
        if stage:
            q = q.eq("stage", stage)
        return q.order("updated_at", desc=True).execute().data

    async def get_client(self, client_id: str, user_id: str) -> Optional[dict]:
        r = self.supabase.table("aix_clients").select("*").eq("id", client_id).eq("created_by", user_id).execute()
        return r.data[0] if r.data else None

    async def create_client(self, data: dict, user_id: str) -> dict:
        r = self.supabase.table("aix_clients").insert({**data, "created_by": user_id}).execute()
        return r.data[0]

    async def update_client(self, client_id: str, data: dict, user_id: str) -> Optional[dict]:
        r = (
            self.supabase.table("aix_clients")
            .update(data)
            .eq("id", client_id)
            .eq("created_by", user_id)
            .execute()
        )
        return r.data[0] if r.data else None

    async def delete_client(self, client_id: str, user_id: str) -> bool:
        r = self.supabase.table("aix_clients").delete().eq("id", client_id).eq("created_by", user_id).execute()
        return bool(r.data)

    # ==========================================
    # 仮説
    # ==========================================
    async def list_hypotheses(self, client_id: str, user_id: str) -> List[dict]:
        return (
            self.supabase.table("aix_hypotheses")
            .select("*")
            .eq("client_id", client_id)
            .eq("created_by", user_id)
            .order("updated_at", desc=True)
            .execute()
            .data
        )

    async def create_hypothesis(self, data: dict, user_id: str) -> dict:
        if "client_id" in data:
            data["client_id"] = str(data["client_id"])
        r = self.supabase.table("aix_hypotheses").insert({**data, "created_by": user_id}).execute()
        return r.data[0]

    async def update_hypothesis(self, h_id: str, data: dict, user_id: str) -> Optional[dict]:
        r = (
            self.supabase.table("aix_hypotheses")
            .update(data)
            .eq("id", h_id)
            .eq("created_by", user_id)
            .execute()
        )
        return r.data[0] if r.data else None

    async def delete_hypothesis(self, h_id: str, user_id: str) -> bool:
        r = self.supabase.table("aix_hypotheses").delete().eq("id", h_id).eq("created_by", user_id).execute()
        return bool(r.data)

    # ==========================================
    # 提案
    # ==========================================
    async def list_proposals(self, client_id: Optional[str], user_id: str) -> List[dict]:
        q = self.supabase.table("aix_proposals").select("*").eq("created_by", user_id)
        if client_id:
            q = q.eq("client_id", client_id)
        return q.order("updated_at", desc=True).execute().data

    async def create_proposal(self, data: dict, user_id: str) -> dict:
        if "client_id" in data:
            data["client_id"] = str(data["client_id"])
        if "hypothesis_id" in data and data["hypothesis_id"]:
            data["hypothesis_id"] = str(data["hypothesis_id"])
        r = self.supabase.table("aix_proposals").insert({**data, "created_by": user_id}).execute()
        return r.data[0]

    async def update_proposal(self, p_id: str, data: dict, user_id: str) -> Optional[dict]:
        if "sent_at" in data and isinstance(data["sent_at"], datetime):
            data["sent_at"] = data["sent_at"].isoformat()
        r = (
            self.supabase.table("aix_proposals")
            .update(data)
            .eq("id", p_id)
            .eq("created_by", user_id)
            .execute()
        )
        return r.data[0] if r.data else None

    async def delete_proposal(self, p_id: str, user_id: str) -> bool:
        r = self.supabase.table("aix_proposals").delete().eq("id", p_id).eq("created_by", user_id).execute()
        return bool(r.data)

    # ==========================================
    # 営業活動
    # ==========================================
    async def list_activities(self, client_id: str, user_id: str) -> List[dict]:
        return (
            self.supabase.table("aix_activities")
            .select("*")
            .eq("client_id", client_id)
            .eq("created_by", user_id)
            .order("occurred_at", desc=True)
            .execute()
            .data
        )

    async def create_activity(self, data: dict, user_id: str) -> dict:
        if "client_id" in data:
            data["client_id"] = str(data["client_id"])
        if "proposal_id" in data and data["proposal_id"]:
            data["proposal_id"] = str(data["proposal_id"])
        if "occurred_at" in data and isinstance(data["occurred_at"], datetime):
            data["occurred_at"] = data["occurred_at"].isoformat()
        r = self.supabase.table("aix_activities").insert({**data, "created_by": user_id}).execute()
        return r.data[0]

    async def update_activity(self, a_id: str, data: dict, user_id: str) -> Optional[dict]:
        r = (
            self.supabase.table("aix_activities")
            .update(data)
            .eq("id", a_id)
            .eq("created_by", user_id)
            .execute()
        )
        return r.data[0] if r.data else None

    # ==========================================
    # 契約
    # ==========================================
    async def list_contracts(self, client_id: Optional[str], user_id: str) -> List[dict]:
        q = self.supabase.table("aix_contracts").select("*").eq("created_by", user_id)
        if client_id:
            q = q.eq("client_id", client_id)
        return q.order("updated_at", desc=True).execute().data

    async def create_contract(self, data: dict, user_id: str) -> dict:
        if "client_id" in data:
            data["client_id"] = str(data["client_id"])
        if "proposal_id" in data and data["proposal_id"]:
            data["proposal_id"] = str(data["proposal_id"])
        r = self.supabase.table("aix_contracts").insert({**data, "created_by": user_id}).execute()
        return r.data[0]

    async def update_contract(self, c_id: str, data: dict, user_id: str) -> Optional[dict]:
        r = (
            self.supabase.table("aix_contracts")
            .update(data)
            .eq("id", c_id)
            .eq("created_by", user_id)
            .execute()
        )
        return r.data[0] if r.data else None

    # ==========================================
    # 運用
    # ==========================================
    async def list_engagements(self, client_id: Optional[str], user_id: str) -> List[dict]:
        q = self.supabase.table("aix_engagements").select("*").eq("created_by", user_id)
        if client_id:
            q = q.eq("client_id", client_id)
        return q.order("updated_at", desc=True).execute().data

    async def create_engagement(self, data: dict, user_id: str) -> dict:
        if "client_id" in data:
            data["client_id"] = str(data["client_id"])
        if "contract_id" in data and data["contract_id"]:
            data["contract_id"] = str(data["contract_id"])
        r = self.supabase.table("aix_engagements").insert({**data, "created_by": user_id}).execute()
        return r.data[0]

    async def update_engagement(self, e_id: str, data: dict, user_id: str) -> Optional[dict]:
        r = (
            self.supabase.table("aix_engagements")
            .update(data)
            .eq("id", e_id)
            .eq("created_by", user_id)
            .execute()
        )
        return r.data[0] if r.data else None

    # ==========================================
    # ダンタスクハブ
    # ==========================================
    async def list_tasks(
        self,
        user_id: str,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        zone: Optional[str] = None,
    ) -> List[dict]:
        q = self.supabase.table("aix_tasks").select("*").eq("created_by", user_id)
        if client_id:
            q = q.eq("client_id", client_id)
        if status:
            q = q.eq("status", status)
        if zone:
            q = q.eq("zone", zone)
        return q.order("created_at", desc=True).execute().data

    async def create_task(self, data: dict, user_id: str) -> dict:
        for k in ("client_id", "proposal_id", "engagement_id"):
            if k in data and data[k]:
                data[k] = str(data[k])
        r = self.supabase.table("aix_tasks").insert({**data, "created_by": user_id}).execute()
        return r.data[0]

    async def update_task(self, t_id: str, data: dict, user_id: str) -> Optional[dict]:
        r = (
            self.supabase.table("aix_tasks")
            .update(data)
            .eq("id", t_id)
            .eq("created_by", user_id)
            .execute()
        )
        return r.data[0] if r.data else None

    async def delete_task(self, t_id: str, user_id: str) -> bool:
        r = self.supabase.table("aix_tasks").delete().eq("id", t_id).eq("created_by", user_id).execute()
        return bool(r.data)

    # ==========================================
    # パイプライン集計
    # ==========================================
    async def get_pipeline_kpi(self, user_id: str) -> dict:
        clients = (
            self.supabase.table("aix_clients").select("*").eq("created_by", user_id).execute().data
        )
        proposals = (
            self.supabase.table("aix_proposals").select("*").eq("created_by", user_id).execute().data
        )
        contracts = (
            self.supabase.table("aix_contracts").select("*").eq("created_by", user_id).execute().data
        )
        tasks = (
            self.supabase.table("aix_tasks")
            .select("*")
            .eq("created_by", user_id)
            .in_("status", ["todo", "in_progress", "awaiting_approval"])
            .execute()
            .data
        )

        active_clients = sum(1 for c in clients if c["stage"] not in ("lost", "paused"))
        proposals_sent = sum(1 for p in proposals if p["status"] in ("sent", "viewed", "replied", "won", "lost"))
        proposals_responded = sum(1 for p in proposals if p["status"] in ("viewed", "replied", "won", "lost"))
        response_rate = (proposals_responded / proposals_sent) if proposals_sent else 0.0

        contracted = sum(1 for c in contracts if c["status"] in ("active", "pending_signature"))
        monthly_estimated_value = sum(
            (c.get("monthly_value") or 0) for c in contracts if c["status"] == "active"
        )

        return {
            "active_clients": active_clients,
            "proposals_sent": proposals_sent,
            "proposals_responded": proposals_responded,
            "response_rate": round(response_rate, 2),
            "contracted": contracted,
            "monthly_estimated_value": monthly_estimated_value,
            "open_tasks": len(tasks),
        }

    async def get_pipeline_stages(self, user_id: str) -> List[dict]:
        clients = (
            self.supabase.table("aix_clients").select("*").eq("created_by", user_id).execute().data
        )
        buckets: dict = {}
        for c in clients:
            st = c["stage"]
            if st not in buckets:
                buckets[st] = {"stage": st, "count": 0, "estimated_value_total": 0}
            buckets[st]["count"] += 1
            buckets[st]["estimated_value_total"] += (c.get("estimated_value") or 0)
        return list(buckets.values())
