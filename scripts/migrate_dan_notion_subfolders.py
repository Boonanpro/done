"""
dan-notion 既存データのサブフォルダ化マイグレーション。

実施内容:
  1. project_root の properties.title を content[0].text から補完
  2. 各プロジェクトに「制作物」サブフォルダを作成
  3. 既存の artifact (5件) の parent_id を「制作物」フォルダに付け替え
  4. （生成画像/動画は0件のため対象なし）

idempotent。何度実行しても同じ結果。
DRY_RUN=1 で読み取りのみ。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from supabase import create_client

DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

env = Path("D:/done/.env").read_text(encoding="utf-8")
SB_URL = next(l.split("=", 1)[1].strip().strip('"') for l in env.splitlines() if l.startswith("SUPABASE_URL="))
SB_KEY = next(l.split("=", 1)[1].strip().strip('"') for l in env.splitlines() if l.startswith("SUPABASE_SERVICE_ROLE_KEY="))
sb = create_client(SB_URL, SB_KEY)

# DanNotionService を使うために環境変数を整える
os.environ["SUPABASE_URL"] = SB_URL
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = SB_KEY
from app.services.dan_notion_service import get_dan_notion_service

svc = get_dan_notion_service()


def step1_fix_project_root_titles():
    print(f"\n=== Step 1: project_root の properties.title 補完 ({'DRY-RUN' if DRY_RUN else 'APPLY'}) ===")
    r = sb.table("blocks").select("id,user_id,properties,content") \
        .eq("source", "agent").is_("deleted_at", "null").execute()
    fixed = 0
    for b in r.data or []:
        props = b.get("properties") or {}
        if props.get("kind") != "project_root":
            continue
        if props.get("title"):
            continue  # 既に title あり
        content = b.get("content") or []
        title = content[0].get("text") if content else None
        if not title:
            continue
        new_props = {**props, "title": title}
        print(f"  [fix] {b['id'][:8]} title='{title[:30]}'")
        if not DRY_RUN:
            sb.table("blocks").update({"properties": new_props}).eq("id", b["id"]).execute()
        fixed += 1
    print(f"  fixed: {fixed}")


def step2_create_subfolders_and_move_artifacts():
    print(f"\n=== Step 2: 各プロジェクトに『制作物』フォルダ作成 + artifact 付け替え ===")
    # 全 artifact (kind='artifact') を取得
    r = sb.table("blocks").select("id,user_id,parent_id,properties,content,tags") \
        .eq("source", "chat").is_("deleted_at", "null").execute()
    artifacts = [b for b in (r.data or []) if (b.get("properties") or {}).get("kind") == "artifact"]
    print(f"  found {len(artifacts)} artifact blocks")

    for art in artifacts:
        props = art.get("properties") or {}
        project_id = props.get("project_id")
        user_id = art.get("user_id")
        if not project_id or not user_id:
            print(f"  [skip] {art['id'][:8]} missing project_id/user_id")
            continue

        # project_title を root から取得
        rr = sb.table("blocks").select("properties,content") \
            .eq("user_id", user_id).eq("source", "agent").eq("source_id", project_id) \
            .is_("deleted_at", "null").limit(1).execute()
        proj_title = None
        if rr.data:
            p = rr.data[0].get("properties") or {}
            proj_title = p.get("title") or (rr.data[0].get("content") or [{}])[0].get("text")

        # 制作物フォルダ取得/作成
        if DRY_RUN:
            print(f"  [DRY] would create folder_production for project {project_id[:8]} and move artifact {art['id'][:8]}")
            continue
        folder = svc.get_or_create_subfolder(user_id, project_id, proj_title, "folder_production")
        if not folder:
            print(f"  [err] folder creation failed for project {project_id[:8]}")
            continue

        # 既に制作物フォルダ配下なら skip
        if art.get("parent_id") == folder["id"]:
            print(f"  [keep] {art['id'][:8]} already under folder_production")
            continue

        # 移動 + properties.title 補完
        new_props = {**props}
        if not new_props.get("title"):
            label = (art.get("content") or [{}])[0].get("text", "") if art.get("content") else ""
            label = label.lstrip("📄 ").strip() or "成果物"
            new_props["title"] = label
        sb.table("blocks").update({
            "parent_id": folder["id"],
            "properties": new_props,
            "icon": "🎨",
        }).eq("id", art["id"]).execute()
        print(f"  [move] {art['id'][:8]} → folder {folder['id'][:8]} (project {project_id[:8]})")


if __name__ == "__main__":
    step1_fix_project_root_titles()
    step2_create_subfolders_and_move_artifacts()
    print("\ndone.")
