"""
chat_artifact のビジネスロジック
"""
from typing import Optional, List
from app.services.supabase_client import get_supabase_client


class ChatArtifactService:
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.table = "chat_artifact"

    async def list(
        self,
        user_id: str,
        project_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[dict]:
        query = (
            self.supabase.table(self.table)
            .select("*")
            .eq("created_by", user_id)
        )
        if project_id:
            query = query.eq("project_id", project_id)
        result = query.order("created_at", desc=True).limit(limit).execute()
        return result.data or []

    async def get(self, artifact_id: str, user_id: str) -> Optional[dict]:
        result = (
            self.supabase.table(self.table)
            .select("*")
            .eq("id", artifact_id)
            .eq("created_by", user_id)
            .execute()
        )
        return result.data[0] if result.data else None

    async def create(self, data: dict, user_id: str) -> Optional[dict]:
        payload = {**data, "created_by": user_id}
        if payload.get("project_id"):
            payload["project_id"] = str(payload["project_id"])
        if payload.get("message_id"):
            payload["message_id"] = str(payload["message_id"])
        result = self.supabase.table(self.table).insert(payload).execute()
        return result.data[0] if result.data else None

    async def update(self, artifact_id: str, data: dict, user_id: str) -> Optional[dict]:
        result = (
            self.supabase.table(self.table)
            .update(data)
            .eq("id", artifact_id)
            .eq("created_by", user_id)
            .execute()
        )
        return result.data[0] if result.data else None

    async def delete(self, artifact_id: str, user_id: str) -> bool:
        result = (
            self.supabase.table(self.table)
            .delete()
            .eq("id", artifact_id)
            .eq("created_by", user_id)
            .execute()
        )
        return bool(result.data)
