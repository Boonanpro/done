"""
chat_artifact のビジネスロジック
"""
from datetime import datetime, timezone
from typing import Optional, List
import re
from app.services.supabase_client import get_supabase_client


class ChatArtifactService:
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.table = "chat_artifact"

    def _normalize_payload(self, payload: dict) -> dict:
        slug = (payload.get("slug") or "").strip()
        kind = payload.get("kind") or "production"
        preview_url = payload.get("preview_url")
        if slug:
            payload.setdefault("preview_url", f"/artifacts/{slug}")
            preview_url = payload.get("preview_url")
        artifact_type = payload.get("artifact_type") or self.infer_artifact_type(
            slug=slug,
            label=payload.get("label"),
            path=preview_url,
        )
        payload["kind"] = kind
        payload["artifact_type"] = artifact_type
        if slug:
            default_share_url = self._share_url_for(preview_url, slug)
            payload.setdefault("share_url", default_share_url)
            payload.setdefault("draft_url", default_share_url)
            payload["share_url"] = self._to_preview_url(payload.get("share_url"), slug)
            payload["draft_url"] = self._to_preview_url(payload.get("draft_url"), slug)
        payload.setdefault("publish_status", "preview_live")
        payload.setdefault("delivery_status", "preview")
        payload.setdefault("delivery_mode", "preview")
        payload.setdefault("target_audience", "internal")
        payload.setdefault("requires_auth", False)
        payload.setdefault("payment_responsibility", "owner_pays")
        payload.setdefault("delivery_checklist", {})
        return payload

    @staticmethod
    def _to_preview_url(value: str | None, slug: str) -> str:
        if not value:
            return f"/preview/{slug}"
        if value == f"/artifacts/{slug}" or value.startswith(f"/artifacts/{slug}/"):
            return value.replace(f"/artifacts/{slug}", f"/preview/{slug}", 1)
        return value

    @staticmethod
    def _share_url_for(preview_url: str | None, slug: str) -> str:
        value = preview_url or f"/artifacts/{slug}"
        match = re.match(r"^/artifacts/([^/?#]+)([^?#]*)?([?#].*)?$", value)
        if match:
            return f"/preview/{match.group(1)}{match.group(2) or ''}{match.group(3) or ''}"
        return f"/preview/{slug}"

    @staticmethod
    def infer_artifact_type(slug: str = "", label: str | None = None, path: str | None = None) -> str:
        normalized_path = (path or "").replace("\\", "/").lower()
        path_parts = [part for part in normalized_path.split("/") if part]
        if "dashboards" in path_parts or "dashboard" in path_parts:
            return "dashboard"
        if any(part in path_parts for part in ("sites", "websites", "landing-pages")):
            return "website"
        if "tools" in path_parts:
            return "tool"

        text = " ".join([slug or "", label or "", path or ""]).lower()
        if any(token in text for token in ("dashboard", "dash", "analytics", "kpi")):
            return "dashboard"
        if any(token in text for token in ("website", "site", "homepage", "hp", "lp", "landing", "corporate", "company")):
            return "website"
        return "tool"

    async def list(
        self,
        user_id: str,
        project_id: Optional[str] = None,
        room_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[dict]:
        query = (
            self.supabase.table(self.table)
            .select("*")
            .eq("created_by", user_id)
        )
        if room_id:
            query = query.eq("room_id", room_id)
        elif project_id:
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
        payload = self._normalize_payload({**data, "created_by": user_id})
        if payload.get("project_id"):
            payload["project_id"] = str(payload["project_id"])
        if payload.get("room_id"):
            payload["room_id"] = str(payload["room_id"])
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
        data = self._normalize_payload(data) if data.get("slug") else data
        result = (
            self.supabase.table(self.table)
            .update(data)
            .eq("id", artifact_id)
            .eq("created_by", user_id)
            .execute()
        )
        return result.data[0] if result.data else None

    async def mark_preview_live(self, artifact_id: str, user_id: str) -> Optional[dict]:
        artifact = await self.get(artifact_id, user_id)
        if not artifact:
            return None
        slug = artifact["slug"]
        return await self.update(
            artifact_id,
            {
                "share_url": artifact.get("share_url") or f"/preview/{slug}",
                "draft_url": artifact.get("draft_url") or f"/preview/{slug}",
                "publish_status": "preview_live",
                "last_publish_error": None,
            },
            user_id,
        )

    async def connect_domain(self, artifact_id: str, domain: str, user_id: str) -> Optional[dict]:
        artifact = await self.get(artifact_id, user_id)
        if not artifact:
            return None
        if artifact.get("artifact_type") != "website":
            raise ValueError("custom domains are only available for website artifacts")
        normalized = domain.strip().lower().replace("https://", "").replace("http://", "").split("/")[0]
        if "." not in normalized:
            raise ValueError("domain must be a fully qualified domain name")
        return await self.update(
            artifact_id,
            {
                "custom_domain": normalized,
                "production_url": f"https://{normalized}",
                "publish_status": "domain_pending",
                "last_publish_error": None,
                "published_at": datetime.now(timezone.utc).isoformat(),
            },
            user_id,
        )

    async def list_custom_domain_map(self) -> dict:
        """custom_domain が設定された全 artifact の host -> slug マップ。

        middleware がカスタムドメインのリクエストを正しい artifact に
        ルーティングするために使う (公開・認証なし)。
        """
        result = (
            self.supabase.table(self.table)
            .select("slug, custom_domain")
            .execute()
        )
        mapping: dict = {}
        for row in result.data or []:
            domain = (row.get("custom_domain") or "").strip().lower()
            slug = row.get("slug")
            if not domain or not slug:
                continue
            mapping[domain] = slug
            if not domain.startswith("www."):
                mapping[f"www.{domain}"] = slug
        return mapping

    async def get_by_domain_setup_token(self, token: str) -> Optional[dict]:
        """ドメイン案内フローのトークンで artifact を引く (公開ページ用・認証なし)。"""
        if not token:
            return None
        result = (
            self.supabase.table(self.table)
            .select("*")
            .eq("domain_setup_token", token)
            .limit(1)
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
