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
        artifact = result.data[0] if result.data else None

        # dan-notion 自動整理: project 配下に block を追加
        # 失敗しても artifact 作成自体は成功扱いにする（best-effort）
        # dan-notion 自動整理: project_id 有無に関係なく inbox に投入し AI 後段仕分けに委ねる
        if artifact:
            try:
                from app.services.dan_notion_service import get_dan_notion_service
                project_title = None
                pid = artifact.get("project_id")
                if pid:
                    project_row = (
                        self.supabase.table("projects")
                        .select("title")
                        .eq("id", pid)
                        .limit(1)
                        .execute()
                    )
                    project_title = project_row.data[0]["title"] if project_row.data else None
                get_dan_notion_service().add_artifact_block_to_project(
                    user_id=user_id,
                    project_id=pid,
                    project_title=project_title,
                    artifact=artifact,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "dan-notion sync failed for artifact %s", artifact.get("id")
                )

        return artifact

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
