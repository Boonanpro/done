# -*- coding: utf-8 -*-
"""電管ナレッジ AI一次回答の知識基盤ビルダー

既存の frontend/public/denki-knowledge-index.json（記事メタ＋冒頭1500字）を起点に、
本文を「切らずに」取り直して Supabase の denki_kb_doc へ入れる。
YouTube は字幕（手動→自動の順）を本文として入れる。
その後、チャンク分割して Gemini 埋め込みを付け denki_kb_chunk へ入れる。

使い方:
    python scripts/build_denki_kb.py --fetch            # ブログ本文を全文取得
    python scripts/build_denki_kb.py --subs             # YouTube字幕を取得
    python scripts/build_denki_kb.py --embed            # 未埋め込みのdocをチャンク化＋ベクトル化
    python scripts/build_denki_kb.py --stats            # 現状の件数・文字数

オプション:
    --source ID     対象ソースを絞る
    --limit N       件数を絞る（試験用）
    --refetch       既に取り込み済みのURLも取り直す
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from denki_encoding import decode_html  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

requests.packages.urllib3.disable_warnings()  # type: ignore
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

INDEX_PATH = os.path.join(ROOT, "frontend", "public", "denki-knowledge-index.json")
UA = "Mozilla/5.0 (compatible; DenkiKnowledgeBot/1.0; +https://denkiouen.com)"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"}
TIMEOUT = 25

CHUNK_SIZE = 600          # 1断片の文字数（日本語）
CHUNK_OVERLAP = 100
MIN_DOC_CHARS = 80        # これ未満は知識として使わない
EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 768
EMBED_BATCH = 40          # 1リクエストあたりの断片数

session = requests.Session()
session.headers.update(HEADERS)


def log(msg: str) -> None:
    print(msg, flush=True)


def clean(s: str) -> str:
    s = re.sub(r"[ \t　]+", " ", s or "")
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def sb():
    from app.services.supabase_client import get_supabase_client
    return get_supabase_client().client


# ───────────────────────── 本文の取得 ─────────────────────────
def extract_fulltext(url: str) -> tuple[str, str]:
    """(本文, 日付) を返す。取れなければ ("", "")。"""
    try:
        r = session.get(url, timeout=TIMEOUT, verify=False)
    except Exception:
        return "", ""
    if r.status_code != 200:
        return "", ""
    html = decode_html(r)

    text, date = "", ""
    try:
        import trafilatura
        got = trafilatura.extract(
            html, url=url, favor_recall=True, include_comments=False,
            include_tables=True, output_format="json", with_metadata=True,
        )
        if got:
            d = json.loads(got)
            text = clean(d.get("text") or "")
            date = (d.get("date") or "")[:10]
    except Exception:
        pass

    # trafilatura が取りこぼす古い個人サイト向けのフォールバック
    if len(text) < MIN_DOC_CHARS:
        soup = BeautifulSoup(html, "html.parser")
        for t in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
            t.decompose()
        body_el = None
        for sel in [".entry-content", ".article-body", ".post-content", ".articleBody",
                    "article", ".entry", ".post", "#main", "main"]:
            body_el = soup.select_one(sel)
            if body_el:
                break
        text = clean((body_el or soup).get_text("\n"))
    if not date:
        m = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", html)
        if m:
            date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return text, date


def fetch_blogs(args) -> None:
    with open(INDEX_PATH, encoding="utf-8") as f:
        doc = json.load(f)
    src_type = {s["id"]: s.get("type", "html") for s in doc["sources"]}

    client = sb()
    done_urls = set()
    if not args.refetch:
        start = 0
        while True:
            rows = client.table("denki_kb_doc").select("url").range(start, start + 999).execute().data
            done_urls.update(r["url"] for r in rows)
            if len(rows) < 1000:
                break
            start += 1000

    targets = []
    for a in doc["articles"]:
        if src_type.get(a["source"]) == "youtube":
            continue
        if args.source and a["source"] != args.source:
            continue
        if a["url"] in done_urls:
            continue
        targets.append(a)
    if args.limit:
        targets = targets[: args.limit]

    by_host: dict[str, list] = defaultdict(list)
    for a in targets:
        by_host[urlparse(a["url"]).netloc].append(a)
    log(f"取得対象 {len(targets)} 件 / {len(by_host)} サイト（済み {len(done_urls)} 件）")

    counters = {"ok": 0, "ng": 0, "chars": 0}

    def run_host(host: str, items: list) -> None:
        """同じサイトへは1本ずつ・間隔を空けて当てる（相手サーバへの配慮）。"""
        buf = []
        for a in items:
            text, date = extract_fulltext(a["url"])
            if len(text) < MIN_DOC_CHARS:
                # 取れなければ既存索引の冒頭テキストを使う（無いよりまし）
                text = clean(a.get("text") or "")
            if len(text) < MIN_DOC_CHARS:
                counters["ng"] += 1
                continue
            buf.append({
                "source_id": a["source"],
                "source_name": a.get("sourceName") or a["source"],
                "kind": "blog",
                "url": a["url"],
                "title": (a.get("title") or "")[:300] or a["url"],
                "published_on": (date or a.get("date") or None) or None,
                "content": text,
                "char_count": len(text),
                "content_hash": hashlib.sha1(text.encode("utf-8")).hexdigest(),
            })
            counters["ok"] += 1
            counters["chars"] += len(text)
            if len(buf) >= 25:
                client.table("denki_kb_doc").upsert(buf, on_conflict="url").execute()
                buf = []
            time.sleep(0.7)
        if buf:
            client.table("denki_kb_doc").upsert(buf, on_conflict="url").execute()
        log(f"  done {host}: {len(items)} 件処理")

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(run_host, h, items) for h, items in by_host.items()]
        for f in as_completed(futs):
            try:
                f.result()
            except Exception as e:  # noqa: BLE001
                log(f"  host err: {e}")

    log(f"本文取得: 成功 {counters['ok']} / 失敗 {counters['ng']} / 総文字 {counters['chars']:,}")


# ───────────────────────── YouTube 字幕 ─────────────────────────
def _vtt_to_text(path: str) -> str:
    try:
        raw = open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return ""
    lines, seen_last = [], ""
    for ln in raw.splitlines():
        ln = ln.strip()
        if (not ln or ln.startswith("WEBVTT") or "-->" in ln
                or ln.startswith(("Kind:", "Language:", "NOTE"))
                or re.fullmatch(r"\d+", ln)):
            continue
        ln = re.sub(r"<[^>]+>", "", ln)
        ln = re.sub(r"\[[^\]]*\]", "", ln).strip()
        if not ln or ln == seen_last:
            continue
        # 自動字幕はローリング表示で行が重なる。直前行の続きなら差分だけ足す
        if seen_last and ln.startswith(seen_last):
            ln = ln[len(seen_last):].strip()
            if not ln:
                continue
        lines.append(ln)
        seen_last = lines[-1]
    return clean(" ".join(lines))


def fetch_subs(args) -> None:
    import yt_dlp

    with open(INDEX_PATH, encoding="utf-8") as f:
        doc = json.load(f)
    src_type = {s["id"]: s.get("type", "html") for s in doc["sources"]}

    client = sb()
    done_urls = set()
    if not args.refetch:
        rows = client.table("denki_kb_doc").select("url").eq("kind", "youtube").execute().data
        done_urls = {r["url"] for r in rows}

    targets = [a for a in doc["articles"]
               if src_type.get(a["source"]) == "youtube"
               and (not args.source or a["source"] == args.source)
               and a["url"] not in done_urls]
    if args.limit:
        targets = targets[: args.limit]
    log(f"字幕取得対象 {len(targets)} 本（済み {len(done_urls)} 本）")

    tmp = os.path.join(ROOT, ".tmp", "denki_subs")
    os.makedirs(tmp, exist_ok=True)
    ok = ng = 0
    buf = []
    for i, a in enumerate(targets, 1):
        vid = a["url"].split("v=")[-1]
        out = os.path.join(tmp, vid)
        opts = {
            "quiet": True, "no_warnings": True, "skip_download": True, "noprogress": True,
            "writesubtitles": True, "writeautomaticsub": True,
            "subtitleslangs": ["ja", "ja-orig", "ja-JP"],
            "subtitlesformat": "vtt", "outtmpl": out,
            "http_headers": {"Accept-Language": "ja-JP,ja"},
        }
        text, date, title = "", "", a.get("title", "")
        try:
            with yt_dlp.YoutubeDL(opts) as y:
                info = y.extract_info(a["url"], download=True)
            title = info.get("title") or title
            up = info.get("upload_date") or ""
            if len(up) == 8:
                date = f"{up[:4]}-{up[4:6]}-{up[6:]}"
            for f in sorted(os.listdir(tmp)):
                if f.startswith(vid) and f.endswith(".vtt"):
                    text = _vtt_to_text(os.path.join(tmp, f))
                    os.remove(os.path.join(tmp, f))
                    if text:
                        break
            desc = clean(info.get("description") or "")
            if desc:
                text = (text + "\n\n【動画の説明】\n" + desc).strip()
        except Exception as e:  # noqa: BLE001
            log(f"  [{i}] {vid} err: {str(e)[:120]}")

        if len(text) < MIN_DOC_CHARS:
            ng += 1
        else:
            ok += 1
            buf.append({
                "source_id": a["source"],
                "source_name": a.get("sourceName") or a["source"],
                "kind": "youtube",
                "url": a["url"],
                "title": title[:300],
                "published_on": (date or None),
                "content": text,
                "char_count": len(text),
                "content_hash": hashlib.sha1(text.encode("utf-8")).hexdigest(),
            })
        if len(buf) >= 20:
            client.table("denki_kb_doc").upsert(buf, on_conflict="url").execute()
            buf = []
        if i % 25 == 0:
            log(f"  {i}/{len(targets)} 本 (取得 {ok} / 字幕なし {ng})")
        time.sleep(1.2)
    if buf:
        client.table("denki_kb_doc").upsert(buf, on_conflict="url").execute()
    log(f"字幕取得: 成功 {ok} / 字幕なし {ng}")


# ───────────────────────── チャンク＋埋め込み ─────────────────────────
def split_chunks(title: str, text: str) -> list[str]:
    text = clean(text)
    out, i = [], 0
    while i < len(text):
        piece = text[i: i + CHUNK_SIZE]
        if piece.strip():
            out.append(f"{title}\n{piece.strip()}")
        if i + CHUNK_SIZE >= len(text):
            break
        i += CHUNK_SIZE - CHUNK_OVERLAP
    return out


def embed_texts(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    key = os.getenv("GOOGLE_GEMINI_API_KEY")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{EMBED_MODEL}:batchEmbedContents?key={key}")
    payload = {"requests": [{
        "model": f"models/{EMBED_MODEL}",
        "content": {"parts": [{"text": t[:8000]}]},
        "taskType": task_type,
        "outputDimensionality": EMBED_DIM,
    } for t in texts]}
    for attempt in range(6):
        r = requests.post(url, json=payload, timeout=180)
        if r.status_code == 200:
            return [e["values"] for e in r.json()["embeddings"]]
        if r.status_code in (429, 500, 503):
            wait = min(60, 5 * (attempt + 1))
            log(f"    embed {r.status_code} → {wait}s 待機")
            time.sleep(wait)
            continue
        raise RuntimeError(f"embed failed {r.status_code}: {r.text[:300]}")
    raise RuntimeError("embed failed after retries")


def embed_docs(args) -> None:
    client = sb()
    done = set()
    start = 0
    while True:
        rows = client.table("denki_kb_chunk").select("doc_id").range(start, start + 999).execute().data
        done.update(r["doc_id"] for r in rows)
        if len(rows) < 1000:
            break
        start += 1000

    docs, start = [], 0
    while True:
        q = client.table("denki_kb_doc").select("id,title,content,source_id")
        if args.source:
            q = q.eq("source_id", args.source)
        rows = q.range(start, start + 499).execute().data
        docs.extend(rows)
        if len(rows) < 500:
            break
        start += 500
    docs = [d for d in docs if d["id"] not in done]
    if args.limit:
        docs = docs[: args.limit]
    log(f"埋め込み対象 {len(docs)} 件（済み {len(done)} 件）")

    pending: list[dict] = []
    total = 0

    def flush() -> None:
        nonlocal pending, total
        while pending:
            batch, pending = pending[:EMBED_BATCH], pending[EMBED_BATCH:]
            vecs = embed_texts([b["content"] for b in batch])
            for b, v in zip(batch, vecs):
                b["embedding"] = v
            client.table("denki_kb_chunk").upsert(batch, on_conflict="doc_id,chunk_index").execute()
            total += len(batch)
            log(f"  断片 {total} 件 投入")

    for n, d in enumerate(docs, 1):
        for idx, c in enumerate(split_chunks(d["title"], d["content"])):
            pending.append({"doc_id": d["id"], "chunk_index": idx, "content": c})
        if len(pending) >= EMBED_BATCH * 4:
            flush()
        if n % 200 == 0:
            log(f"  {n}/{len(docs)} 記事")
    flush()
    log(f"埋め込み完了: 断片 {total} 件")


def stats(_args) -> None:
    client = sb()
    docs, start = [], 0
    while True:
        rows = client.table("denki_kb_doc").select("source_id,source_name,kind,char_count").range(start, start + 999).execute().data
        docs.extend(rows)
        if len(rows) < 1000:
            break
        start += 1000
    n_chunk = client.table("denki_kb_chunk").select("id", count="exact").limit(1).execute().count
    agg: dict[str, list] = defaultdict(lambda: [0, 0, "", ""])
    for d in docs:
        a = agg[d["source_id"]]
        a[0] += 1
        a[1] += d.get("char_count") or 0
        a[2] = d.get("source_name") or ""
        a[3] = d.get("kind") or ""
    log(f"{'source':18s} {'kind':8s} {'件数':>6s} {'総文字':>10s} {'平均':>7s}")
    for sid, (n, ch, name, kind) in sorted(agg.items(), key=lambda x: -x[1][1]):
        log(f"{sid:18s} {kind:8s} {n:6d} {ch:10,d} {ch//max(n,1):7d}")
    log(f"合計: 記事 {len(docs):,} 件 / {sum(d.get('char_count') or 0 for d in docs):,} 字 / 断片 {n_chunk:,} 件")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--fetch", action="store_true")
    p.add_argument("--subs", action="store_true")
    p.add_argument("--embed", action="store_true")
    p.add_argument("--stats", action="store_true")
    p.add_argument("--source")
    p.add_argument("--limit", type=int)
    p.add_argument("--refetch", action="store_true")
    args = p.parse_args()

    if args.fetch:
        fetch_blogs(args)
    if args.subs:
        fetch_subs(args)
    if args.embed:
        embed_docs(args)
    if args.stats or not (args.fetch or args.subs or args.embed):
        stats(args)


if __name__ == "__main__":
    main()
