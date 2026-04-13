"""Block Service — Dan Workspace (AI Native Information Hub).

ブロックベースのCRUD、ツリー取得、並び替え、ファイル添付を担当する。
順序管理は Fractional Indexing を使用し、並び替え時のDB更新を1行に限定する。
"""

from __future__ import annotations

import logging
import mimetypes
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.supabase_client import get_supabase_client
from app.utils.fractional_index import key_between

logger = logging.getLogger(__name__)

BLOCK_UPLOAD_DIR = Path("D:/done/uploads/blocks")
BLOCK_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class BlockService:
    def __init__(self) -> None:
        self.supabase = get_supabase_client().client

    # ======================================================
    # Internal helpers
    # ======================================================

    def _table(self):
        return self.supabase.table("blocks")

    def _active(self, query):
        return query.is_("deleted_at", "null")

    async def _get_raw(self, block_id: str) -> dict | None:
        res = self._table().select("*").eq("id", block_id).execute()
        if res.data:
            return res.data[0]
        return None

    async def _resolve_order_key(
        self,
        user_id: str,
        parent_id: str | None,
        after_block_id: str | None,
        before_block_id: str | None,
    ) -> str:
        """並び替え時の order_key を計算する。"""
        after_key: str | None = None
        before_key: str | None = None

        if after_block_id:
            after = await self._get_raw(after_block_id)
            if after and after.get("user_id") == user_id:
                after_key = after.get("order_key")

        if before_block_id:
            before = await self._get_raw(before_block_id)
            if before and before.get("user_id") == user_id:
                before_key = before.get("order_key")

        # after/before の指定がない場合、末尾に追加
        if after_key is None and before_key is None:
            query = self._table().select("order_key").eq("user_id", user_id)
            if parent_id:
                query = query.eq("parent_id", parent_id)
            else:
                query = query.is_("parent_id", "null")
            query = self._active(query).order("order_key", desc=True).limit(1)
            res = query.execute()
            if res.data:
                after_key = res.data[0]["order_key"]

        return key_between(after_key, before_key)

    # ======================================================
    # CRUD
    # ======================================================

    async def create_block(self, user_id: str, payload: dict) -> dict:
        parent_id = payload.get("parent_id")
        after_block_id = payload.pop("after_block_id", None)
        before_block_id = payload.pop("before_block_id", None)

        order_key = await self._resolve_order_key(
            user_id=user_id,
            parent_id=parent_id,
            after_block_id=after_block_id,
            before_block_id=before_block_id,
        )

        insert_data = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "parent_id": parent_id,
            "type": payload["type"],
            "order_key": order_key,
            "properties": payload.get("properties") or {},
            "content": payload.get("content") or [],
            "icon": payload.get("icon"),
            "cover_url": payload.get("cover_url"),
            "tags": payload.get("tags") or [],
            "source": payload.get("source", "manual"),
            "source_id": payload.get("source_id"),
            "created_by": payload.get("created_by", "user"),
        }

        res = self._table().insert(insert_data).execute()
        if not res.data:
            raise RuntimeError("failed to create block")
        return res.data[0]

    async def get_block(self, user_id: str, block_id: str) -> dict | None:
        res = (
            self._table()
            .select("*")
            .eq("id", block_id)
            .eq("user_id", user_id)
            .is_("deleted_at", "null")
            .execute()
        )
        if not res.data:
            return None
        block = res.data[0]

        # 子の数を取得
        count_res = (
            self._table()
            .select("id", count="exact")
            .eq("parent_id", block_id)
            .is_("deleted_at", "null")
            .execute()
        )
        block["children_count"] = count_res.count or 0

        # 添付ファイルを取得
        files_res = (
            self.supabase.table("block_files")
            .select("*")
            .eq("block_id", block_id)
            .order("version", desc=True)
            .execute()
        )
        block["files"] = files_res.data or []
        return block

    async def list_children(
        self,
        user_id: str,
        parent_id: str | None,
    ) -> list[dict]:
        query = (
            self._table()
            .select("*")
            .eq("user_id", user_id)
            .is_("deleted_at", "null")
        )
        if parent_id is None:
            query = query.is_("parent_id", "null")
        else:
            query = query.eq("parent_id", parent_id)
        res = query.order("order_key").execute()
        return res.data or []

    async def update_block(
        self,
        user_id: str,
        block_id: str,
        updates: dict,
    ) -> dict | None:
        clean = {k: v for k, v in updates.items() if v is not None}
        if not clean:
            return await self.get_block(user_id, block_id)

        res = (
            self._table()
            .update(clean)
            .eq("id", block_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not res.data:
            return None
        return res.data[0]

    async def delete_block(self, user_id: str, block_id: str) -> bool:
        """ソフトデリート。"""
        now = datetime.now(timezone.utc).isoformat()
        res = (
            self._table()
            .update({"deleted_at": now})
            .eq("id", block_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(res.data)

    async def restore_block(self, user_id: str, block_id: str) -> bool:
        res = (
            self._table()
            .update({"deleted_at": None})
            .eq("id", block_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(res.data)

    async def move_block(
        self,
        user_id: str,
        block_id: str,
        parent_id: str | None,
        after_block_id: str | None,
        before_block_id: str | None,
    ) -> dict | None:
        order_key = await self._resolve_order_key(
            user_id=user_id,
            parent_id=parent_id,
            after_block_id=after_block_id,
            before_block_id=before_block_id,
        )
        res = (
            self._table()
            .update({"parent_id": parent_id, "order_key": order_key})
            .eq("id", block_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not res.data:
            return None
        return res.data[0]

    # ======================================================
    # Tree & search
    # ======================================================

    async def get_tree(self, user_id: str) -> list[dict]:
        """サイドバー用の軽量ツリー (page/database のみ)。"""
        res = (
            self._table()
            .select("id, parent_id, type, properties, icon, is_starred, order_key")
            .eq("user_id", user_id)
            .in_("type", ["page", "database"])
            .is_("deleted_at", "null")
            .order("order_key")
            .execute()
        )
        nodes: list[dict] = []
        for row in res.data or []:
            props = row.get("properties") or {}
            title = props.get("title") or "Untitled"
            nodes.append({
                "id": row["id"],
                "parent_id": row["parent_id"],
                "type": row["type"],
                "title": title,
                "icon": row.get("icon"),
                "is_starred": row.get("is_starred", False),
                "order_key": row["order_key"],
                "has_children": False,  # フロントで子の有無を判定
            })
        return nodes

    async def get_starred(self, user_id: str) -> list[dict]:
        res = (
            self._table()
            .select("*")
            .eq("user_id", user_id)
            .eq("is_starred", True)
            .is_("deleted_at", "null")
            .order("updated_at", desc=True)
            .execute()
        )
        return res.data or []

    async def get_recent(self, user_id: str, limit: int = 20) -> list[dict]:
        res = (
            self._table()
            .select("*")
            .eq("user_id", user_id)
            .in_("type", ["page", "database"])
            .is_("deleted_at", "null")
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []

    # ======================================================
    # Files
    # ======================================================

    async def attach_file(
        self,
        user_id: str,
        block_id: str,
        source_path: str,
        original_name: str,
    ) -> dict | None:
        block = await self._get_raw(block_id)
        if not block or block.get("user_id") != user_id:
            return None

        # 既存のcurrentを退役
        self.supabase.table("block_files").update({"is_current": False}).eq(
            "block_id", block_id
        ).eq("is_current", True).execute()

        # バージョン番号を決定
        prev = (
            self.supabase.table("block_files")
            .select("version")
            .eq("block_id", block_id)
            .order("version", desc=True)
            .limit(1)
            .execute()
        )
        next_version = (prev.data[0]["version"] + 1) if prev.data else 1

        # ファイルを uploads/blocks/ にコピー
        ext = Path(original_name).suffix
        stored_name = f"{uuid.uuid4().hex}{ext}"
        dest_path = BLOCK_UPLOAD_DIR / stored_name
        shutil.copy2(source_path, dest_path)

        mime_type, _ = mimetypes.guess_type(original_name)
        file_size = dest_path.stat().st_size

        insert_data = {
            "id": str(uuid.uuid4()),
            "block_id": block_id,
            "storage_path": str(dest_path),
            "original_name": original_name,
            "mime_type": mime_type or "application/octet-stream",
            "file_size": file_size,
            "version": next_version,
            "is_current": True,
        }
        res = self.supabase.table("block_files").insert(insert_data).execute()
        if not res.data:
            return None
        return res.data[0]

    async def list_files(self, user_id: str, block_id: str) -> list[dict]:
        block = await self._get_raw(block_id)
        if not block or block.get("user_id") != user_id:
            return []
        res = (
            self.supabase.table("block_files")
            .select("*")
            .eq("block_id", block_id)
            .order("version", desc=True)
            .execute()
        )
        return res.data or []


_singleton: BlockService | None = None


def get_block_service() -> BlockService:
    global _singleton
    if _singleton is None:
        _singleton = BlockService()
    return _singleton
