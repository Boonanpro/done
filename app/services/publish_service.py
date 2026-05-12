"""
publish のビジネスロジック
create_feature で自動生成。中身を実装してください。
"""
from typing import Optional, List
from app.services.supabase_client import get_supabase_client


class PublishService:
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.table = "publish"

    async def create(self, data: dict, user_id: str) -> dict:
        """新規作成"""
        result = self.supabase.table(self.table).insert({
            **data,
            "created_by": user_id,
        }).execute()
        return result.data[0] if result.data else None

    async def get(self, id: str, user_id: str) -> Optional[dict]:
        """1件取得"""
        result = self.supabase.table(self.table).select("*").eq("id", id).eq("created_by", user_id).execute()
        return result.data[0] if result.data else None

    async def list(self, user_id: str, limit: int = 50) -> List[dict]:
        """一覧取得"""
        result = self.supabase.table(self.table).select("*").eq("created_by", user_id).order("created_at", desc=True).limit(limit).execute()
        return result.data or []

    async def update(self, id: str, data: dict, user_id: str) -> Optional[dict]:
        """更新"""
        result = self.supabase.table(self.table).update(data).eq("id", id).eq("created_by", user_id).execute()
        return result.data[0] if result.data else None

    async def delete(self, id: str, user_id: str) -> bool:
        """削除"""
        result = self.supabase.table(self.table).delete().eq("id", id).eq("created_by", user_id).execute()
        return bool(result.data)
