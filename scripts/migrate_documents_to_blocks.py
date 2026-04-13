"""既存 documents → blocks 移行スクリプト.

documents テーブル (033_document_management.sql) のレコードを
blocks テーブル (036_blocks.sql) のページブロックに変換する。

documents には user_id カラムがないため、CLI引数で対象ユーザーIDを指定する。
関連する document_files は block_files に移行する。

使い方:
    python scripts/migrate_documents_to_blocks.py --user-id <uuid>
    python scripts/migrate_documents_to_blocks.py --user-id <uuid> --dry-run
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.supabase_client import get_supabase_client
from app.utils.fractional_index import generate_n_keys_between


DOC_TYPE_TO_BLOCK_TYPE = {
    "folder": "page",
    "file": "page",
    "collection": "database",
}


def migrate(user_id: str, dry_run: bool = False) -> None:
    supabase = get_supabase_client().client

    docs_res = (
        supabase.table("documents")
        .select("*")
        .eq("is_deleted", False)
        .order("sort_order")
        .execute()
    )
    docs = docs_res.data or []
    print(f"[info] {len(docs)} documents fetched")

    if not docs:
        return

    order_keys = generate_n_keys_between(None, None, len(docs))
    id_map: dict[str, str] = {}

    block_rows: list[dict] = []
    for doc, key in zip(docs, order_keys):
        new_id = str(uuid.uuid4())
        id_map[doc["id"]] = new_id
        block_type = DOC_TYPE_TO_BLOCK_TYPE.get(doc.get("doc_type") or "file", "page")

        properties = {
            "title": doc.get("title") or "Untitled",
        }
        if doc.get("description"):
            properties["description"] = doc["description"]

        content: list = []
        if doc.get("content"):
            content = [{"type": "markdown", "text": doc["content"]}]

        block_rows.append({
            "id": new_id,
            "user_id": user_id,
            "parent_id": None,  # 2周目で解決
            "_legacy_parent": doc.get("parent_id"),
            "type": block_type,
            "order_key": key,
            "properties": properties,
            "content": content,
            "icon": doc.get("icon"),
            "tags": doc.get("tags") or [],
            "is_starred": doc.get("is_starred") or False,
            "source": "manual",
            "source_id": f"document:{doc['id']}",
            "created_by": "user",
        })

    # parent_id を解決
    for row in block_rows:
        legacy_parent = row.pop("_legacy_parent")
        if legacy_parent and legacy_parent in id_map:
            row["parent_id"] = id_map[legacy_parent]

    print(f"[info] prepared {len(block_rows)} block rows")

    if dry_run:
        print("[dry-run] skip insert")
        for r in block_rows[:3]:
            print("  sample:", r["id"], r["type"], r["properties"].get("title"))
    else:
        res = supabase.table("blocks").insert(block_rows).execute()
        print(f"[info] inserted {len(res.data or [])} blocks")

    # ファイル移行
    files_res = (
        supabase.table("document_files")
        .select("*")
        .in_("document_id", list(id_map.keys()))
        .execute()
    )
    files = files_res.data or []
    print(f"[info] {len(files)} document_files found")

    file_rows: list[dict] = []
    for f in files:
        new_block_id = id_map.get(f["document_id"])
        if not new_block_id:
            continue
        file_rows.append({
            "id": str(uuid.uuid4()),
            "block_id": new_block_id,
            "storage_path": f.get("storage_path") or "",
            "original_name": f.get("original_name") or f.get("filename") or "unnamed",
            "mime_type": f.get("mime_type") or "application/octet-stream",
            "file_size": f.get("file_size") or 0,
            "version": f.get("version") or 1,
            "is_current": f.get("is_current", True),
            "checksum": f.get("checksum"),
            "thumbnail_path": f.get("thumbnail_path"),
        })

    if dry_run:
        print(f"[dry-run] would insert {len(file_rows)} block_files")
    elif file_rows:
        res = supabase.table("block_files").insert(file_rows).execute()
        print(f"[info] inserted {len(res.data or [])} block_files")

    print("[done] migration complete")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", required=True, help="対象ユーザーID (UUID)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    migrate(args.user_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
