"""
dan-notion: ファイルライブラリ/未紐付け 配下の 68件を 📥 とりあえず inbox に移動。

「未紐付け」は「あとで仕分けする予定だけど放置されている」状態のため、
新しい inbox 設計の意図と一致する。inbox に集約して AI 仕分け対象とする。

idempotent。DRY_RUN=1 で読み取りのみ。
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from supabase import create_client

DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"
OWNER = "2582a188-ff24-4a4f-b989-6063034d90b2"

env = Path("D:/done/.env").read_text(encoding="utf-8")
SB_URL = next(l.split("=", 1)[1].strip().strip('"') for l in env.splitlines() if l.startswith("SUPABASE_URL="))
SB_KEY = next(l.split("=", 1)[1].strip().strip('"') for l in env.splitlines() if l.startswith("SUPABASE_SERVICE_ROLE_KEY="))
sb = create_client(SB_URL, SB_KEY)


def find_inbox_id():
    r = sb.table("blocks").select("id").eq("user_id", OWNER) \
        .eq("source_id", "__inbox__").is_("deleted_at", "null").limit(1).execute()
    return r.data[0]["id"] if r.data else None


def find_unlinked_folder_id():
    r = sb.table("blocks").select("id,properties,content").eq("user_id", OWNER) \
        .eq("type", "page").is_("deleted_at", "null").execute()
    for b in r.data or []:
        title = (b.get("properties") or {}).get("title") or (b.get("content") or [{}])[0].get("text", "")
        if title == "未紐付け":
            return b["id"]
    return None


def main():
    inbox_id = find_inbox_id()
    unlinked_id = find_unlinked_folder_id()
    print(f"inbox id: {inbox_id}")
    print(f"unlinked folder id: {unlinked_id}")
    if not inbox_id or not unlinked_id:
        print("[abort] 必要な block が見つからない")
        return

    children = sb.table("blocks").select("id,type,properties,content,parent_id") \
        .eq("parent_id", unlinked_id).is_("deleted_at", "null").execute()
    print(f"\n=== 未紐付け 配下 {len(children.data or [])} 件 ===")

    for c in children.data or []:
        title = (c.get("properties") or {}).get("title") or (c.get("content") or [{}])[0].get("text", "")
        if DRY_RUN:
            print(f"  [DRY] would move [{c['type']}] {c['id'][:8]} {title[:40]!r} → inbox")
            continue
        # parent_id を inbox に変更 + needs_sorting フラグ + tags に inbox 追加
        old_props = c.get("properties") or {}
        new_props = {**old_props, "needs_sorting": True, "moved_from": "library_unlinked"}
        sb.table("blocks").update({
            "parent_id": inbox_id,
            "properties": new_props,
        }).eq("id", c["id"]).execute()
        print(f"  [move] [{c['type']}] {c['id'][:8]} {title[:40]!r}")

    print("\ndone.")


if __name__ == "__main__":
    main()
