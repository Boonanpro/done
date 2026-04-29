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
            "properties": {
                "kind": "project_root",
                "project_id": str(project_id),
                "title": title,  # サイドバー表示用（content fallbackより明示的）
            },
            "content": [{"type": "text", "text": title}],
            "tags": ["project", str(project_id)],
            "source": "agent",
            "source_id": str(project_id),
            "created_by": "system",
        }
        res = self.sb.table("blocks").insert(row).execute()
        return res.data[0] if res.data else row

    # ---- 素材サブフォルダ (制作物 / 画像素材 / 動画素材 / 資料) ----
    # client_root 配下に作る。inbox はトップレベルなのでここには含めない。

    SUBFOLDER_DEFS = {
        # folder_kind: (label, icon)
        "folder_production": ("制作物", "🎨"),
        "folder_image": ("画像素材", "🖼️"),
        "folder_video": ("動画素材", "🎬"),
        "folder_document": ("資料", "📄"),
    }

    def get_or_create_subfolder(
        self,
        user_id: str,
        owner_root_id: str,   # client_root or project_root の block id
        owner_scope_id: str,  # client_id or project_id (source_id 構築用)
        folder_kind: str,
    ) -> Optional[dict[str, Any]]:
        """
        オーナー root (client_root か project_root) 配下に
        「制作物」「画像素材」等のサブフォルダ page を idempotent に作成。
        識別子: source='agent' + source_id=f'{owner_scope_id}:{folder_kind}'。
        """
        if folder_kind not in self.SUBFOLDER_DEFS:
            raise ValueError(f"unknown folder_kind: {folder_kind}")
        label, icon = self.SUBFOLDER_DEFS[folder_kind]
        sid = f"{owner_scope_id}:{folder_kind}"

        existing = (
            self.sb.table("blocks")
            .select("*")
            .eq("user_id", user_id)
            .eq("source", "agent")
            .eq("source_id", sid)
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        for b in (existing.data or []):
            if (b.get("properties") or {}).get("kind") == folder_kind:
                return b

        order_key = self._compute_order_key(user_id, owner_root_id, after_block_id=None)
        row = {
            "user_id": user_id,
            "parent_id": owner_root_id,
            "type": "page",
            "order_key": order_key,
            "properties": {
                "kind": folder_kind,
                "scope_id": str(owner_scope_id),
                "title": label,
                "is_folder": True,
            },
            "content": [{"type": "text", "text": label}],
            "icon": icon,
            "tags": ["folder", str(owner_scope_id), folder_kind],
            "source": "agent",
            "source_id": sid,
            "created_by": "system",
        }
        res = self.sb.table("blocks").insert(row).execute()
        return res.data[0] if res.data else row

    # ---- トップレベル: 📥 とりあえず inbox ----

    def get_or_create_inbox(self, user_id: str) -> dict[str, Any]:
        """
        ユーザーの dan-notion トップレベル『📥 とりあえず』inbox block を取得 or 作成。
        AI が中身を読んで仕分ける universal バケツ。
        識別子: source='agent' + source_id='__inbox__' + properties.kind='inbox'。
        """
        existing = (
            self.sb.table("blocks")
            .select("*")
            .eq("user_id", user_id)
            .eq("source", "agent")
            .eq("source_id", "__inbox__")
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        for b in (existing.data or []):
            if (b.get("properties") or {}).get("kind") == "inbox":
                return b

        order_key = self._compute_order_key(user_id, None, after_block_id=None)
        row = {
            "user_id": user_id,
            "parent_id": None,
            "type": "page",
            "order_key": order_key,
            "properties": {"kind": "inbox", "title": "とりあえず", "is_folder": True},
            "content": [{"type": "text", "text": "とりあえず"}],
            "icon": "📥",
            "tags": ["inbox"],
            "source": "agent",
            "source_id": "__inbox__",
            "created_by": "system",
        }
        res = self.sb.table("blocks").insert(row).execute()
        return res.data[0] if res.data else row

    # ---- トップレベル: 📇 クライアント container ----

    def get_or_create_client_index(self, user_id: str) -> dict[str, Any]:
        """
        トップレベル『📇 クライアント』container を取得 or 作成。
        各 client_root はこの直下にぶら下がる。
        識別子: source='agent' + source_id='__client_index__' + kind='client_index'。
        """
        existing = (
            self.sb.table("blocks")
            .select("*")
            .eq("user_id", user_id)
            .eq("source", "agent")
            .eq("source_id", "__client_index__")
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        for b in (existing.data or []):
            if (b.get("properties") or {}).get("kind") == "client_index":
                return b

        order_key = self._compute_order_key(user_id, None, after_block_id=None)
        row = {
            "user_id": user_id,
            "parent_id": None,
            "type": "page",
            "order_key": order_key,
            "properties": {"kind": "client_index", "title": "クライアント", "is_folder": True},
            "content": [{"type": "text", "text": "クライアント"}],
            "icon": "📇",
            "tags": ["client_index"],
            "source": "agent",
            "source_id": "__client_index__",
            "created_by": "system",
        }
        res = self.sb.table("blocks").insert(row).execute()
        return res.data[0] if res.data else row

    # ---- 個別クライアント root ----

    def get_or_create_client_root(
        self,
        user_id: str,
        client_id: str,
        client_name: str,
    ) -> dict[str, Any]:
        """
        個別クライアントの root page を 📇 クライアント 配下に取得 or 作成。
        識別子: source='agent' + source_id=client_id + kind='client_root'。
        """
        existing = (
            self.sb.table("blocks")
            .select("*")
            .eq("user_id", user_id)
            .eq("source", "agent")
            .eq("source_id", str(client_id))
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        for b in (existing.data or []):
            if (b.get("properties") or {}).get("kind") == "client_root":
                return b

        index = self.get_or_create_client_index(user_id)
        order_key = self._compute_order_key(user_id, index["id"], after_block_id=None)
        row = {
            "user_id": user_id,
            "parent_id": index["id"],
            "type": "page",
            "order_key": order_key,
            "properties": {
                "kind": "client_root",
                "client_id": str(client_id),
                "title": client_name,
                "is_folder": True,
            },
            "content": [{"type": "text", "text": client_name}],
            "icon": "🏢",
            "tags": ["client", str(client_id)],
            "source": "agent",
            "source_id": str(client_id),
            "created_by": "system",
        }
        res = self.sb.table("blocks").insert(row).execute()
        return res.data[0] if res.data else row

    # ---- 受信メッセージ (Gmail / iCloud / LINE / 外部チャット) → inbox ----

    SOURCE_ICONS = {
        "gmail": "📧",
        "icloud_mail": "📧",
        "line": "💬",
        "slack": "💬",
        "done_chat": "💬",
    }

    def add_detected_message_to_inbox(
        self,
        user_id: str,
        source: str,
        source_id: Optional[str],
        subject: Optional[str],
        content: Optional[str],
        sender_info: dict[str, Any],
        metadata: dict[str, Any],
        detected_message_id: str,
    ) -> Optional[dict[str, Any]]:
        """
        外部メッセージ (メール等) を 📥 とりあえず inbox に block として追加する。
        重複は source + source_id でガード (source_id が無ければ detected_message_id)。
        """
        guard_id = source_id or detected_message_id
        already = (
            self.sb.table("blocks")
            .select("id,properties")
            .eq("user_id", user_id)
            .eq("source", source)
            .eq("source_id", str(guard_id))
            .is_("deleted_at", "null")
            .limit(3)
            .execute()
        )
        for b in (already.data or []):
            if (b.get("properties") or {}).get("kind") == "message":
                return b

        inbox = self.get_or_create_inbox(user_id)
        order_key = self._compute_order_key(user_id, inbox["id"], after_block_id=None)
        title = subject or (content or "")[:60] or f"({source})"
        excerpt = (content or "").strip()[:300]
        attachments = metadata.get("attachments") or []
        from_addr = sender_info.get("from") or sender_info.get("email") or ""
        date_str = sender_info.get("date") or ""
        icon = self.SOURCE_ICONS.get(source, "📬")

        row = {
            "user_id": user_id,
            "parent_id": inbox["id"],
            "type": "page",
            "order_key": order_key,
            "properties": {
                "kind": "message",
                "source_kind": source,
                "title": title,
                "subject": subject,
                "from": from_addr,
                "date": date_str,
                "excerpt": excerpt,
                "attachments_count": len(attachments),
                "detected_message_id": str(detected_message_id),
                "needs_sorting": True,
            },
            "content": [{"type": "text", "text": title}],
            "icon": icon,
            "tags": ["message", source, "inbox"],
            "source": source,
            "source_id": str(guard_id),
            "created_by": "system",
        }
        res = self.sb.table("blocks").insert(row).execute()
        message_block = res.data[0] if res.data else None
        if not message_block:
            return None

        # 添付ファイルを子 block として展開 (image/pdf/video/audio/file 自動判定)
        for idx, att in enumerate(attachments):
            try:
                att_url = att.get("url") or att.get("storage_path") or ""
                if not att_url:
                    continue
                fname = att.get("filename") or "attachment"
                content_type = (att.get("content_type") or "").lower()
                if content_type.startswith("image/"):
                    btype = "image"
                elif content_type == "application/pdf" or fname.lower().endswith(".pdf"):
                    btype = "pdf"
                elif content_type.startswith("video/"):
                    btype = "video"
                elif content_type.startswith("audio/"):
                    btype = "audio"
                else:
                    btype = "file"
                child_order = self._compute_order_key(user_id, message_block["id"], after_block_id=None)
                self.sb.table("blocks").insert({
                    "user_id": user_id,
                    "parent_id": message_block["id"],
                    "type": btype,
                    "order_key": child_order,
                    "properties": {
                        "kind": f"asset_{btype}",
                        "url": att_url,
                        "title": fname,
                        "original_name": fname,
                        "size": att.get("size"),
                        "content_type": content_type,
                        "from_email": True,
                        "needs_sorting": True,
                    },
                    "content": [{"type": "text", "text": fname}],
                    "tags": [btype, "attachment", "inbox", source],
                    "source": source,
                    "source_id": f"{guard_id}::att{idx}",
                    "created_by": "system",
                }).execute()
            except Exception:
                logger.exception("attach child block failed for %s", att.get("filename"))

        return message_block

    def add_artifact_block_to_project(
        self,
        user_id: str,
        project_id: Optional[str],
        project_title: Optional[str],
        artifact: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """
        chat_artifact (HP/ツール) を inbox に投入。AI 後段仕分けで client 配下に移動される想定。
        既に同じ artifact_id の block があれば skip。
        メソッド名は API 互換維持のため残しているが、project_id は metadata 扱い (None 可)。
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

        # 新方針 (2026-04-29~): 受信時はトップレベル inbox に投入。
        # 後段の AI 仕分けで client_root/制作物 へ移動される想定。
        inbox = self.get_or_create_inbox(user_id)

        label = artifact.get("label") or artifact.get("slug") or "成果物"
        kind = artifact.get("kind") or "production"
        preview_url = artifact.get("preview_url") or ""
        order_key = self._compute_order_key(user_id, inbox["id"], after_block_id=None)
        row = {
            "user_id": user_id,
            "parent_id": inbox["id"],
            "type": "page",
            "order_key": order_key,
            "properties": {
                "kind": "artifact",
                "artifact_kind": kind,
                "slug": artifact.get("slug"),
                "preview_url": preview_url,
                "project_id": str(project_id) if project_id else None,
                "title": label,
                "needs_sorting": True,
            },
            "content": [{"type": "text", "text": label}],
            "icon": "🎨",
            "tags": ["artifact", "inbox"] + ([str(project_id)] if project_id else []),
            "source": "chat",
            "source_id": str(artifact["id"]),
            "created_by": "system",
        }
        res = self.sb.table("blocks").insert(row).execute()
        return res.data[0] if res.data else None

    def add_asset_block_to_project(
        self,
        user_id: str,
        project_id: Optional[str],
        project_title: Optional[str],
        asset: dict[str, Any],
        asset_type: str,  # 'image' / 'video' / 'file' / 'pdf'
        source_id: str,
    ) -> Optional[dict[str, Any]]:
        """
        画像 / 動画 / ファイル等の asset を inbox に投入。AI 後段仕分けで適切な場所へ移動。
        重複は source + source_id でガード。
        メソッド名は API 互換維持のため残しているが、project_id は metadata 扱い (None 可)。
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

        # 新方針 (2026-04-29~): まず inbox に投入、AI が後で仕分け。
        inbox = self.get_or_create_inbox(user_id)
        url = asset.get("url") or asset.get("preview_url") or ""
        prompt = asset.get("prompt") or ""
        label = (prompt[:40] if prompt else asset_type) or asset_type
        order_key = self._compute_order_key(user_id, inbox["id"], after_block_id=None)

        row = {
            "user_id": user_id,
            "parent_id": inbox["id"],
            "type": asset_type if asset_type in ("image", "video", "pdf", "file") else "file",
            "order_key": order_key,
            "properties": {
                "kind": f"asset_{asset_type}",
                "url": url,
                "prompt": prompt,
                "needs_sorting": True,
                "project_id": str(project_id) if project_id else None,
                "title": label,
                "original_name": label,
            },
            "content": [{"type": "text", "text": label}],
            "tags": [asset_type, "inbox"] + ([str(project_id)] if project_id else []),
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
