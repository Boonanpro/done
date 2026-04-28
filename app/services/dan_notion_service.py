"""ダン用Notion: ビジネスロジック"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.services.supabase_client import get_supabase_client
from app.utils.fractional_index import key_between

logger = logging.getLogger(__name__)


class DanNotionService:
    """blocks / triggers / notifications の CRUD を提供"""

    def __init__(self) -> None:
        self.sb = get_supabase_client().client

    # ============================================================
    # Blocks
    # ============================================================

    def list_root_pages(self, user_id: str) -> list[dict[str, Any]]:
        """parent_id が NULL のページ一覧 (サイドバーツリー用)"""
        res = (
            self.sb.table("blocks")
            .select("*")
            .eq("user_id", user_id)
            .eq("type", "page")
            .is_("parent_id", "null")
            .is_("deleted_at", "null")
            .order("order_key")
            .execute()
        )
        return res.data or []

    def list_children(self, user_id: str, parent_id: str) -> list[dict[str, Any]]:
        res = (
            self.sb.table("blocks")
            .select("*")
            .eq("user_id", user_id)
            .eq("parent_id", parent_id)
            .is_("deleted_at", "null")
            .order("order_key")
            .execute()
        )
        return res.data or []

    def get_block(self, user_id: str, block_id: str) -> Optional[dict[str, Any]]:
        res = (
            self.sb.table("blocks")
            .select("*")
            .eq("id", block_id)
            .eq("user_id", user_id)
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    def _siblings_order_keys(
        self, user_id: str, parent_id: Optional[str]
    ) -> list[tuple[str, str]]:
        """同 parent の (id, order_key) を順に返す"""
        q = (
            self.sb.table("blocks")
            .select("id, order_key")
            .eq("user_id", user_id)
            .is_("deleted_at", "null")
            .order("order_key")
        )
        if parent_id is None:
            q = q.is_("parent_id", "null")
        else:
            q = q.eq("parent_id", parent_id)
        res = q.execute()
        return [(r["id"], r["order_key"]) for r in (res.data or [])]

    def _compute_order_key(
        self,
        user_id: str,
        parent_id: Optional[str],
        after_block_id: Optional[str] = None,
        before_block_id: Optional[str] = None,
    ) -> str:
        siblings = self._siblings_order_keys(user_id, parent_id)
        if not siblings:
            return key_between(None, None)

        ids = [s[0] for s in siblings]
        keys = [s[1] for s in siblings]

        if after_block_id and after_block_id in ids:
            i = ids.index(after_block_id)
            a = keys[i]
            b = keys[i + 1] if i + 1 < len(keys) else None
            return key_between(a, b)

        if before_block_id and before_block_id in ids:
            i = ids.index(before_block_id)
            a = keys[i - 1] if i > 0 else None
            b = keys[i]
            return key_between(a, b)

        # 末尾に追加
        return key_between(keys[-1], None)

    def get_or_create_project_page(
        self, user_id: str, project_id: str, project_title: Optional[str] = None
    ) -> dict[str, Any]:
        """
        プロジェクトに対応する dan-notion 上の root page block を取得 or 作成する。
        生成物（HP / 画像 / 動画 / ファイル）はこの page の配下に追加していくことで、
        プロジェクト単位の自動整理を実現する。

        識別子: source='agent' + source_id=project_id + properties.kind='project_root' でユニーク。
        （DB スキーマの source CHECK 制約に合わせるため source は 'agent' を使う）
        """
        existing = (
            self.sb.table("blocks")
            .select("*")
            .eq("user_id", user_id)
            .eq("source", "agent")
            .eq("source_id", str(project_id))
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        # properties.kind='project_root' でフィルタ（複数 source=agent 行に対応）
        for b in (existing.data or []):
            if (b.get("properties") or {}).get("kind") == "project_root":
                return b

        # 無ければ root page として作成
        title = project_title or "プロジェクト"
        order_key = self._compute_order_key(user_id, None, after_block_id=None)
        row = {
            "user_id": user_id,
            "parent_id": None,
            "type": "page",
            "order_key": order_key,
            "properties": {"kind": "project_root", "project_id": str(project_id)},
            "content": [{"type": "text", "text": title}],
            "tags": ["project", str(project_id)],
            "source": "agent",
            "source_id": str(project_id),
            "created_by": "system",
        }
        res = self.sb.table("blocks").insert(row).execute()
        return res.data[0] if res.data else row

    def add_artifact_block_to_project(
        self,
        user_id: str,
        project_id: str,
        project_title: Optional[str],
        artifact: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """
        chat_artifact (HP/ツール) を該当プロジェクトの root page 配下に
        block として追加する。既に同じ artifact_id の block があれば skip。
        """
        # 重複チェック (source='chat' + source_id=artifact_id + properties.kind='artifact')
        already = (
            self.sb.table("blocks")
            .select("id,properties")
            .eq("user_id", user_id)
            .eq("source", "chat")
            .eq("source_id", str(artifact["id"]))
            .is_("deleted_at", "null")
            .limit(5)
            .execute()
        )
        for b in (already.data or []):
            if (b.get("properties") or {}).get("kind") == "artifact":
                return b

        page = self.get_or_create_project_page(user_id, project_id, project_title)
        if not page:
            return None

        label = artifact.get("label") or artifact.get("slug") or "成果物"
        kind = artifact.get("kind") or "production"
        preview_url = artifact.get("preview_url") or ""
        order_key = self._compute_order_key(user_id, page["id"], after_block_id=None)
        row = {
            "user_id": user_id,
            "parent_id": page["id"],
            "type": "page",
            "order_key": order_key,
            "properties": {
                "kind": "artifact",
                "artifact_kind": kind,
                "slug": artifact.get("slug"),
                "preview_url": preview_url,
                "project_id": str(project_id),
            },
            "content": [{"type": "text", "text": f"📄 {label}"}],
            "tags": ["artifact", str(project_id)],
            "source": "chat",
            "source_id": str(artifact["id"]),
            "created_by": "system",
        }
        res = self.sb.table("blocks").insert(row).execute()
        return res.data[0] if res.data else None

    def add_asset_block_to_project(
        self,
        user_id: str,
        project_id: str,
        project_title: Optional[str],
        asset: dict[str, Any],
        asset_type: str,  # 'image' / 'video' / 'file' / 'pdf'
        source_id: str,
    ) -> Optional[dict[str, Any]]:
        """
        画像 / 動画 / ファイル等の asset を該当プロジェクトの root page 配下に
        block として追加する。重複は source + source_id でガード。
        """
        already = (
            self.sb.table("blocks")
            .select("id,properties")
            .eq("user_id", user_id)
            .eq("source", "chat")
            .eq("source_id", str(source_id))
            .is_("deleted_at", "null")
            .limit(5)
            .execute()
        )
        for b in (already.data or []):
            if (b.get("properties") or {}).get("kind") == f"asset_{asset_type}":
                return b

        page = self.get_or_create_project_page(user_id, project_id, project_title)
        if not page:
            return None

        url = asset.get("url") or asset.get("preview_url") or ""
        prompt = asset.get("prompt") or ""
        label = (prompt[:40] if prompt else asset_type) or asset_type
        order_key = self._compute_order_key(user_id, page["id"], after_block_id=None)

        icon_map = {"image": "🖼️", "video": "🎬", "file": "📎", "pdf": "📄"}
        prefix = icon_map.get(asset_type, "📦")

        row = {
            "user_id": user_id,
            "parent_id": page["id"],
            "type": asset_type if asset_type in ("image", "video", "pdf", "file") else "file",
            "order_key": order_key,
            "properties": {
                "kind": f"asset_{asset_type}",
                "url": url,
                "prompt": prompt,
                "project_id": str(project_id),
            },
            "content": [{"type": "text", "text": f"{prefix} {label}"}],
            "tags": [asset_type, str(project_id)],
            "source": "chat",
            "source_id": str(source_id),
            "created_by": "system",
        }
        res = self.sb.table("blocks").insert(row).execute()
        return res.data[0] if res.data else None

    def create_block(self, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        parent_id = data.get("parent_id")
        order_key = self._compute_order_key(
            user_id,
            str(parent_id) if parent_id else None,
            after_block_id=str(data["after_block_id"]) if data.get("after_block_id") else None,
        )
        row = {
            "user_id": user_id,
            "parent_id": str(parent_id) if parent_id else None,
            "type": data["type"],
            "order_key": order_key,
            "properties": data.get("properties") or {},
            "content": data.get("content") if data.get("content") is not None else [],
            "icon": data.get("icon"),
            "cover_url": data.get("cover_url"),
            "tags": data.get("tags") or [],
            "source": data.get("source") or "manual",
            "source_id": data.get("source_id"),
            "created_by": "user",
        }
        res = self.sb.table("blocks").insert(row).execute()
        return res.data[0] if res.data else None

    def update_block(
        self, user_id: str, block_id: str, data: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        update = {k: v for k, v in data.items() if v is not None}
        if not update:
            return self.get_block(user_id, block_id)
        res = (
            self.sb.table("blocks")
            .update(update)
            .eq("id", block_id)
            .eq("user_id", user_id)
            .is_("deleted_at", "null")
            .execute()
        )
        return res.data[0] if res.data else None

    def soft_delete_block(self, user_id: str, block_id: str) -> bool:
        from datetime import datetime, timezone
        res = (
            self.sb.table("blocks")
            .update({"deleted_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", block_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(res.data)

    def move_block(
        self,
        user_id: str,
        block_id: str,
        parent_id: Optional[str],
        after_block_id: Optional[str],
        before_block_id: Optional[str],
    ) -> Optional[dict[str, Any]]:
        order_key = self._compute_order_key(
            user_id, parent_id, after_block_id=after_block_id, before_block_id=before_block_id
        )
        update = {"order_key": order_key}
        if parent_id is not None:
            update["parent_id"] = parent_id
        res = (
            self.sb.table("blocks")
            .update(update)
            .eq("id", block_id)
            .eq("user_id", user_id)
            .execute()
        )
        return res.data[0] if res.data else None

    # ============================================================
    # Versions
    # ============================================================

    def list_versions(self, user_id: str, block_id: str) -> list[dict[str, Any]]:
        # block 所有確認
        if not self.get_block(user_id, block_id):
            return []
        res = (
            self.sb.table("block_versions")
            .select("*")
            .eq("block_id", block_id)
            .order("version", desc=True)
            .execute()
        )
        return res.data or []

    def restore_version(
        self, user_id: str, block_id: str, version: int
    ) -> Optional[dict[str, Any]]:
        block = self.get_block(user_id, block_id)
        if not block:
            return None
        ver = (
            self.sb.table("block_versions")
            .select("*")
            .eq("block_id", block_id)
            .eq("version", version)
            .limit(1)
            .execute()
        )
        if not ver.data:
            return None
        v = ver.data[0]
        return self.update_block(
            user_id, block_id, {"content": v["content"], "properties": v["properties"]}
        )

    # ============================================================
    # Triggers
    # ============================================================

    def list_triggers(self, user_id: str) -> list[dict[str, Any]]:
        res = (
            self.sb.table("triggers")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []

    def create_trigger(self, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        row = {"user_id": user_id, **data}
        res = self.sb.table("triggers").insert(row).execute()
        return res.data[0] if res.data else None

    def update_trigger(
        self, user_id: str, trigger_id: str, data: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        update = {k: v for k, v in data.items() if v is not None}
        if not update:
            return None
        res = (
            self.sb.table("triggers")
            .update(update)
            .eq("id", trigger_id)
            .eq("user_id", user_id)
            .execute()
        )
        return res.data[0] if res.data else None

    def delete_trigger(self, user_id: str, trigger_id: str) -> bool:
        res = (
            self.sb.table("triggers")
            .delete()
            .eq("id", trigger_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(res.data)

    def list_trigger_runs(
        self, user_id: str, trigger_id: Optional[str] = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        q = (
            self.sb.table("trigger_runs")
            .select("*")
            .eq("user_id", user_id)
            .order("started_at", desc=True)
            .limit(limit)
        )
        if trigger_id:
            q = q.eq("trigger_id", trigger_id)
        return q.execute().data or []

    def list_traces(self, user_id: str, run_id: str) -> list[dict[str, Any]]:
        res = (
            self.sb.table("agent_traces")
            .select("*")
            .eq("user_id", user_id)
            .eq("trigger_run_id", run_id)
            .order("created_at")
            .execute()
        )
        return res.data or []

    # ============================================================
    # Notifications
    # ============================================================

    def list_notifications(
        self, user_id: str, unread_only: bool = False, limit: int = 50
    ) -> list[dict[str, Any]]:
        q = (
            self.sb.table("dan_notifications")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
        )
        if unread_only:
            q = q.is_("read_at", "null")
        return q.execute().data or []

    def mark_notification_read(self, user_id: str, notification_id: str) -> bool:
        from datetime import datetime, timezone
        res = (
            self.sb.table("dan_notifications")
            .update({"read_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", notification_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(res.data)


_service: Optional[DanNotionService] = None


def get_dan_notion_service() -> DanNotionService:
    global _service
    if _service is None:
        _service = DanNotionService()
    return _service
