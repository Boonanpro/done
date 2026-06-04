"""
孤児アップロードファイルのクリーンアップ（案A: 参照されていないファイルだけ削除）

uploads/ のファイルは /api/v1/files/{name} で配信され、チャットに貼った動画・画像が
ずっと参照し続ける。単純な TTL 削除は過去チャットの添付を壊すため、
「どのメッセージ・添付レコードからも参照されていない孤児ファイル」だけを削除する。

参照元（ここに名前が出るファイルは絶対に消さない）:
  - chat_messages.content   … [添付動画: /api/v1/files/xxx] 等のタグ・URL
  - message_attachments     … storage_path / filename
  - detected_messages.content … メール本文中のファイルURL（テーブルがあれば）

安全策:
  - デフォルトは dry-run（--apply を付けない限り削除しない）
  - mtime が --grace-days 日以内のファイルは対象外（アップロード直後/送信中を保護）
  - DBの主要クエリ(chat_messages)が失敗したら何も削除せず中断（fail-safe）

使い方:
  python scripts/cleanup_orphan_uploads.py              # dry-run（消さずに一覧）
  python scripts/cleanup_orphan_uploads.py --apply      # 実削除
  python scripts/cleanup_orphan_uploads.py --grace-days 14 --apply
"""
import argparse
import re
import sys
import time
from pathlib import Path

# プロジェクトルートを import パスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.file_routes import UPLOAD_DIR  # noqa: E402
from app.services.supabase_client import get_supabase_client  # noqa: E402

# /api/v1/files/<name> または素の <name> を拾うための正規表現
FILE_URL_RE = re.compile(r"/api/v1/files/([A-Za-z0-9._\-]+)")
# UPLOAD_DIR のファイル名はだいたい uuid + 拡張子。素のファイル名参照も拾う保険。
BARE_NAME_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\.[A-Za-z0-9]+")


def _scan_table(sb, table: str, columns: str, required: bool):
    """テーブルを全ページ走査して行を yield する。

    Supabase/PostgREST は1リクエスト最大1000行で打ち切るため、必ずページングする。
    （ページングを怠ると参照を取りこぼし、参照ファイルを孤児と誤判定して消す危険がある）
    required=True のテーブルで失敗したら例外を投げる（呼び出し側で削除中断させる）。
    """
    size = 1000
    page = 0
    total = 0
    while True:
        try:
            res = (
                sb.table(table)
                .select(columns)
                .range(page * size, page * size + size - 1)
                .execute()
            )
        except Exception as e:
            if required:
                raise
            print(f"[scan] {table} スキップ: {e}")
            return
        rows = res.data or []
        for r in rows:
            yield r
        total += len(rows)
        if len(rows) < size:
            break
        page += 1
    print(f"[scan] {table}: {total} 行を走査")


def _collect_referenced(sb) -> set[str]:
    """全参照元を走査し、参照されているファイル名(basename)の集合を返す。"""
    referenced: set[str] = set()

    def add_from_text(text: str):
        if not text:
            return
        for m in FILE_URL_RE.findall(text):
            referenced.add(m)
        for m in BARE_NAME_RE.findall(text):
            referenced.add(m)

    # --- chat_messages.content（主参照元・必須） ---
    for r in _scan_table(sb, "chat_messages", "content", required=True):
        add_from_text(r.get("content") or "")

    # --- message_attachments（任意） ---
    for r in _scan_table(sb, "message_attachments", "storage_path, filename", required=False):
        sp = r.get("storage_path") or ""
        if sp:
            referenced.add(Path(sp).name)
        fn = r.get("filename") or ""
        if fn:
            referenced.add(fn)

    # --- detected_messages.content（任意・メール添付URL） ---
    for r in _scan_table(sb, "detected_messages", "content", required=False):
        add_from_text(r.get("content") or "")

    return referenced


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="実際に削除する（未指定なら dry-run）")
    ap.add_argument("--grace-days", type=float, default=7.0, help="この日数以内に更新されたファイルは対象外（デフォルト7日）")
    args = ap.parse_args()

    upload_dir = Path(UPLOAD_DIR)
    if not upload_dir.exists():
        print(f"UPLOAD_DIR が存在しません: {upload_dir}")
        return

    try:
        sb = get_supabase_client().client
        referenced = _collect_referenced(sb)
    except Exception as e:
        # fail-safe: DBが読めないときは絶対に削除しない
        print(f"[abort] 参照情報を取得できませんでした。安全のため何も削除しません: {e}")
        sys.exit(1)

    print(f"[info] 参照されているファイル名: {len(referenced)} 件")

    now = time.time()
    grace_sec = args.grace_days * 86400

    files = [p for p in upload_dir.glob("*") if p.is_file()]
    orphans = []
    protected_recent = 0
    for p in files:
        if p.name in referenced:
            continue
        age = now - p.stat().st_mtime
        if age < grace_sec:
            protected_recent += 1
            continue
        orphans.append(p)

    total_bytes = sum(p.stat().st_size for p in orphans)
    print(
        f"[result] uploads総数={len(files)} / 参照あり保持={len(files) - len(orphans) - protected_recent} "
        f"/ 猶予期間内で保護={protected_recent} / 孤児候補={len(orphans)} "
        f"({total_bytes / 1024 / 1024:.1f}MB)"
    )

    if not orphans:
        print("削除対象なし。")
        return

    for p in orphans:
        print(f"  {'DELETE' if args.apply else 'DRY-RUN'} {p.name} ({p.stat().st_size / 1024 / 1024:.1f}MB)")

    if not args.apply:
        print("\n※ dry-run です。実際に削除するには --apply を付けてください。")
        return

    deleted = 0
    for p in orphans:
        try:
            p.unlink()
            deleted += 1
        except Exception as e:
            print(f"  削除失敗 {p.name}: {e}")
    print(f"[done] {deleted} 件削除、{total_bytes / 1024 / 1024:.1f}MB 解放")


if __name__ == "__main__":
    main()
