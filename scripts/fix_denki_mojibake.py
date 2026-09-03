# -*- coding: utf-8 -*-
"""文字コードを誤って取り込んだ記事を、索引・知識ベースごと取り直す。

charset を返さない Shift_JIS のページ（佐近電気の koatukitei 配下など）は、
以前の収集処理が欧文コードページと誤判定して丸ごと文字化けしたまま保存していた。
判定は scripts/denki_encoding.py で直したので、このスクリプトは
すでに壊れた状態で入っているデータだけを対象に取り直す。

    python scripts/fix_denki_mojibake.py --dry-run   # 対象を出すだけ
    python scripts/fix_denki_mojibake.py             # 索引・DB・ベクトルを直す

このあと `python scripts/build_denki_kb.py --embed` でベクトルを作り直す。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

import build_denki_kb as kb  # noqa: E402
import refresh_denki_knowledge as rf  # noqa: E402
from denki_encoding import looks_mojibake  # noqa: E402

INDEX_PATH = os.path.join(ROOT, "frontend", "public", "denki-knowledge-index.json")


def is_mojibake(text: str) -> bool:
    return looks_mojibake(text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    index = json.load(io.open(INDEX_PATH, encoding="utf-8"))
    targets = [
        a for a in index["articles"]
        if is_mojibake((a.get("title") or "") + (a.get("text") or "")[:300])
    ]
    print(f"文字化けしている記事: {len(targets)} 件")
    for a in targets:
        print("  ", a["url"])
    if not targets or args.dry_run:
        return

    client = kb.sb()
    fixed = 0
    for a in targets:
        page = rf.extract_generic(a["url"])
        if not page or is_mojibake(page["title"]) or is_mojibake(page["text"][:300]):
            print(f"  取り直せず（索引）: {a['url']}")
            continue

        full, date = kb.extract_fulltext(a["url"])
        if len(full) < kb.MIN_DOC_CHARS or is_mojibake(full[:300]):
            print(f"  取り直せず（本文）: {a['url']}")
            continue

        # 1) 索引（公開サイトの検索が読むファイル）
        a["title"] = page["title"][:300]
        a["text"] = page["text"]
        if page.get("date") or date:
            a["date"] = page.get("date") or date

        # 2) 知識ベースの本文
        client.table("denki_kb_doc").upsert(
            [{
                "source_id": a["source"],
                "source_name": a.get("sourceName") or a["source"],
                "kind": "blog",
                "url": a["url"],
                "title": a["title"],
                "published_on": (date or a.get("date") or None) or None,
                "content": full,
                "char_count": len(full),
                "content_hash": hashlib.sha1(full.encode("utf-8")).hexdigest(),
            }],
            on_conflict="url",
        ).execute()

        # 3) 文字化けしたままのベクトルを捨てる（--embed で作り直される）
        row = client.table("denki_kb_doc").select("id").eq("url", a["url"]).limit(1).execute()
        if row.data:
            client.table("denki_kb_chunk").delete().eq("doc_id", row.data[0]["id"]).execute()
        fixed += 1
        print(f"  直した: {a['title'][:40]}")

    with io.open(INDEX_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    print(f"取り直し完了: {fixed} 件。続けて build_denki_kb.py --embed を実行すること。")


if __name__ == "__main__":
    main()
