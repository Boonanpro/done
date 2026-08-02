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
import asyncio
from pathlib import Path


PROJECT_ROOT = Path(r"D:/done")
sys.path.insert(0, str(PROJECT_ROOT))

# artifacts/{slug}/page.tsx と demo/{slug}/page.tsx の両方を拾う
PATH_PATTERN = re.compile(
    r"frontend[/\\]src[/\\]app[/\\](artifacts|demo)[/\\]([\w-]+)(?:[/\\]([^:]*?))?[/\\]page\.tsx$"
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
    root_slug = m.group(2)
    rest = (m.group(3) or "").strip("/\\").replace("\\", "/")
    slug = root_slug if not rest else f"{root_slug}-{'-'.join(part for part in rest.split('/') if part)}"
    preview_path = f"/{folder}/{root_slug}" + (f"/{rest}" if rest else "")

    # 成果物 (artifacts のみ。demo は除外) は favicon を自前アイコンに配線する。
    # ルート slug 単位 (例 kittoku-careers でも kittoku の layout/icon を整える)。
    if folder == "artifacts":
        try:
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from wire_artifact_icons import wire_slug

            status = wire_slug(root_slug)
            sys.stderr.write(f"[artifact icon] {root_slug} -> {status}\n")
        except Exception as e:
            sys.stderr.write(f"[artifact icon] failed: {e}\n")

        # 成果物ディレクトリは .gitignore 済みで Tailwind の自動ソース検出から漏れる。
        # slug 単位の @source を書き出しておかないと、成果物でしか使っていないクラスが
        # コンパイルされず、指定したレイアウトが無言で無視される。
        try:
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from wire_artifact_tailwind_sources import wire as wire_tw_sources

            tw_status = wire_tw_sources()
            sys.stderr.write(f"[artifact tailwind sources] {tw_status}\n")
        except Exception as e:
            sys.stderr.write(f"[artifact tailwind sources] failed: {e}\n")

    room_id = os.environ.get("DAN_ROOM_ID") or os.environ.get("DAN_SESSION_ID")
    project_id = os.environ.get("DAN_PROJECT_ID")
    if not room_id or not project_id:
        # project 紐づけなしで登録する意味は薄い。何もしない
        return 0

    try:
        from app.services.chat_artifact_service import ChatArtifactService
    except Exception:
        return 0

    try:
        service = ChatArtifactService()
        # 既存チェック
        exists = (
            service.supabase.table("chat_artifact")
            .select("id")
            .eq("room_id", room_id)
            .eq("preview_url", preview_path)
            .execute()
        )
        if exists.data:
            return 0

        # project の owner を取得
        proj = service.supabase.table("projects").select("user_id").eq("id", project_id).execute()
        if not proj.data:
            return 0
        owner_id = proj.data[0]["user_id"]

        # 登録
        kind = "demo" if folder == "demo" else "production"
        preview_url = preview_path
        lower = slug.lower()
        if any(token in lower for token in ("dashboard", "dash", "analytics", "kpi")):
            artifact_type = "dashboard"
        elif any(token in lower for token in ("website", "site", "homepage", "hp", "lp", "landing", "corporate", "company")):
            artifact_type = "website"
        else:
            artifact_type = "tool"
        share_url = preview_url if folder == "demo" else preview_url.replace(f"/{folder}/", "/preview/", 1)
        asyncio.run(service.create({
            "project_id": project_id,
            "room_id": room_id,
            "slug": slug,
            "kind": kind,
            "artifact_type": artifact_type,
            "label": slug.replace("-", " ").replace("_", " "),
            "preview_url": preview_url,
            "share_url": share_url,
            "draft_url": share_url,
            "publish_status": "preview_live",
        }, owner_id))
        sys.stderr.write(
            f"[artifact auto-register] {slug} -> {preview_url} (kind:{kind})\n"
        )
    except Exception as e:
        sys.stderr.write(f"[artifact auto-register] failed: {e}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
