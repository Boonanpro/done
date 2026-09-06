"""
ダン用: 成果物ページ本文（artifact_documents）を読み書きする CLI。

  python scripts/artifact_doc.py <slug>                 # Markdown で表示（チェック状態つき）
  python scripts/artifact_doc.py <slug> --json          # ブロック JSON をそのまま表示
  python scripts/artifact_doc.py <slug> --revisions     # 版履歴（誰が何を変えたか）
  python scripts/artifact_doc.py <slug> --check <block_id> [--off]   # やることのチェックを付ける/外す
  python scripts/artifact_doc.py <slug> --text <block_id> "新しい本文"  # ブロック本文を書き換える
  python scripts/artifact_doc.py <slug> --import blocks.json          # 本文を丸ごと差し替える
  python scripts/artifact_doc.py <slug> --key           # 公開URLから編集するための鍵と URL を表示

ダンの編集は editor="dan" で保存され、部屋への編集通知は出ない（自分の変更を自分に知らせない）。
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "D:/done")

from app.services.artifact_documents_service import ArtifactDocumentsService  # noqa: E402


def _find(blocks, block_id):
    for b in blocks:
        if b.get("id") == block_id:
            return b
        hit = _find(b.get("children") or [], block_id)
        if hit:
            return hit
    return None


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    slug = argv[1]
    svc = ArtifactDocumentsService()
    row = svc.get_row(slug)
    if not row:
        print("見つかりません:", slug)
        return 2
    args = argv[2:]
    if "--json" in args:
        print(json.dumps(row.get("blocks") or [], ensure_ascii=False, indent=1))
        return 0
    if "--revisions" in args:
        import asyncio
        for r in asyncio.run(svc.revisions(slug)):
            print("v%s %s %s\n  %s" % (r["version"], r.get("created_at"), r.get("editor"), (r.get("summary") or "").replace("\n", "\n  ")))
        return 0
    if "--key" in args:
        from app.services.supabase_client import get_supabase_client
        sb = get_supabase_client().client
        art = sb.table("chat_artifact").select("share_url").eq("slug", slug).limit(1).execute()
        base = (art.data[0].get("share_url") if art.data else "") or ""
        print("edit_key:", row.get("edit_key"))
        if base:
            print("edit URL:", base.rstrip("/") + "/?edit=" + row.get("edit_key"))
        return 0
    blocks = row.get("blocks") or []
    if "--check" in args:
        bid = args[args.index("--check") + 1]
        b = _find(blocks, bid)
        if not b or b.get("type") != "checkListItem":
            print("やること（checkListItem）が見つかりません:", bid)
            return 3
        b.setdefault("props", {})["checked"] = "--off" not in args
        res = svc.save_sync(slug, blocks, title=None, editor="dan", base_version=None)
        print("saved v%s: %s" % (res.get("version"), res.get("changes")))
        return 0
    if "--text" in args:
        bid = args[args.index("--text") + 1]
        text = args[args.index("--text") + 2]
        b = _find(blocks, bid)
        if not b:
            print("ブロックが見つかりません:", bid)
            return 3
        b["content"] = [{"type": "text", "text": text, "styles": {}}]
        res = svc.save_sync(slug, blocks, title=None, editor="dan", base_version=None)
        print("saved v%s: %s" % (res.get("version"), res.get("changes")))
        return 0
    if "--import" in args:
        path = args[args.index("--import") + 1]
        new_blocks = json.load(open(path, encoding="utf-8"))
        res = svc.save_sync(slug, new_blocks, title=None, editor="dan", base_version=None)
        print("saved v%s (%d changes)" % (res.get("version"), len(res.get("changes") or [])))
        return 0
    sys.stdout.reconfigure(encoding="utf-8")
    print(svc.markdown(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
