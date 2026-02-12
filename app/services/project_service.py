"""
Project Service - プロジェクト管理のビジネスロジック
"""
from typing import Optional
from datetime import datetime
import uuid
import logging

from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class ProjectService:
    """プロジェクト管理"""

    def __init__(self):
        self.supabase = get_supabase_client().client

    # ==================== Projects ====================

    async def create_project(
        self,
        user_id: str,
        title: str,
        description: Optional[str] = None,
        origin_room_id: Optional[str] = None,
    ) -> dict:
        """プロジェクトを作成し、専用チャットルームも作る"""
        project_id = str(uuid.uuid4())
        room_id = None

        # プロジェクト専用チャットルームを作成
        room_result = self.supabase.table("chat_rooms").insert({
            "name": title,
            "type": "project",
        }).execute()

        if room_result.data:
            room_id = room_result.data[0]["id"]
            # ルームメンバーに追加
            self.supabase.table("chat_room_members").insert({
                "room_id": room_id,
                "user_id": user_id,
                "role": "owner",
            }).execute()

        # プロジェクトを作成
        result = self.supabase.table("projects").insert({
            "id": project_id,
            "user_id": user_id,
            "title": title,
            "description": description,
            "status": "planning",
            "room_id": room_id,
            "origin_room_id": origin_room_id,
        }).execute()

        if not result.data:
            raise ValueError("Failed to create project")

        return result.data[0]

    async def get_project(self, project_id: str, user_id: str) -> Optional[dict]:
        """プロジェクトを取得（所有者チェック付き）"""
        result = (
            self.supabase.table("projects")
            .select("*")
            .eq("id", project_id)
            .eq("user_id", user_id)
            .execute()
        )
        return result.data[0] if result.data else None

    async def list_projects(
        self,
        user_id: str,
        status: Optional[str] = None,
    ) -> list[dict]:
        """ユーザーのプロジェクト一覧を取得"""
        query = (
            self.supabase.table("projects")
            .select("*")
            .eq("user_id", user_id)
        )
        if status:
            query = query.eq("status", status)

        result = query.order("updated_at", desc=True).execute()
        return result.data or []

    async def update_project(
        self,
        project_id: str,
        user_id: str,
        **updates,
    ) -> Optional[dict]:
        """プロジェクトを更新"""
        updates["updated_at"] = datetime.utcnow().isoformat()
        result = (
            self.supabase.table("projects")
            .update(updates)
            .eq("id", project_id)
            .eq("user_id", user_id)
            .execute()
        )
        return result.data[0] if result.data else None

    async def delete_project(self, project_id: str, user_id: str) -> bool:
        """プロジェクトを削除"""
        result = (
            self.supabase.table("projects")
            .delete()
            .eq("id", project_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(result.data)

    # ==================== Proposals ====================

    async def create_proposal(
        self,
        project_id: str,
        content: str,
        proposal_type: str = "plan",
        steps: Optional[list] = None,
    ) -> dict:
        """プロジェクトに提案を作成"""
        # 既存のpending提案をsupersededに
        self.supabase.table("project_proposals").update({
            "status": "superseded",
        }).eq("project_id", project_id).eq("status", "pending").execute()

        result = self.supabase.table("project_proposals").insert({
            "project_id": project_id,
            "content": content,
            "proposal_type": proposal_type,
            "steps": steps or [],
            "status": "pending",
        }).execute()

        if not result.data:
            raise ValueError("Failed to create proposal")

        # プロジェクトステータスをproposedに
        self.supabase.table("projects").update({
            "status": "proposed",
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("id", project_id).execute()

        return result.data[0]

    async def get_proposals(self, project_id: str) -> list[dict]:
        """プロジェクトの提案一覧"""
        result = (
            self.supabase.table("project_proposals")
            .select("*")
            .eq("project_id", project_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []

    async def approve_proposal(self, proposal_id: str, project_id: str) -> Optional[dict]:
        """提案を承認"""
        result = (
            self.supabase.table("project_proposals")
            .update({
                "status": "approved",
                "approved_at": datetime.utcnow().isoformat(),
            })
            .eq("id", proposal_id)
            .eq("project_id", project_id)
            .eq("status", "pending")
            .execute()
        )

        if result.data:
            # プロジェクトステータスをapprovedに
            self.supabase.table("projects").update({
                "status": "approved",
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("id", project_id).execute()

        return result.data[0] if result.data else None

    async def reject_proposal(self, proposal_id: str, project_id: str) -> Optional[dict]:
        """提案を却下"""
        result = (
            self.supabase.table("project_proposals")
            .update({"status": "rejected"})
            .eq("id", proposal_id)
            .eq("project_id", project_id)
            .eq("status", "pending")
            .execute()
        )

        if result.data:
            # プロジェクトステータスをplanningに戻す
            self.supabase.table("projects").update({
                "status": "planning",
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("id", project_id).execute()

        return result.data[0] if result.data else None
