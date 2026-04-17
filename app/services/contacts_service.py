from typing import Optional, List
from app.services.supabase_client import get_supabase_client


class ContactsService:
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.table = "contacts"

    async def create(self, data: dict, user_id: str) -> dict:
        result = self.supabase.table(self.table).insert({
            **data,
            "created_by": user_id,
        }).execute()
        return result.data[0] if result.data else None

    async def get(self, id: str, user_id: str) -> Optional[dict]:
        result = self.supabase.table(self.table).select("*").eq("id", id).eq("created_by", user_id).execute()
        return result.data[0] if result.data else None

    async def list(self, user_id: str, limit: int = 200) -> List[dict]:
        result = self.supabase.table(self.table).select("*").eq("created_by", user_id).order("name").limit(limit).execute()
        return result.data or []

    async def update(self, id: str, data: dict, user_id: str) -> Optional[dict]:
        result = self.supabase.table(self.table).update(data).eq("id", id).eq("created_by", user_id).execute()
        return result.data[0] if result.data else None

    async def delete(self, id: str, user_id: str) -> bool:
        result = self.supabase.table(self.table).delete().eq("id", id).eq("created_by", user_id).execute()
        return bool(result.data)
