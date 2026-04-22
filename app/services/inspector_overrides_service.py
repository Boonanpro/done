"""
inspector_overrides のビジネスロジック
"""
from typing import Optional, List, Dict, Any
from app.services.supabase_client import get_supabase_client


class InspectorOverridesService:
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.table = "inspector_overrides"

    async def upsert(
        self,
        artifact_slug: str,
        element_key: str,
        styles: Optional[Dict[str, str]],
        attrs: Optional[Dict[str, str]],
        user_id: str,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        # 既存の overrides がある場合はマージする（同じ element_key に対して
        # 複数プロパティが段階的に送信されるため）
        existing = (
            self.supabase.table(self.table)
            .select("*")
            .eq("artifact_slug", artifact_slug)
            .eq("element_key", element_key)
            .eq("created_by", user_id)
            .limit(1)
            .execute()
        )
        merged_styles: Dict[str, str] = {}
        merged_attrs: Dict[str, str] = {}
        if existing.data:
            row = existing.data[0]
            merged_styles = dict(row.get("styles") or {})
            merged_attrs = dict(row.get("attrs") or {})
        if styles:
            merged_styles.update(styles)
        if attrs:
            merged_attrs.update(attrs)

        payload = {
            "artifact_slug": artifact_slug,
            "element_key": element_key,
            "styles": merged_styles,
            "attrs": merged_attrs,
            "created_by": user_id,
        }
        if project_id:
            payload["project_id"] = str(project_id)

        if existing.data:
            payload["updated_at"] = "now()"
            # Supabase Python client は now() を文字列として扱うので
            # updated_at は明示送信せず DB trigger に任せる
            payload.pop("updated_at", None)
            result = (
                self.supabase.table(self.table)
                .update({
                    "styles": merged_styles,
                    "attrs": merged_attrs,
                })
                .eq("id", existing.data[0]["id"])
                .execute()
            )
            if result.data:
                return result.data[0]
            return {**existing.data[0], "styles": merged_styles, "attrs": merged_attrs}

        result = self.supabase.table(self.table).insert(payload).execute()
        return result.data[0] if result.data else payload

    async def list_by_slug(self, artifact_slug: str, user_id: str) -> List[dict]:
        result = (
            self.supabase.table(self.table)
            .select("*")
            .eq("artifact_slug", artifact_slug)
            .eq("created_by", user_id)
            .execute()
        )
        return result.data or []

    async def delete_by_slug(self, artifact_slug: str, user_id: str) -> int:
        result = (
            self.supabase.table(self.table)
            .delete()
            .eq("artifact_slug", artifact_slug)
            .eq("created_by", user_id)
            .execute()
        )
        return len(result.data or [])

    async def delete_one(self, artifact_slug: str, element_key: str, user_id: str) -> bool:
        result = (
            self.supabase.table(self.table)
            .delete()
            .eq("artifact_slug", artifact_slug)
            .eq("element_key", element_key)
            .eq("created_by", user_id)
            .execute()
        )
        return bool(result.data)
