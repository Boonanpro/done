"""電気主任技術者応援サイト（denkiouen.com）の検索対策「3つのエンジン」。

2026-09-10 の説明動画で本人が承認した内容をそのまま実装したもの。

  エンジン1  毎日1ページ増やす
      検索されているのに、うちに答えが無い言葉を拾う（Google の検索候補＋Search Console）
      → サイトが集めた記事・動画（denki_kb_*）から実例を集める
      → 結論から書いた1ページにまとめる（実例には必ず出典リンク）
      → 出典に無い話が混ざっていないか別のAIが審査し、通ったものだけ公開（/guides/<slug>）
  エンジン2  順位を磨く
      Search Console で「あと少しで1位」の言葉を1つ選ぶ → 上位ページと比べて足りない論点を
      サイトの資料で足す → 7日待って実測で判定（悪くなったら元に戻す）→ 1位まで繰り返す
  エンジン3  AIに推薦させる
      新しいページを IndexNow（Bing ほか）へ即通知 → 月1回、ChatGPT・Gemini・Claude に
      10問聞いて、うちのサイトが引用されるかを記録する

使い方:
  python scripts/denki_seo_engines.py daily            毎日の定期実行（判定→新ページ→磨く→通知）
  python scripts/denki_seo_engines.py new-page         エンジン1だけ（--keyword で語を指定可、--dry-run で保存しない）
  python scripts/denki_seo_engines.py polish           エンジン2だけ
  python scripts/denki_seo_engines.py evaluate         エンジン2の7日判定だけ
  python scripts/denki_seo_engines.py keywords         検索候補の在庫を作り直す
  python scripts/denki_seo_engines.py indexnow URL...  IndexNow に通知
  python scripts/denki_seo_engines.py ai-check         エンジン3の月次チェック
  python scripts/denki_seo_engines.py weekly-list      直近7日に出た・直したページの一覧を書き出す

文章を書く・審査する AI は Claude Code CLI（定額 Max プラン）。記事の意味検索だけ既存の
Gemini 埋め込み（AI一次回答と同じ仕組み）を使う。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from denki_seo import OUT_DIR, SITE_URL, SITEMAP_URL, _env, _query, _service, log  # noqa: E402

ORIGIN = "https://denkiouen.com"
STATE_DIR = OUT_DIR / "state"
ACTIVITY = OUT_DIR / "activity.jsonl"
KEYWORDS_PATH = STATE_DIR / "keywords.json"
AI_QUESTIONS_PATH = STATE_DIR / "ai_questions.json"
AI_CHECK_DIR = OUT_DIR / "ai_citations"

# IndexNow の鍵。成果物側の /<鍵>.txt（artifacts/denki-knowledge/<鍵>.txt/route.ts）と同じ値。
INDEXNOW_KEY = "d3nk10u3n5e0a7c4b1f96e28d05c3a7b"

# 手書きの特集。自動ページの slug と衝突させない
RESERVED_SLUGS = {"dokuritsu", "haikyu-jiko", "nenji-tenken", "index", "new", "api"}
STATIC_GUIDES = [
    {"slug": "haikyu-jiko", "title": "波及事故はなぜ起きるのか", "keyword": "波及事故"},
    {"slug": "dokuritsu", "title": "電気管理技術者として独立する", "keyword": "電気管理技術者 独立"},
    {"slug": "nenji-tenken", "title": "年次点検（停電作業）で読んでおきたい記事まとめ", "keyword": "年次点検"},
]

EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 768
WRITER_MODEL = "opus"


# ================================================================ 共通
def jst_today() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=9)).date()


def parse_ts(s: str) -> datetime:
    """Supabase の時刻（小数秒の桁数がまちまち）を読む。Python 3.10 の fromisoformat は3桁/6桁しか読めない。"""
    m = re.match(r"^(.*?T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$", s.strip())
    if not m:
        return datetime.fromisoformat(s)
    frac = (m.group(2) or "0")[:6].ljust(6, "0")
    tz = m.group(3) or "+00:00"
    tz = "+00:00" if tz == "Z" else (tz if ":" in tz else tz[:3] + ":" + tz[3:])
    return datetime.fromisoformat(f"{m.group(1)}.{frac}{tz}")


def activity(kind: str, **data) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rec = {"at": datetime.now(timezone.utc).isoformat(), "kind": kind, **data}
    with ACTIVITY.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _sb() -> tuple[str, str]:
    env = _env()
    url = env.get("SUPABASE_URL") or env.get("NEXT_PUBLIC_SUPABASE_URL")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_SERVICE_KEY") or env.get("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("Supabase の接続情報が .env にありません")
    return url.rstrip("/"), key


def sb_request(method: str, path: str, body=None, prefer: str | None = None, timeout: int = 60):
    url, key = _sb()
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{url}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        raw = res.read()
    return json.loads(raw) if raw else None


def http_json(url: str, body=None, headers=None, timeout: int = 60, method: str | None = None):
    h = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 denkiouen-seo"}
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=h, method=method or ("POST" if data else "GET"))
    with urllib.request.urlopen(req, timeout=timeout) as res:
        raw = res.read()
    return json.loads(raw.decode("utf-8")) if raw else None


def extract_json(text: str):
    """AIの返答から JSON を取り出す（```json ブロック優先、無ければ最初の { から最後の } まで）。"""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", text, re.S)
    cand = m.group(1) if m else None
    if cand is None:
        s, e = text.find("{"), text.rfind("}")
        if s < 0 or e <= s:
            return None
        cand = text[s : e + 1]
    try:
        return json.loads(cand)
    except json.JSONDecodeError:
        # 末尾カンマ等の軽い崩れだけ救う
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", cand))
        except json.JSONDecodeError:
            return None


def claude(prompt: str, timeout: int = 900, model: str = WRITER_MODEL) -> str | None:
    """Claude Code CLI（定額 Max プラン）で1回だけ生成する。"""
    from app.agent.cli_runner import run_oneshot_cli

    for attempt in range(2):
        out = run_oneshot_cli(prompt, model=model, timeout=timeout)
        if out:
            return out
        log(f"claude oneshot failed (attempt {attempt + 1})")
        time.sleep(20)
    _log_claude_failure_reason(model)
    return None


def _log_claude_failure_reason(model: str) -> None:
    """失敗の理由を残す。run_oneshot_cli は異常終了時に標準出力を捨てるが、
    CLI は利用上限・ログイン切れの文面を標準出力へ出すため、短い試し呼び出しで拾う。"""
    import subprocess

    try:
        from app.agent.cli_runner import _resolve_claude_cli

        claude_cmd, cli_js = _resolve_claude_cli()
        if not claude_cmd:
            log("claude failure reason: CLI が見つからない")
            return
        cmd = ([claude_cmd, cli_js] if cli_js else [claude_cmd]) + [
            "-p", "ping", "--output-format", "text", "--model", model,
        ]
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "ANTHROPIC_API_KEY")}
        proc = subprocess.run(
            cmd, input="", capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, timeout=120,
        )
        text = " ".join(((proc.stdout or "") + " " + (proc.stderr or "")).split())[:400]
        log(f"claude failure reason: exit={proc.returncode} output={text!r}")
    except Exception as e:  # 診断の失敗で本処理を止めない
        log(f"claude failure reason: 診断できず {e!r}")


def claude_json(prompt: str, timeout: int = 900):
    for attempt in range(2):
        out = claude(prompt, timeout=timeout)
        data = extract_json(out or "")
        if data is not None:
            return data
        log(f"claude json parse failed (attempt {attempt + 1}): {(out or '')[:200]!r}")
    return None


# ================================================================ 知識ベース（サイトが集めた記事・動画）
def embed(texts: list[str], task_type: str = "RETRIEVAL_QUERY") -> list[list[float]]:
    key = _env().get("GOOGLE_GEMINI_API_KEY")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{EMBED_MODEL}:batchEmbedContents?key={key}"
    out: list[list[float]] = []
    for i in range(0, len(texts), 50):
        batch = texts[i : i + 50]
        payload = {
            "requests": [
                {
                    "model": f"models/{EMBED_MODEL}",
                    "content": {"parts": [{"text": t[:8000]}]},
                    "taskType": task_type,
                    "outputDimensionality": EMBED_DIM,
                }
                for t in batch
            ]
        }
        for attempt in range(6):
            try:
                res = http_json(url, payload, timeout=180)
                out.extend(e["values"] for e in res["embeddings"])
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 503) and attempt < 5:
                    time.sleep(min(60, 5 * (attempt + 1)))
                    continue
                raise
    return out


def kb_search_vec(vec: list[float], count: int = 12, min_sim: float = 0.35) -> list[dict]:
    return (
        sb_request(
            "POST",
            "/rest/v1/rpc/denki_kb_search",
            {"p_query_embedding": vec, "p_match_count": count, "p_min_similarity": min_sim},
        )
        or []
    )


def kb_search(query: str, count: int = 12, min_sim: float = 0.35) -> list[dict]:
    return kb_search_vec(embed([query])[0], count, min_sim)


def gather_sources(queries: list[str], max_docs: int = 16, per_doc: int = 2, min_sim: float = 0.68) -> list[dict]:
    """複数の言い換えで検索し、記事単位にまとめた資料を返す（類似度の高い順）。"""
    vecs = embed(queries)
    by_doc: dict[int, dict] = {}
    for q, v in zip(queries, vecs):
        for h in kb_search_vec(v, count=14, min_sim=min_sim):
            d = by_doc.setdefault(
                h["doc_id"],
                {
                    "doc_id": h["doc_id"],
                    "title": h["title"],
                    "url": h["url"],
                    "source_name": h["source_name"],
                    "kind": h["kind"],
                    "published_on": h.get("published_on"),
                    "best": 0.0,
                    "chunks": {},
                },
            )
            d["best"] = max(d["best"], h["similarity"])
            if h["chunk_id"] not in d["chunks"]:
                d["chunks"][h["chunk_id"]] = (h["similarity"], h["content"])
    docs = sorted(by_doc.values(), key=lambda d: -d["best"])[:max_docs]
    for d in docs:
        top = sorted(d["chunks"].values(), key=lambda x: -x[0])[:per_doc]
        d["excerpt"] = "\n…\n".join(c for _, c in top)
        del d["chunks"]
    return docs


def sources_block(sources: list[dict]) -> str:
    blocks = []
    for i, s in enumerate(sources, 1):
        kind = "YouTube動画の字幕（自動文字起こし）" if s["kind"] == "youtube" else "ブログ記事"
        blocks.append(
            f"[{i}] {s['title']}\n種別: {kind} / 発信者: {s['source_name']}"
            f"{' / ' + str(s['published_on']) if s.get('published_on') else ''}\n{s['excerpt']}"
        )
    return "\n\n---\n\n".join(blocks)


# ================================================================ 検索候補の在庫（エンジン1の入口）
SEEDS = [
    "電気主任技術者", "電気管理技術者", "電気主任技術者 外部委託", "電気保安法人", "保安規程",
    "年次点検", "月次点検", "竣工検査 高圧", "キュービクル", "キュービクル 点検", "高圧受電設備",
    "絶縁抵抗測定", "絶縁抵抗 高圧", "絶縁抵抗 低い", "接地抵抗測定", "漏れ電流 測定", "Ior",
    "Igr", "絶縁監視装置", "地絡継電器", "地絡方向継電器", "過電流継電器", "継電器試験",
    "ZPD", "PAS", "SOG", "UGS", "VCB", "LBS 高圧", "高圧ケーブル", "高圧ケーブル 耐圧試験",
    "水トリー", "変圧器 絶縁油", "進相コンデンサ", "直列リアクトル", "高調波 対策", "デマンド 監視",
    "力率 改善", "太陽光発電 高圧 保安", "太陽光 絶縁抵抗", "非常用発電機 点検", "蓄電池 点検",
    "波及事故", "停電作業", "検電器 高圧", "短絡接地器具", "感電事故", "キュービクル 小動物",
    "電気事故報告", "電験三種 実務", "電気管理技術者 独立", "電気管理技術者 年収", "保安協会",
    "漏電遮断器", "漏電 調査", "耐圧試験", "保護協調", "受電設備 更新", "PCB 絶縁油",
    "高圧 地絡", "トラッキング", "避雷器", "電力需給用計器", "SPD", "B種接地",
]
DROP_WORDS = ("求人", "募集", "転職", "過去問", "講習", "テキスト", "参考書", "通信講座", "ユーキャン", "英語", "とは 英語")


def _suggest(q: str) -> list[str]:
    u = "https://suggestqueries.google.com/complete/search?" + urllib.parse.urlencode(
        {"client": "firefox", "hl": "ja", "ie": "utf-8", "oe": "utf-8", "q": q}
    )
    try:
        raw = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=15).read()
        data = json.loads(raw.decode("utf-8", errors="replace"))
        return [s for s in data[1] if isinstance(s, str)]
    except Exception as e:  # noqa: BLE001
        log(f"suggest failed {q!r}: {e}")
        return []


def _norm_kw(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip().lower()


def load_keywords() -> dict:
    if KEYWORDS_PATH.exists():
        return json.loads(KEYWORDS_PATH.read_text(encoding="utf-8"))
    return {"refreshed_at": None, "items": {}}


def save_keywords(pool: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    KEYWORDS_PATH.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")


def _gsc_queries(days: int = 28) -> list[dict]:
    try:
        svc = _service()
        end = date.today() - timedelta(days=3)
        rows = _query(svc, end - timedelta(days=days - 1), end, ["query", "page"], row_limit=1000)
        return [
            {
                "query": r["keys"][0],
                "page": r["keys"][1],
                "clicks": r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "position": r.get("position", 0),
            }
            for r in rows
        ]
    except Exception as e:  # noqa: BLE001
        log(f"gsc query failed: {e}")
        return []


def cmd_keywords(args=None) -> dict:
    """検索候補を集め、サイトの資料でどこまで語れるか（関連記事の数）を測って在庫にする。"""
    pool = load_keywords()
    items: dict = pool.get("items", {})
    found: dict[str, str] = {}
    for seed in SEEDS:
        for q in (seed, seed + " "):
            for s in _suggest(q):
                k = _norm_kw(s)
                if len(k) < 3 or any(w in k for w in DROP_WORDS):
                    continue
                found.setdefault(k, "google_suggest")
            time.sleep(0.4)
    # Search Console に出ている語（表示されているのに専用ページが無い＝最優先）
    for r in _gsc_queries():
        k = _norm_kw(r["query"])
        if "/guides/" in r["page"]:
            continue
        found[k] = "search_console"
    new = [k for k in found if k not in items]
    log(f"keywords: suggest/gsc={len(found)} new={len(new)} pool={len(items)}")
    if new:
        vecs = embed(new)
        for k, v in zip(new, vecs):
            # 無関係な語でも 0.62〜0.66 は出る（実測）。0.72 以上を「関係がある記事」と数える
            hits = kb_search_vec(v, count=15, min_sim=0.72)
            docs = {}
            for h in hits:
                docs.setdefault(h["doc_id"], (h["similarity"], h["title"]))
            top = sorted(docs.values(), key=lambda x: -x[0])
            items[k] = {
                "keyword": k,
                "origin": found[k],
                "status": "new",
                "docs": len(top),
                "best": round(top[0][0], 3) if top else 0,
                "top_titles": [t for _, t in top[:3]],
                "added": jst_today().isoformat(),
            }
    for k, src in found.items():
        if k in items and src == "search_console":
            items[k]["origin"] = "search_console"
    pool = {"refreshed_at": datetime.now(timezone.utc).isoformat(), "items": items}
    save_keywords(pool)
    usable = [i for i in items.values() if i["status"] == "new" and i["docs"] >= 4]
    log(f"keywords saved: total={len(items)} usable={len(usable)}")
    return pool


# ================================================================ 解説ページ（DB）
def list_guides(status: str | None = "published") -> list[dict]:
    q = "/rest/v1/denki_seo_guide?select=slug,keyword,title,description,revision,updated_at,published_at,status"
    if status:
        q += f"&status=eq.{status}"
    return sb_request("GET", q + "&order=published_at.desc&limit=1000") or []


def get_guide(slug: str) -> dict | None:
    rows = sb_request("GET", f"/rest/v1/denki_seo_guide?select=*&slug=eq.{urllib.parse.quote(slug)}&limit=1") or []
    return rows[0] if rows else None


PAGE_FIELDS = ("title", "description", "answer", "sections", "checklist", "faq")


def _page_text_fields(page: dict) -> list[str]:
    out = [page.get("title", ""), page.get("description", ""), page.get("answer", "")]
    for s in page.get("sections", []):
        out.append(s.get("heading", ""))
        out.extend(s.get("paragraphs", []))
    out.extend(page.get("checklist", []))
    for f in page.get("faq", []):
        out.extend([f.get("q", ""), f.get("a", "")])
    return out


def _map_text(page: dict, fn) -> dict:
    p = dict(page)
    for k in ("title", "description", "answer"):
        p[k] = fn(p.get(k, ""))
    p["sections"] = [
        {"heading": fn(s.get("heading", "")), "paragraphs": [fn(x) for x in s.get("paragraphs", [])]}
        for s in page.get("sections", [])
    ]
    p["checklist"] = [fn(x) for x in page.get("checklist", [])]
    p["faq"] = [{"q": fn(f.get("q", "")), "a": fn(f.get("a", ""))} for f in page.get("faq", [])]
    return p


CITE_RE = re.compile(r"\[(\d{1,2})\]")


def finalize_citations(page: dict, sources: list[dict]) -> tuple[dict, list[dict]]:
    """本文で実際に使った出典だけを、初出順に 1,2,3… と振り直す。存在しない番号は消す。"""
    order: list[int] = []
    for t in _page_text_fields(page):
        for m in CITE_RE.finditer(t):
            n = int(m.group(1))
            if 1 <= n <= len(sources) and n not in order:
                order.append(n)
    remap = {old: new for new, old in enumerate(order, 1)}

    def fix(t: str) -> str:
        t = CITE_RE.sub(lambda m: f"[{remap[int(m.group(1))]}]" if int(m.group(1)) in remap else "", t)
        t = re.sub(r"(\[\d+\])(?:\1)+", r"\1", t)  # 同じ番号の重複
        t = re.sub(r"\*\*|__|^#+\s*", "", t)  # 記号装飾は表示が崩れるので落とす
        return t.strip()

    page = _map_text(page, fix)
    cites = []
    for old in order:
        s = sources[old - 1]
        cites.append(
            {
                "n": remap[old],
                "title": s["title"],
                "url": s["url"],
                "source_name": s["source_name"],
                "kind": s["kind"],
                # 日付の無い記事は取り込み時に 2000-01-01 が入っているので、日付なし扱いにする
                "published_on": s.get("published_on") if str(s.get("published_on") or "") >= "2005-01-01" else None,
            }
        )
    return page, cites


def _plain(t: str) -> str:
    t = CITE_RE.sub("", t)
    return re.sub(r"[\s　、。「」『』（）()・:：,.，．!！?？\-ー]", "", unicodedata.normalize("NFKC", t))


def verbatim_issues(page: dict, sources: list[dict], n: int = 28) -> list[dict]:
    """資料の文章を n 字以上そのまま書き写した箇所を探す（言い換え漏れの機械チェック）。"""
    grams = set()
    for s in sources:
        p = _plain(s.get("excerpt", ""))
        for i in range(0, max(0, len(p) - n + 1)):
            grams.add(p[i : i + n])
    issues = []
    for t in _page_text_fields(page):
        p = _plain(t)
        for i in range(0, max(0, len(p) - n + 1)):
            if p[i : i + n] in grams:
                issues.append({"type": "D", "quote": t[:120], "problem": f"資料の文章を{n}字以上そのまま使っている", "fix": "自分の言葉で言い換える"})
                break
    return issues


def structure_issues(page: dict) -> list[dict]:
    issues = []
    if not (8 <= len(page.get("title", "")) <= 40):
        issues.append({"type": "E", "quote": page.get("title", ""), "problem": "題名の長さが不適切", "fix": "32字前後にする"})
    if not (50 <= len(page.get("description", "")) <= 160):
        issues.append({"type": "E", "quote": page.get("description", ""), "problem": "説明文の長さが不適切", "fix": "80〜120字にする"})
    if len(page.get("sections", [])) < 3:
        issues.append({"type": "E", "quote": "", "problem": "本文の見出しが3つ未満", "fix": "3〜6個にする"})
    body = "".join(_page_text_fields(page))
    if len(set(CITE_RE.findall(body))) < 3:
        issues.append({"type": "A", "quote": "", "problem": "出典の使用が3件未満", "fix": "資料の実例を出典番号つきで使う"})
    return issues


# ---------------------------------------------------------------- 文章を書く・審査する
WRITE_RULES = """絶対に守ること:
1. 事実・数値・手順・現場の事例は、資料に書かれていることだけを使い、その文の末尾に [3] のように出典番号を付ける。複数なら [2][5]。
2. 資料に無いことを、資料にあるかのように書かない。用語の意味など一般的な前提を補う文は「一般に」で始め、出典番号は付けない。一般論は全体の2割以下。一般論として数値・基準値・法令の条文番号を書かない。
3. 資料の文章を書き写さない。自分の言葉で要約する。資料と同じ言い回しを20字以上続けない。
4. 停電作業・検電・接地・活線近接・波及事故など安全に関わることは断定しない。現場の手順書と有資格者の判断に従うよう書く。
5. YouTube字幕は自動文字起こしで専門用語の誤変換がある（例: 竣工検査→進行検査）。文脈から正しい語に直して扱う。
6. 資料どうしで意見や数字が違うときは、両方を示し「現場や設備によって判断が分かれる」と書く。
7. 本文にブログ名・人名は書かない（「ある技術者の記録では」のようにぼかし、出典番号で示す）。
8. ** や ## などの記号装飾は使わない。丁寧語（です・ます）で、実務者向けに簡潔に。前置きや挨拶は書かない。"""

PAGE_SCHEMA = """{
  "title": "検索語を自然に含む題名（32字前後、最大40字）",
  "description": "検索結果に出る説明文（80〜120字）。読めば結論の方向が分かるように",
  "answer": "冒頭の結論（2〜4文）。検索した人が一番知りたい答えを1文目に。出典番号つき",
  "sections": [{"heading": "見出し", "paragraphs": ["段落（2〜5文）", "..."]}],
  "checklist": ["現場で確かめること（短文、3〜6項目）"],
  "faq": [{"q": "検索されそうな関連質問", "a": "2〜3文の答え（出典番号つき）"}]
}"""


def write_page(keyword: str, angle: str, sources: list[dict]) -> dict | None:
    prompt = f"""あなたは「電気主任技術者応援サイト」(denkiouen.com) の解説ページを書く編集者です。
読み手は電気主任技術者・電気管理技術者、これから目指す人、高圧設備を持つ事業者です。
Googleで「{keyword}」と検索して来た人のためのページを書きます。
ページの切り口: {angle}

下の「資料」は、このサイトが集めている現役の電気管理技術者のブログ記事・YouTube字幕の抜粋です。
このサイトの価値は、教科書や一般的な解説サイトに無い「現場で実際に起きたこと・やっていること」です。
資料の実例を具体的に使ってください。

{WRITE_RULES}

構成:
- sections は 3〜6 個。検索した人が知りたい順に並べる。最低1つは現場の実例（何が起きて、どう対応したか）を中心にした見出しにする
- faq は 3〜5 個
- 全体で 2,000〜3,500 字

次の形の JSON だけを ```json で囲んで返してください。
{PAGE_SCHEMA}

# 資料
{sources_block(sources)}
"""
    return claude_json(prompt)


def review_page(keyword: str, page: dict, sources: list[dict]) -> dict | None:
    prompt = f"""あなたは技術系サイトの公開前審査の担当です。検索語「{keyword}」向けの「原稿」を「資料」と突き合わせて、公開してよいか審査してください。
原稿の [番号] は資料の番号です。

審査基準:
A. 出典番号が付いた文の内容が、その番号の資料に実際に書かれているか（数値・手順・事例の取り違え、誇張、資料に無い一般化）
B. 出典番号の無い文に、一般論の範囲を超えた具体的な数値・基準値・法令条文・事例が書かれていないか
C. 安全面で危険な断定、誤った手順の推奨が無いか
D. 資料の文章をほぼそのまま書き写した箇所が無いか
E. 題名・結論が検索語に対して的外れでないか

言い回しの好みなど軽微なことは挙げないでください。本当に直すべき点だけを挙げます。
次の JSON だけを ```json で囲んで返してください。issues が空のときだけ ok を true にします。
{{"ok": true, "issues": [{{"type": "A|B|C|D|E", "quote": "原稿の該当文をそのまま", "problem": "何が問題か", "fix": "削除または書き換え案"}}]}}

# 原稿
{json.dumps({k: page.get(k) for k in PAGE_FIELDS}, ensure_ascii=False, indent=1)}

# 資料
{sources_block(sources)}
"""
    return claude_json(prompt, timeout=900)


def revise_page(keyword: str, page: dict, issues: list[dict], sources: list[dict]) -> dict | None:
    prompt = f"""検索語「{keyword}」向けの解説ページの原稿に、審査で次の指摘がありました。指摘された箇所だけを直し、
それ以外はできるだけそのまま残した完成版を返してください。直せない文は削除して構いません。

{WRITE_RULES}

# 指摘
{json.dumps(issues, ensure_ascii=False, indent=1)}

# 原稿
{json.dumps({k: page.get(k) for k in PAGE_FIELDS}, ensure_ascii=False, indent=1)}

# 資料
{sources_block(sources)}

同じ形の JSON だけを ```json で囲んで返してください。
{PAGE_SCHEMA}
"""
    return claude_json(prompt)


def _valid_page(p) -> bool:
    return (
        isinstance(p, dict)
        and all(isinstance(p.get(k), str) and p.get(k) for k in ("title", "description", "answer"))
        and isinstance(p.get("sections"), list)
        and all(isinstance(s, dict) and s.get("heading") and isinstance(s.get("paragraphs"), list) for s in p["sections"])
        and isinstance(p.get("checklist", []), list)
        and isinstance(p.get("faq", []), list)
    )


def write_and_review(keyword: str, angle: str, sources: list[dict], draft: dict | None = None) -> tuple[dict | None, dict]:
    """書く → 機械チェック＋AI審査 → 指摘があれば直す → もう一度審査。最大2回直す。"""
    page = draft or write_page(keyword, angle, sources)
    if not _valid_page(page):
        return None, {"ok": False, "reason": "原稿の形が崩れていた"}
    rounds = []
    for rnd in range(3):
        mech = structure_issues(page) + verbatim_issues(page, sources)
        rev = review_page(keyword, page, sources) or {"ok": False, "issues": [{"type": "X", "quote": "", "problem": "審査の返答を読めなかった", "fix": ""}]}
        issues = mech + [i for i in rev.get("issues", []) if isinstance(i, dict)]
        rounds.append({"round": rnd + 1, "issues": issues})
        log(f"  review round {rnd + 1}: issues={len(issues)} (mechanical={len(mech)})")
        if not issues:
            return page, {"ok": True, "rounds": rounds}
        if rnd == 2:
            # 2回直しても残った指摘は、指摘された文そのものを削る（削るだけなら新しい誤りは入らない）
            trimmed = drop_flagged(page, issues)
            if trimmed and not structure_issues(trimmed) and not verbatim_issues(trimmed, sources):
                rounds.append({"round": "trim", "removed": [i.get("quote", "")[:80] for i in issues]})
                log(f"  指摘された {len(issues)} 文を削って通す")
                return trimmed, {"ok": True, "rounds": rounds, "trimmed": True}
            break
        fixed = revise_page(keyword, page, issues, sources)
        if not _valid_page(fixed):
            break
        page = fixed
    return None, {"ok": False, "rounds": rounds, "reason": "審査を通らなかった"}


def drop_flagged(page: dict, issues: list[dict]) -> dict | None:
    """指摘の quote を含む文を本文から取り除く。題名・結論に関わる指摘や、場所が特定できない指摘があれば諦める。"""
    quotes = []
    for i in issues:
        q = _plain(i.get("quote", ""))
        if len(q) < 8 or i.get("type") == "E":
            return None
        quotes.append(q)
    found = {q: False for q in quotes}

    def cut(t: str) -> str:
        sents = re.split(r"(?<=[。！？])", t)
        keep = []
        for s in sents:
            ps = _plain(s)
            hit = [q for q in quotes if ps and (q in ps or ps in q or (len(ps) > 15 and ps[:15] in q))]
            if hit:
                for q in hit:
                    found[q] = True
                continue
            keep.append(s)
        return "".join(keep).strip()

    p = dict(page)
    for k in ("title", "description", "answer"):
        if any(q in _plain(p.get(k, "")) for q in quotes):
            return None  # 題名・説明・結論は削れない
    p["sections"] = [
        {"heading": s["heading"], "paragraphs": [x for x in (cut(y) for y in s.get("paragraphs", [])) if x]}
        for s in page.get("sections", [])
    ]
    p["sections"] = [s for s in p["sections"] if s["paragraphs"]]
    p["checklist"] = [x for x in (cut(y) for y in page.get("checklist", [])) if x]
    p["faq"] = [f for f in ({"q": f.get("q", ""), "a": cut(f.get("a", ""))} for f in page.get("faq", [])) if f["a"]]
    if not all(found.values()):
        return None
    return p


# ---------------------------------------------------------------- エンジン1: 言葉を選ぶ
def pick_keyword(pool: dict, guides: list[dict], exclude: set[str]) -> dict | None:
    items = [
        i for i in pool["items"].values()
        if i["status"] == "new" and i["docs"] >= 4 and i["keyword"] not in exclude
    ]
    # Search Console に出ている語を最優先、次に資料の厚い語
    items.sort(key=lambda i: (i["origin"] != "search_console", -i["docs"], -i["best"]))
    cands = items[:60]
    if not cands:
        return None
    existing = [f"- {g['title']}（狙った語: {g['keyword']}）" for g in STATIC_GUIDES + guides]
    lines = [
        f"- {c['keyword']} | 出どころ: {'Search Consoleで表示あり' if c['origin'] == 'search_console' else 'Googleの検索候補'} | 関連記事 {c['docs']}本 | 近い記事: {' / '.join(c['top_titles'])}"
        for c in cands
    ]
    prompt = f"""あなたは「電気主任技術者応援サイト」(denkiouen.com) の編集長です。
このサイトは、全国の現役電気管理技術者のブログ・YouTube 約3,600件を集め、現場の実務知識を探せるようにしています。
毎日1ページ、検索されている言葉に答える解説ページを追加しています。

下の候補は、実際に Google で検索されている言葉（検索候補・Search Console）と、サイト内の関連記事の数です。
今日作る1語を選んでください。

選ぶ基準:
1. 検索する人の知りたいことがはっきりしていて、1ページで答えられる
2. サイトの記事・動画で「現場の実例」を具体的に語れる（関連記事が多く、近い記事の題名が合っている）
3. 既存ページと内容が重ならない
4. 避ける: 試験問題の解き方、求人・転職、特定の会社や製品の評判、最新の法改正の正確さが命の話題、意味が曖昧な語
5. 同じ候補が表記違いで並んでいたら、より検索されそうな自然な表記を選ぶ

# 既存のページ
{chr(10).join(existing)}

# 候補
{chr(10).join(lines)}

次の JSON だけを ```json で囲んで返してください。
{{"keyword": "候補の中から1語（そのまま）", "angle": "検索した人が知りたいことと、このページの切り口（1〜2文）", "slug": "英小文字・数字・ハイフンのURL用の名前（例: zetsuen-teikou-hikui）", "queries": ["サイト内の記事を探すための言い換え・関連質問を5個"], "reason": "選んだ理由（1文）"}}
"""
    choice = claude_json(prompt, timeout=600)
    if not choice or not choice.get("keyword"):
        return None
    k = _norm_kw(choice["keyword"])
    if k not in pool["items"]:
        # 表記ゆれで返ってきた場合は候補の中から一番近いものに寄せる
        match = next((c for c in cands if _norm_kw(c["keyword"]).replace(" ", "") == k.replace(" ", "")), None)
        if not match:
            log(f"picked keyword not in pool: {choice['keyword']!r}")
            return None
        k = match["keyword"]
    choice["keyword"] = k
    return choice


def _slugify(raw: str, taken: set[str]) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", (raw or "").lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)[:60].strip("-")
    if not s or s in RESERVED_SLUGS:
        s = "guide-" + hashlib.sha1((raw or str(time.time())).encode()).hexdigest()[:8]
    base, i = s, 2
    while s in taken or s in RESERVED_SLUGS:
        s = f"{base}-{i}"
        i += 1
    return s


def cmd_new_page(args) -> dict | None:
    pool = load_keywords()
    refreshed = pool.get("refreshed_at")
    stale = not refreshed or (datetime.now(timezone.utc) - parse_ts(refreshed)).days >= 14
    usable = [i for i in pool["items"].values() if i["status"] == "new" and i["docs"] >= 4]
    if stale or len(usable) < 20:
        pool = cmd_keywords()
    guides = list_guides(status=None)
    taken = {g["slug"] for g in guides}

    tried: set[str] = set()
    for attempt in range(2):
        if getattr(args, "keyword", None):
            k = _norm_kw(args.keyword)
            choice = {"keyword": k, "angle": getattr(args, "angle", None) or f"「{k}」で検索した実務者が知りたいことに、現場の実例で答える", "slug": getattr(args, "slug", None) or "", "queries": [k], "reason": "指定"}
        else:
            choice = pick_keyword(pool, [g for g in guides if g["status"] == "published"], tried)
        if not choice:
            log("new-page: 候補が選べなかった")
            return None
        kw = choice["keyword"]
        tried.add(kw)
        log(f"new-page: keyword={kw!r} angle={choice.get('angle')!r}")
        queries = [kw] + [q for q in choice.get("queries", []) if isinstance(q, str)][:6]
        sources = gather_sources(queries)
        if len(sources) < 4:
            log(f"  資料が少ない（{len(sources)}件）→ 見送り")
            if kw in pool["items"]:
                pool["items"][kw]["status"] = "no_evidence"
                save_keywords(pool)
            if getattr(args, "keyword", None):
                return None
            continue
        page, check = write_and_review(kw, choice.get("angle", ""), sources)
        if not page:
            log(f"  審査を通らず見送り: {check.get('reason')}")
            if kw in pool["items"]:
                pool["items"][kw]["status"] = "rejected"
                pool["items"][kw]["note"] = check.get("reason")
                save_keywords(pool)
            activity("guide_rejected", keyword=kw, reason=check.get("reason"))
            if getattr(args, "keyword", None):
                return None
            continue
        page, cites = finalize_citations(page, sources)
        slug = _slugify(choice.get("slug", ""), taken)
        row = {
            "slug": slug,
            "keyword": kw,
            **{k: page.get(k) for k in PAGE_FIELDS},
            "citations": cites,
            "status": "published",
            "check_result": check,
            "meta": {
                "angle": choice.get("angle"),
                "reason": choice.get("reason"),
                "origin": pool["items"].get(kw, {}).get("origin", "manual"),
                "queries": queries,
                # 後で磨く・審査し直すときに同じ資料を使えるよう、使った抜粋を残す（画面には出さない）
                "sources": [{k: s.get(k) for k in ("title", "url", "source_name", "kind", "published_on", "excerpt")} for s in sources],
            },
        }
        if getattr(args, "dry_run", False):
            out = OUT_DIR / f"draft-{slug}.json"
            out.write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
            log(f"  dry-run: {out}")
            return row
        sb_request("POST", "/rest/v1/denki_seo_guide", row, prefer="return=minimal")
        if kw in pool["items"]:
            pool["items"][kw]["status"] = "used"
            pool["items"][kw]["slug"] = slug
            save_keywords(pool)
        url = f"{ORIGIN}/guides/{slug}"
        log(f"  published: {url} ({len(cites)} sources)")
        activity("guide_published", slug=slug, keyword=kw, title=page["title"], url=url, sources=len(cites))
        return row
    return None


# ---------------------------------------------------------------- エンジン2: 順位を磨く
def _query_stats(svc, page_url: str, query: str, start: date, end: date) -> dict:
    rows = _query(
        svc,
        start,
        end,
        [],
        row_limit=1,
        dimensionFilterGroups=[
            {
                "filters": [
                    {"dimension": "page", "operator": "equals", "expression": page_url},
                    {"dimension": "query", "operator": "equals", "expression": query},
                ]
            }
        ],
    )
    r = rows[0] if rows else {}
    days = (end - start).days + 1
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": days,
        "clicks": r.get("clicks", 0),
        "impressions": r.get("impressions", 0),
        "ctr": round(r.get("ctr", 0) * 100, 2),
        # 表示ゼロの期間は順位が 0 で返ってくる（＝1位と区別できない）ので「順位なし」にする
        "position": round(r.get("position", 0), 2) if r and r.get("impressions", 0) > 0 else None,
    }


def cmd_evaluate(args=None) -> list[dict]:
    """7日たった「磨き」を実測で判定する。明らかに悪化したら元の版に戻す。"""
    today = jst_today()
    due = sb_request(
        "GET",
        f"/rest/v1/denki_seo_experiment?select=*&status=eq.running&evaluate_on=lte.{today.isoformat()}",
    ) or []
    if not due:
        log("evaluate: 判定待ちなし")
        return []
    svc = _service()
    results = []
    for ex in due:
        started = date.fromisoformat(ex["started_on"])
        after = _query_stats(svc, ex["page_url"], ex["query"], started + timedelta(days=1), started + timedelta(days=7))
        base = ex["baseline"]
        bpos, apos = base.get("position"), after.get("position")
        per_day = lambda s: (s["impressions"] / s["days"]) if s["days"] else 0  # noqa: E731
        verdict = "neutral"
        if bpos is None and apos is not None:
            verdict = "won"  # 変更前は出ていなかった語で表示され始めた
        elif apos is None and bpos is not None:
            verdict = "lost" if per_day(base) >= 1 else "neutral"  # 表示が消えた
        elif bpos is not None and apos is not None:
            if apos <= bpos - 1.0 or (after["clicks"] > base["clicks"] * after["days"] / max(base["days"], 1) and apos <= bpos):
                verdict = "won"
            elif apos >= bpos + 2.0:
                verdict = "lost"
        reverted = False
        if verdict == "lost":
            reverted = _revert_guide(ex["guide_slug"], ex["from_revision"])
        sb_request(
            "PATCH",
            f"/rest/v1/denki_seo_experiment?id=eq.{ex['id']}",
            {"status": verdict, "result": {"after": after, "reverted": reverted}, "evaluated_at": datetime.now(timezone.utc).isoformat()},
            prefer="return=minimal",
        )
        log(f"evaluate: {ex['guide_slug']} 「{ex['query']}」 {bpos}→{apos} = {verdict}{' (元に戻した)' if reverted else ''}")
        activity("experiment_evaluated", slug=ex["guide_slug"], query=ex["query"], before=bpos, after=apos, verdict=verdict, reverted=reverted)
        results.append({"slug": ex["guide_slug"], "verdict": verdict})
    return results


def _revert_guide(slug: str, revision: int) -> bool:
    g = get_guide(slug)
    if not g:
        return False
    prev = next((h for h in g.get("history", []) if h.get("revision") == revision), None)
    if not prev:
        return False
    snap = {k: g.get(k) for k in PAGE_FIELDS + ("citations",)}
    snap["revision"] = g["revision"]
    patch = {k: prev[k] for k in PAGE_FIELDS + ("citations",) if k in prev}
    patch.update(
        {
            "revision": g["revision"] + 1,
            "history": (g.get("history", []) + [snap])[-10:],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    sb_request("PATCH", f"/rest/v1/denki_seo_guide?slug=eq.{slug}", patch, prefer="return=minimal")
    return True


def cmd_polish(args=None) -> dict | None:
    """あと少しで1位の言葉を1つ選び、上位ページと比べて足りない論点をサイトの資料で足す。"""
    min_impr = int(getattr(args, "min_impressions", 3) or 3)
    svc = _service()
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=27)
    rows = _query(svc, start, end, ["page", "query"], row_limit=2000)
    guides = {g["slug"]: g for g in list_guides()}
    running = sb_request("GET", "/rest/v1/denki_seo_experiment?select=guide_slug&status=eq.running") or []
    locked = {r["guide_slug"] for r in running}
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    cands, others = [], []
    for r in rows:
        page, query = r["keys"]
        pos, impr = r.get("position", 0), r.get("impressions", 0)
        if not (1.5 < pos <= 20 and impr >= min_impr):
            continue
        m = re.match(rf"^{re.escape(ORIGIN)}/guides/([a-z0-9-]+)$", page)
        slug = m.group(1) if m else None
        if slug and slug in guides and slug not in locked and parse_ts(guides[slug]["updated_at"]) < week_ago:
            # 1位に近く、表示が多いほど優先
            cands.append({"slug": slug, "page": page, "query": query, "position": pos, "impressions": impr, "score": impr / pos})
        else:
            others.append({"page": page, "query": query, "position": round(pos, 1), "impressions": impr})
    if others:
        activity("polish_manual_candidates", items=sorted(others, key=lambda x: -x["impressions"])[:10])
    if getattr(args, "force_slug", None):
        # 動作確認用: 実データが無くても、指定したページ・検索語で改善の流れを通す
        fs = args.force_slug
        cands = [{"slug": fs, "page": f"{ORIGIN}/guides/{fs}", "query": args.force_query or guides[fs]["keyword"], "position": 8.0, "impressions": 0, "score": 1}]
        locked.discard(fs)
    if not cands:
        log(f"polish: 対象なし（自動で直せるページで、表示{min_impr}回以上・2〜20位の言葉がまだ無い）")
        return None
    c = max(cands, key=lambda x: x["score"])
    g = get_guide(c["slug"])
    log(f"polish: {c['slug']} 「{c['query']}」 {c['position']:.1f}位 表示{c['impressions']}")

    current = {k: g.get(k) for k in PAGE_FIELDS}
    gap = claude_json(
        f"""WebSearch を使って、Google で「{c['query']}」と検索したときに上位に出る日本語のページを5件ほど調べてください。
上位ページが共通して扱っている論点・読者が知りたいことを整理し、下の「うちのページ」に足りない論点を挙げてください。
足りない論点は、電気管理技術者のブログや動画で現場の実例が見つかりそうな具体的なものに絞ってください（最大4つ）。

# うちのページ（{ORIGIN}/guides/{c['slug']}）
{json.dumps(current, ensure_ascii=False, indent=1)[:12000]}

次の JSON だけを ```json で囲んで返してください。
{{"top_pages": [{{"title": "", "url": "", "points": [""]}}], "missing": [{{"topic": "足りない論点", "why": "上位ページでの扱われ方", "kb_query": "サイト内の記事を探すための検索文"}}], "title_hint": "検索語に合う題名の方向", "description_hint": "説明文の方向"}}""",
        timeout=900,
    )
    if not gap:
        log("polish: 上位ページの調査に失敗")
        return None
    old_sources = (g.get("meta") or {}).get("sources") or []
    new_queries = [m["kb_query"] for m in gap.get("missing", []) if isinstance(m, dict) and m.get("kb_query")][:4]
    extra = gather_sources(new_queries, max_docs=8, min_sim=0.72) if new_queries else []
    known = {s["url"] for s in old_sources}
    sources = old_sources + [s for s in extra if s["url"] not in known]
    # 既存本文の [n] は旧出典番号（citations の n）なので、資料の並び（old_sources）の番号へ戻す
    url_to_idx = {s["url"]: i + 1 for i, s in enumerate(sources)}
    cite_map = {c_["n"]: url_to_idx.get(c_["url"]) for c_ in g.get("citations", [])}
    current = _map_text(current, lambda t: CITE_RE.sub(lambda m: f"[{cite_map.get(int(m.group(1)))}]" if cite_map.get(int(m.group(1))) else "", t))

    improved = claude_json(
        f"""検索語「{c['query']}」で現在 {c['position']:.1f} 位の解説ページを、1位を狙って改善します。
上位ページの調査で、うちのページに足りない論点が分かりました。資料で裏付けられる論点だけを足してください。
資料で裏付けられない論点は足さないでください（足さないことは失敗ではありません）。
題名と説明文は、検索語「{c['query']}」がそのまま、または自然に含まれるように見直してください。
既存の本文はできるだけ残し、[番号] も資料の番号のまま使ってください。

{WRITE_RULES}

# 上位ページの調査結果
{json.dumps(gap, ensure_ascii=False, indent=1)[:8000]}

# 現在のページ
{json.dumps(current, ensure_ascii=False, indent=1)}

# 資料
{sources_block(sources)}

改善後のページ全体を、同じ形の JSON だけで ```json で囲んで返してください。
{PAGE_SCHEMA}
""",
    )
    if not _valid_page(improved):
        log("polish: 改善案の形が崩れていた")
        return None
    page, check = write_and_review(c["query"], "", sources, draft=improved)
    if not page:
        log(f"polish: 審査を通らず見送り {check.get('reason')}")
        activity("polish_rejected", slug=c["slug"], query=c["query"])
        return None
    page, cites = finalize_citations(page, sources)
    if getattr(args, "dry_run", False):
        out = OUT_DIR / f"polish-draft-{c['slug']}.json"
        out.write_text(json.dumps({"gap": gap, "page": page, "citations": cites, "check": check}, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"polish dry-run: {out}")
        return None
    before = _query_stats(svc, c["page"], c["query"], end - timedelta(days=13), end)
    snap = {k: g.get(k) for k in PAGE_FIELDS + ("citations",)}
    snap["revision"] = g["revision"]
    added = [m.get("topic") for m in gap.get("missing", []) if isinstance(m, dict)]
    meta = dict(g.get("meta") or {})
    meta["sources"] = [{k: s.get(k) for k in ("title", "url", "source_name", "kind", "published_on", "excerpt")} for s in sources]
    sb_request(
        "PATCH",
        f"/rest/v1/denki_seo_guide?slug=eq.{c['slug']}",
        {
            **{k: page.get(k) for k in PAGE_FIELDS},
            "citations": cites,
            "revision": g["revision"] + 1,
            "history": (g.get("history", []) + [snap])[-10:],
            "check_result": check,
            "meta": meta,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        prefer="return=minimal",
    )
    today = jst_today()
    summary = f"題名「{g['title']}」→「{page['title']}」／足した論点候補: {'、'.join(filter(None, added)) or 'なし'}"
    sb_request(
        "POST",
        "/rest/v1/denki_seo_experiment",
        {
            "guide_slug": c["slug"],
            "page_url": c["page"],
            "query": c["query"],
            "started_on": today.isoformat(),
            # 変更後7日分の数字が Search Console に出そろう（約3日遅れ）日に判定する
            "evaluate_on": (today + timedelta(days=10)).isoformat(),
            "baseline": before,
            "change_summary": summary,
            "from_revision": g["revision"],
            "to_revision": g["revision"] + 1,
        },
        prefer="return=minimal",
    )
    log(f"polish: updated {c['slug']} rev{g['revision']}→{g['revision'] + 1}")
    activity("guide_polished", slug=c["slug"], query=c["query"], position=round(c["position"], 1), summary=summary, url=c["page"])
    return {"slug": c["slug"], "query": c["query"]}


# ---------------------------------------------------------------- エンジン3: 通知・AIの引用チェック
def indexnow(urls: list[str]) -> bool:
    urls = [u for u in dict.fromkeys(urls) if u.startswith(ORIGIN)]
    if not urls:
        return False
    body = {"host": "denkiouen.com", "key": INDEXNOW_KEY, "keyLocation": f"{ORIGIN}/{INDEXNOW_KEY}.txt", "urlList": urls}
    try:
        req = urllib.request.Request(
            "https://api.indexnow.org/indexnow",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as res:
            log(f"indexnow: {res.status} ({len(urls)} urls)")
            return res.status in (200, 202)
    except urllib.error.HTTPError as e:
        log(f"indexnow failed: {e.code} {e.read()[:200]!r}")
    except Exception as e:  # noqa: BLE001
        log(f"indexnow failed: {e}")
    return False


def cmd_indexnow(args) -> None:
    indexnow(args.urls)


def _page_ok(url: str, must: str = "") -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 denkiouen-seo-check"})
        with urllib.request.urlopen(req, timeout=60) as res:
            html = res.read().decode("utf-8", errors="replace")
            return res.status == 200 and (not must or must in html)
    except Exception:  # noqa: BLE001
        return False


DEFAULT_AI_QUESTIONS = [
    "高圧受電設備の年次点検で、絶縁抵抗の値が低く出たときはどう原因を切り分けますか？",
    "電気管理技術者として独立すると、最初の1年でどのくらい契約が取れるものですか？",
    "高圧の波及事故は主に何が原因で起きますか？防ぐために点検で見るべきところは？",
    "PASのSOG制御装置はどういう仕組みで動作し、点検では何を確認しますか？",
    "高圧ケーブルの水トリー劣化は、点検でどうやって見つけますか？",
    "進相コンデンサの劣化の兆候と、交換を考える目安を教えてください。",
    "月次点検で漏れ電流（Ior）を測るときの注意点は何ですか？",
    "キュービクルへの小動物の侵入を防ぐには、どんな対策がありますか？",
    "ZPDの零相電圧は、試験のときにどう換算して読みますか？",
    "現役の電気管理技術者のブログやYouTubeを横断して調べられるサイトはありますか？",
]


def _cited(urls: list[str], text: str) -> dict:
    hit = [u for u in urls if "denkiouen.com" in u or "denki-knowledge" in u]
    return {"cited": bool(hit), "cited_urls": hit, "mentioned": ("denkiouen" in text or "電気主任技術者応援サイト" in text)}


def _ask_openai(q: str) -> dict:
    key = _env().get("OPENAI_API_KEY")
    if not key:
        return {"error": "no key"}
    res = http_json(
        "https://api.openai.com/v1/responses",
        {"model": "gpt-5-mini", "tools": [{"type": "web_search"}], "input": q},
        headers={"Authorization": f"Bearer {key}"},
        timeout=180,
    )
    urls, text = [], ""
    for item in res.get("output", []):
        for c in item.get("content", []) or []:
            if c.get("type") == "output_text":
                text += c.get("text", "")
                for a in c.get("annotations", []) or []:
                    if a.get("url"):
                        urls.append(a["url"])
    return {"answer": text[:1500], "urls": list(dict.fromkeys(urls)), **_cited(urls, text)}


def _ask_gemini(q: str) -> dict:
    key = _env().get("GOOGLE_GEMINI_API_KEY")
    res = http_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={key}",
        {"contents": [{"role": "user", "parts": [{"text": q}]}], "tools": [{"google_search": {}}]},
        timeout=180,
    )
    cand = (res.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
    chunks = (cand.get("groundingMetadata") or {}).get("groundingChunks", []) or []
    # Gemini の出典 URL は転送用の短縮 URL なので、題名（＝ドメイン名）も一緒に見る
    urls = [f"{(c.get('web') or {}).get('title', '')} {(c.get('web') or {}).get('uri', '')}" for c in chunks]
    return {"answer": text[:1500], "urls": urls, **_cited(urls, text)}


def _ask_claude(q: str) -> dict:
    out = claude(
        f"""次の質問に、WebSearch で調べたうえで日本語で答えてください。
最後に、参考にしたページの URL を JSON で ```json {{"urls": ["..."]}} ``` の形で付けてください。

質問: {q}""",
        timeout=600,
        model="sonnet",
    ) or ""
    data = extract_json(out) or {}
    urls = [u for u in data.get("urls", []) if isinstance(u, str)] if isinstance(data, dict) else []
    return {"answer": out[:1500], "urls": urls, **_cited(urls, out)}


def cmd_ai_check(args=None) -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    AI_CHECK_DIR.mkdir(parents=True, exist_ok=True)
    if not AI_QUESTIONS_PATH.exists():
        AI_QUESTIONS_PATH.write_text(json.dumps(DEFAULT_AI_QUESTIONS, ensure_ascii=False, indent=1), encoding="utf-8")
    questions = json.loads(AI_QUESTIONS_PATH.read_text(encoding="utf-8"))
    engines = {"ChatGPT": _ask_openai, "Gemini": _ask_gemini, "Claude": _ask_claude}
    results = []
    for q in questions:
        row = {"question": q}
        for name, fn in engines.items():
            try:
                row[name] = fn(q)
            except Exception as e:  # noqa: BLE001
                row[name] = {"error": str(e)[:300]}
            time.sleep(2)
        results.append(row)
        log(f"ai-check: {q[:30]} → " + " ".join(f"{n}:{'○' if row[n].get('cited') else '×'}" for n in engines))
    month = jst_today().strftime("%Y-%m")
    summary = {n: sum(1 for r in results if r[n].get("cited")) for n in engines}
    report = {"month": month, "checked_at": datetime.now(timezone.utc).isoformat(), "summary": summary, "results": results}
    (AI_CHECK_DIR / f"{month}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# AIに引用されたか {month}", "", "| 質問 | " + " | ".join(engines) + " |", "|---|" + "---|" * len(engines)]
    for r in results:
        lines.append(f"| {r['question']} | " + " | ".join("○" if r[n].get("cited") else ("×" if "error" not in r[n] else "失敗") for n in engines) + " |")
    lines += ["", "引用された数: " + "、".join(f"{n} {summary[n]}/{len(results)}" for n in engines)]
    (AI_CHECK_DIR / f"{month}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    activity("ai_check", month=month, summary=summary, total=len(results))
    return report


# ---------------------------------------------------------------- 週1の一覧・毎日の実行
def cmd_weekly_list(args=None) -> str:
    since = datetime.now(timezone.utc) - timedelta(days=int(getattr(args, "days", 7) or 7))
    recs = []
    if ACTIVITY.exists():
        for line in ACTIVITY.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if parse_ts(r["at"]) >= since:
                recs.append(r)
    pub = [r for r in recs if r["kind"] == "guide_published"]
    pol = [r for r in recs if r["kind"] == "guide_polished"]
    ev = [r for r in recs if r["kind"] == "experiment_evaluated"]
    rej = [r for r in recs if r["kind"] in ("guide_rejected", "polish_rejected")]
    lines = [f"# 今週出たページ（{jst_today().isoformat()} までの7日）", ""]
    lines.append(f"## 新しく出したページ {len(pub)}本")
    lines += [f"- [{r['title']}]({r['url']})（出典{r.get('sources', '?')}本）" for r in pub] or ["- なし"]
    lines += ["", f"## 順位を磨いたページ {len(pol)}本"]
    lines += [f"- {r['url']} 「{r['query']}」{r['position']}位 → {r['summary']}" for r in pol] or ["- なし（まだ磨ける順位の言葉がない）"]
    if ev:
        lines += ["", "## 7日後の判定"]
        label = {"won": "上がった", "neutral": "変化なし", "lost": "下がった（元に戻した）"}
        lines += [f"- {r['slug']} 「{r['query']}」 {r['before']}位 → {r['after']}位：{label.get(r['verdict'], r['verdict'])}" for r in ev]
    if rej:
        lines += ["", f"審査で見送った案: {len(rej)}件"]
    md = "\n".join(lines) + "\n"
    (OUT_DIR / f"weekly-{jst_today().isoformat()}.md").write_text(md, encoding="utf-8")
    (OUT_DIR / "weekly-latest.md").write_text(md, encoding="utf-8")
    print(md)
    return md


def cmd_daily(args) -> None:
    log("===== daily start =====")
    touched: list[str] = []
    try:
        cmd_evaluate(args)
    except Exception as e:  # noqa: BLE001
        log(f"evaluate failed: {e}")
    try:
        row = cmd_new_page(args)
        if row:
            url = f"{ORIGIN}/guides/{row['slug']}"
            touched += [url, f"{ORIGIN}/guides"]
            # 配信側で実際に開けるか確かめる（開けなければ非公開に戻す）
            ok = False
            for _ in range(6):
                if _page_ok(url, row["title"][:10]):
                    ok = True
                    break
                time.sleep(20)
            if not ok:
                log(f"  公開URLで開けない → 非公開に戻す: {url}")
                sb_request("PATCH", f"/rest/v1/denki_seo_guide?slug=eq.{row['slug']}", {"status": "hidden"}, prefer="return=minimal")
                activity("guide_hidden", slug=row["slug"], reason="公開URLで開けなかった")
                touched = []
    except Exception as e:  # noqa: BLE001
        log(f"new-page failed: {e}")
    try:
        res = cmd_polish(args)
        if res:
            touched.append(f"{ORIGIN}/guides/{res['slug']}")
    except Exception as e:  # noqa: BLE001
        log(f"polish failed: {e}")
    if touched:
        indexnow(touched)
        try:
            svc = _service()
            svc.sitemaps().submit(siteUrl=SITE_URL, feedpath=SITEMAP_URL).execute()
            log("sitemap submitted")
        except Exception as e:  # noqa: BLE001
            log(f"sitemap submit failed: {e}")
    log("===== daily end =====")
    _notify_room_if_failed(touched)


ROOM_ID = "60760f4c-e236-49f4-a72c-c556bc56fa68"  # 電気主任技術者応援サイトの部屋


def _looks_like_login_expired(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in ("/login", "please run", "invalid api key", "authentication_error", "oauth token", "not logged in"))


def _notify_room_if_failed(touched: list[str]) -> None:
    """その日の解説ページが出なかった時だけ、部屋へ短く知らせる（成功日は静かに）。"""
    if any("/guides/" in u and not u.endswith("/guides") for u in touched):
        return
    today = jst_today().isoformat()
    tail = ""
    try:
        lines = (Path(__file__).resolve().parent.parent / ".tmp" / "denki_seo_daily.log").read_text(encoding="utf-8", errors="replace").splitlines()
        tail = "\n".join(l for l in lines[-40:] if today in l and ("failed" in l or "failure reason" in l or "非公開" in l or "対象なし" in l or "候補なし" in l))[-600:]
    except Exception:  # noqa: BLE001
        pass
    head = "原因を調べて復旧してください。"
    if _looks_like_login_expired(tail):
        # ログイン切れの間はダン自身も起きられない。直せるのは本人の再ログインだけなので、そう書く。
        head = "文章を書くAI（Claude）のログインが切れているようです。みきさんの再ログインが必要です。"
    body = f"[SEO自動運用の見張り] {today} の解説ページが公開されませんでした。{head}\n{tail}"
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:9000/api/v1/chat/internal/rooms/{ROOM_ID}/messages",
            data=json.dumps({"content": body, "sender_type": "system"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=15).read()
        log("failure notice posted to room")
    except Exception as e:  # noqa: BLE001
        log(f"failure notice failed: {e}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("daily")
    d.add_argument("--min-impressions", default="3")
    n = sub.add_parser("new-page")
    n.add_argument("--keyword")
    n.add_argument("--angle")
    n.add_argument("--slug")
    n.add_argument("--dry-run", action="store_true")
    pl = sub.add_parser("polish")
    pl.add_argument("--min-impressions", default="3")
    pl.add_argument("--force-slug")
    pl.add_argument("--force-query")
    pl.add_argument("--dry-run", action="store_true")
    sub.add_parser("evaluate")
    sub.add_parser("keywords")
    i = sub.add_parser("indexnow")
    i.add_argument("urls", nargs="+")
    sub.add_parser("ai-check")
    w = sub.add_parser("weekly-list")
    w.add_argument("--days", default="7")
    args = p.parse_args()
    {
        "daily": cmd_daily,
        "new-page": cmd_new_page,
        "polish": cmd_polish,
        "evaluate": cmd_evaluate,
        "keywords": cmd_keywords,
        "indexnow": cmd_indexnow,
        "ai-check": cmd_ai_check,
        "weekly-list": cmd_weekly_list,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
