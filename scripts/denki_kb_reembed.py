"""denki_kb_chunk の埋め込みを今のモデル（build_denki_kb.EMBED_MODEL）で全部作り直す。

埋め込みモデルを替えた時に1回だけ使う（2026-10-28 Gemini → OpenAI text-embedding-3-large）。
    python scripts/denki_kb_reembed.py            # 全断片を作り直す
    python scripts/denki_kb_reembed.py --dump out.json   # 作ったベクトルを手元にも残す（しきい値の実測用）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import requests  # noqa: E402

from build_denki_kb import EMBED_BATCH, EMBED_MODEL, embed_texts, log  # noqa: E402

SB_URL = os.environ["SUPABASE_URL"].strip()
SB_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"].strip()
H = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}", "Content-Type": "application/json"}


def fetch_chunks() -> list[dict]:
    rows, start = [], 0
    while True:
        r = requests.get(
            f"{SB_URL}/rest/v1/denki_kb_chunk?select=id,doc_id,chunk_index,content&order=id.asc",
            headers={**H, "Range": f"{start}-{start + 999}"},
            timeout=60,
        )
        r.raise_for_status()
        page = r.json()
        rows.extend(page)
        if len(page) < 1000:
            return rows
        start += 1000


def patch(chunk_id: int, vec: list[float]) -> None:
    for attempt in range(5):
        r = requests.patch(
            f"{SB_URL}/rest/v1/denki_kb_chunk?id=eq.{chunk_id}",
            headers={**H, "Prefer": "return=minimal"},
            json={"embedding": vec},
            timeout=60,
        )
        if r.status_code in (200, 204):
            return
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"patch failed id={chunk_id} {r.status_code} {r.text[:200]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", help="作ったベクトルを JSON で残す先")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    rows = fetch_chunks()
    if args.limit:
        rows = rows[: args.limit]
    log(f"model={EMBED_MODEL} 断片 {len(rows)} 件")
    dumped: dict[int, dict] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i in range(0, len(rows), EMBED_BATCH):
            batch = rows[i : i + EMBED_BATCH]
            vecs = embed_texts([b["content"] for b in batch])
            list(pool.map(lambda bv: patch(bv[0]["id"], bv[1]), zip(batch, vecs)))
            if args.dump:
                for b, v in zip(batch, vecs):
                    dumped[b["id"]] = {"doc_id": b["doc_id"], "content": b["content"], "v": v}
            done += len(batch)
            if done % 1000 < EMBED_BATCH:
                log(f"  {done}/{len(rows)}")
    if args.dump:
        with open(args.dump, "w", encoding="utf-8") as f:
            json.dump(dumped, f, ensure_ascii=False)
    log(f"完了 {done} 件")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
    SB_URL = os.environ["SUPABASE_URL"].strip()
    SB_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"].strip()
    H = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}", "Content-Type": "application/json"}
    main()
