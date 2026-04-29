"""
dan-notion: クライアント概念導入マイグレーション。

実施内容 (idempotent):
  1. clients テーブルに 2件 seed (吉川特装 / 尼崎)
  2. 既存 📥 受信箱 (a8126469) を「とりあえず」inbox に転換
     - title='とりあえず', kind='inbox', source='agent', source_id='__inbox__'
  3. トップレベル 📇 クライアント container を作成
  4. 各クライアントの client_root + 📁 制作物 を作成
  5. 既存 5 artifact を slug ベースで該当クライアントの 制作物 配下に移動
  6. 旧 project_root 3件 (空になる) をゴミ箱に soft-delete
  7. 旧 🚀 プロジェクト トップレベル (e2b4e0f7) もゴミ箱に soft-delete

DRY_RUN=1 で読み取りのみ。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from supabase import create_client

DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"
OWNER = "2582a188-ff24-4a4f-b989-6063034d90b2"

env = Path("D:/done/.env").read_text(encoding="utf-8")
SB_URL = next(l.split("=", 1)[1].strip().strip('"') for l in env.splitlines() if l.startswith("SUPABASE_URL="))
SB_KEY = next(l.split("=", 1)[1].strip().strip('"') for l in env.splitlines() if l.startswith("SUPABASE_SERVICE_ROLE_KEY="))
sb = create_client(SB_URL, SB_KEY)

os.environ["SUPABASE_URL"] = SB_URL
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = SB_KEY
from app.services.dan_notion_service import get_dan_notion_service

svc = get_dan_notion_service()

# 既存『🚀 プロジェクト』に手書きされていた情報から確定したクライアント
SEED_CLIENTS = ["吉川特装", "五条運輸", "バードSTC"]

# slug → client name (実案件の確定マッピング)
# AIX/amagasaki 系は内部デモなのでクライアント紐付けせず inbox に投入し、
# ユーザーが後で「自社デモ」として扱うか個別判断する
SLUG_TO_CLIENT = {
    "kittoku": "吉川特装",
    "yoshikawa-tokuso": "吉川特装",
}


def step1_seed_clients():
    print(f"\n=== Step 1: clients テーブル seed ({'DRY' if DRY_RUN else 'APPLY'}) ===")
    name_to_id = {}
    for name in SEED_CLIENTS:
        existing = sb.table("clients").select("id,name").eq("user_id", OWNER).eq("name", name).limit(1).execute()
        if existing.data:
            name_to_id[name] = existing.data[0]["id"]
            print(f"  [keep] {name} → {existing.data[0]['id'][:8]}")
            continue
        if DRY_RUN:
            print(f"  [DRY] would create client {name}")
            continue
        r = sb.table("clients").insert({"user_id": OWNER, "name": name}).execute()
        name_to_id[name] = r.data[0]["id"]
        print(f"  [new]  {name} → {r.data[0]['id'][:8]}")
    return name_to_id


def step2_convert_inbox():
    print(f"\n=== Step 2: 既存 📥 受信箱 → 📥 とりあえず inbox に転換 ===")
    # まず既に kind='inbox' source_id='__inbox__' があれば skip
    existing_new = sb.table("blocks").select("id").eq("user_id", OWNER) \
        .eq("source_id", "__inbox__").is_("deleted_at", "null").limit(1).execute()
    if existing_new.data:
        print(f"  [skip] inbox already exists: {existing_new.data[0]['id'][:8]}")
        return existing_new.data[0]["id"]

    # 既存 受信箱 を探す (title='受信箱' or content/icon が 📥)
    rb = sb.table("blocks").select("id,properties,content,icon").eq("user_id", OWNER) \
        .is_("parent_id", "null").is_("deleted_at", "null").execute()
    target = None
    for b in rb.data or []:
        title = (b.get("properties") or {}).get("title") or (b.get("content") or [{}])[0].get("text", "")
        if "受信箱" in title:
            target = b
            break
    if not target:
        print("  [warn] 既存受信箱が見つからないため、新規 inbox を作成")
        if DRY_RUN:
            print("  [DRY] would create new inbox")
            return None
        return svc.get_or_create_inbox(OWNER)["id"]

    print(f"  found 受信箱 id={target['id'][:8]}")
    if DRY_RUN:
        print("  [DRY] would convert to とりあえず + kind='inbox'")
        return target["id"]
    new_props = {**(target.get("properties") or {}), "kind": "inbox", "title": "とりあえず", "is_folder": True}
    sb.table("blocks").update({
        "properties": new_props,
        "content": [{"type": "text", "text": "とりあえず"}],
        "icon": "📥",
        "source": "agent",
        "source_id": "__inbox__",
        "tags": list(set((target.get("tags") or []) + ["inbox"])),
    }).eq("id", target["id"]).execute()
    print(f"  [convert] {target['id'][:8]} → とりあえず inbox")
    return target["id"]


def step3_create_client_structure(name_to_id):
    print(f"\n=== Step 3: 📇 クライアント + 各 client_root + 📁 制作物 作成 ===")
    if DRY_RUN:
        print("  [DRY] would create client_index + client_root + subfolders")
        return {}
    client_to_root = {}
    for name, cid in name_to_id.items():
        root = svc.get_or_create_client_root(OWNER, cid, name)
        prod = svc.get_or_create_subfolder(OWNER, root["id"], cid, "folder_production")
        print(f"  {name}: root={root['id'][:8]} 制作物={prod['id'][:8]}")
        client_to_root[name] = (root["id"], prod["id"])
    return client_to_root


def step4_move_artifacts(client_to_root, inbox_id):
    print(f"\n=== Step 4: 既存 artifact 5件を振り分け ===")
    r = sb.table("blocks").select("id,parent_id,properties,content,tags") \
        .eq("user_id", OWNER).eq("source", "chat").is_("deleted_at", "null").execute()
    artifacts = [b for b in (r.data or []) if (b.get("properties") or {}).get("kind") == "artifact"]
    print(f"  found {len(artifacts)} artifact blocks")
    for art in artifacts:
        slug = (art.get("properties") or {}).get("slug") or ""
        title = (art.get("properties") or {}).get("title", "")
        client_name = SLUG_TO_CLIENT.get(slug)
        if not client_name:
            for key, name in SLUG_TO_CLIENT.items():
                if key in title:
                    client_name = name
                    break

        if client_name and client_name in client_to_root:
            target_parent = client_to_root[client_name][1]
            dest_label = f"{client_name}/制作物"
        else:
            target_parent = inbox_id
            dest_label = "とりあえず (要AI判定)"

        if art.get("parent_id") == target_parent:
            print(f"  [keep] {art['id'][:8]} already under {dest_label}")
            continue
        if DRY_RUN:
            print(f"  [DRY] would move {art['id'][:8]} ({title}) → {dest_label}")
            continue
        old_tags = art.get("tags") or []
        new_tags = [t for t in old_tags if t not in ("inbox",)]
        if client_name:
            new_tags.append(client_name)
            new_props = {**(art.get("properties") or {}), "client_name": client_name, "needs_sorting": False}
        else:
            new_tags.append("inbox")
            new_props = {**(art.get("properties") or {}), "needs_sorting": True}
        sb.table("blocks").update({
            "parent_id": target_parent,
            "tags": list(set(new_tags)),
            "properties": new_props,
        }).eq("id", art["id"]).execute()
        print(f"  [move] {art['id'][:8]} ({title}) → {dest_label}")


def step5_trash_garbage():
    print(f"\n=== Step 5: 旧 project_root 3件 + 旧 🚀 プロジェクト top-level (手書きクライアント情報含む) を soft-delete ===")
    # 全 project_root を soft-delete (配下の空フォルダも)
    targets = []
    pr = sb.table("blocks").select("id,parent_id,properties,content").eq("user_id", OWNER) \
        .is_("deleted_at", "null").execute()
    for b in pr.data or []:
        if (b.get("properties") or {}).get("kind") == "project_root":
            targets.append(("project_root", b))
            sub = sb.table("blocks").select("id,properties").eq("parent_id", b["id"]).is_("deleted_at", "null").execute()
            for s in sub.data or []:
                if (s.get("properties") or {}).get("kind", "").startswith("folder_"):
                    grand = sb.table("blocks").select("id", count="exact").eq("parent_id", s["id"]).is_("deleted_at", "null").execute()
                    if grand.count == 0:
                        targets.append(("empty_folder", s))

    # 旧 🚀 プロジェクト top-level も soft-delete (手書き内容は今回参照したのでOK、必要ならゴミ箱から復元可能)
    rb = sb.table("blocks").select("id,properties,content").eq("user_id", OWNER) \
        .is_("parent_id", "null").is_("deleted_at", "null").execute()
    for b in rb.data or []:
        title = (b.get("properties") or {}).get("title") or (b.get("content") or [{}])[0].get("text", "")
        if title in ("プロジェクト",) or title.startswith("🚀 プロジェクト"):
            targets.append(("project_top", b))
            # 配下の手書き memo (heading + bullets) もまとめて soft-delete
            kids = sb.table("blocks").select("id,properties,content").eq("parent_id", b["id"]).is_("deleted_at", "null").execute()
            for k in kids.data or []:
                targets.append(("project_top_child", k))

    print(f"  対象 {len(targets)} 件")
    from datetime import datetime, timezone
    for kind, b in targets:
        title = (b.get("properties") or {}).get("title") or (b.get("content") or [{}])[0].get("text", "")
        if DRY_RUN:
            print(f"  [DRY] would trash [{kind}] {b['id'][:8]} {title!r}")
            continue
        sb.table("blocks").update({
            "deleted_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", b["id"]).execute()
        print(f"  [trash] [{kind}] {b['id'][:8]} {title!r}")


if __name__ == "__main__":
    name_to_id = step1_seed_clients()
    inbox_id = step2_convert_inbox()
    client_to_root = step3_create_client_structure(name_to_id)
    step4_move_artifacts(client_to_root, inbox_id)
    step5_trash_garbage()
    print("\ndone.")
