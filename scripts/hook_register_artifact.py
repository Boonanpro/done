"""
Artifact 自動登録 hook (PostToolUse)

ダンが `frontend/src/app/artifacts/{slug}/page.tsx` または
`frontend/src/app/demo/{slug}/page.tsx` を Write/Edit した時、
chat_artifact テーブルに登録されてなければ自動で 1 行 insert する。

これにより create_feature を呼び忘れても成果物タブが自動で出現する
(base44 / Manus のファイルシステム駆動と同等の挙動)。

DAN_PROJECT_ID 環境変数があれば project_id を紐づける。無ければ何もしない。
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(r"D:/done")
sys.path.insert(0, str(PROJECT_ROOT))

# artifacts/{slug}/page.tsx と demo/{slug}/page.tsx の両方を拾う
PATH_PATTERN = re.compile(
    r"frontend[/\\]src[/\\]app[/\\](artifacts)[/\\]([\w-]+)[/\\]page\.tsx$"
)


def main() -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return 0

    norm = file_path.replace("\\", "/")
    m = PATH_PATTERN.search(norm)
    if not m:
        return 0

    folder = m.group(1)  # 'artifacts' or 'demo'
    slug = m.group(2)

    project_id = os.environ.get("DAN_PROJECT_ID")
    if not project_id:
        # project 紐づけなしで登録する意味は薄い。何もしない
        return 0

    try:
        from app.services.supabase_client import get_supabase_client
        sb = get_supabase_client().client
    except Exception:
        return 0

    try:
        # 既存チェック
        exists = (
            sb.table("chat_artifact")
            .select("id")
            .eq("project_id", project_id)
            .eq("slug", slug)
            .execute()
        )
        if exists.data:
            return 0

        # project の owner を取得
        proj = sb.table("projects").select("user_id").eq("id", project_id).execute()
        if not proj.data:
            return 0
        owner_id = proj.data[0]["user_id"]

        # 登録
        kind = "production"
        preview_url = f"/{folder}/{slug}"
        lower = slug.lower()
        if any(token in lower for token in ("dashboard", "dash", "analytics", "kpi")):
            artifact_type = "dashboard"
        elif any(token in lower for token in ("website", "site", "homepage", "hp", "lp", "landing", "corporate", "company")):
            artifact_type = "website"
        else:
            artifact_type = "tool"
        sb.table("chat_artifact").insert({
            "project_id": project_id,
            "slug": slug,
            "kind": kind,
            "artifact_type": artifact_type,
            "label": slug.replace("-", " ").replace("_", " "),
            "preview_url": preview_url,
            "share_url": f"/preview/{slug}",
            "draft_url": f"/preview/{slug}",
            "publish_status": "preview_live",
            "created_by": owner_id,
        }).execute()
        sys.stderr.write(
            f"[artifact auto-register] {slug} -> {preview_url} (kind:{kind})\n"
        )
    except Exception as e:
        sys.stderr.write(f"[artifact auto-register] failed: {e}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
