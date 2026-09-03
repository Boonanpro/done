# -*- coding: utf-8 -*-
"""
電管ナレッジ索引に「森電気管理事務所」「佐近電気管理事務所」を追加する。

両サイトとも build_denki_knowledge_index.py の汎用HTML処理では
うまくタイトルが取れない（森=全ページ同一の og:title / 佐近=sitemap無し）ため、
サイト個別の取り込みロジックをここに持つ。
"""
import json
import re
import sys
import io
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

requests.packages.urllib3.disable_warnings()  # type: ignore
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

INDEX_PATH = "frontend/public/denki-knowledge-index.json"
H = {"User-Agent": "Mozilla/5.0 (compatible; DenkiKnowledgeBot/1.0; +blog cross-search)"}
TEXT_CAP = 1500
EXCERPT_CAP = 160
TIMEOUT = 20

session = requests.Session()
session.headers.update(H)


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def get(url: str):
    r = session.get(url, timeout=TIMEOUT, verify=False)
    if not r.encoding or r.encoding.lower() in ("iso-8859-1", "windows-1252", "windows-1254"):
        r.encoding = r.apparent_encoding or r.encoding
    return r


def body_text(soup: BeautifulSoup) -> str:
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        t.decompose()
    return clean(soup.get_text(" "))[:TEXT_CAP]


# ───────────── 森電気管理事務所（sitemap → /blog/数字、本文見出しをタイトルに） ─────────────
def scrape_mori():
    base = "https://moridenkikanri.com"
    sm = get(f"{base}/sitemap.xml")
    soup = BeautifulSoup(sm.text, "xml")
    urls = [l.get_text().strip() for l in soup.find_all("loc")]
    arts = [u for u in urls if re.search(r"/blog/\d+", u)]
    out = []
    for u in arts:
        try:
            r = get(u)
        except Exception:
            continue
        s = BeautifulSoup(r.text, "html.parser")
        # 記事タイトル: 見出しのうち空・「ブログ」・事務所名を除いた最初のもの
        title = ""
        for h in s.find_all(["h1", "h2", "h3"]):
            tx = clean(h.get_text(" "))
            if not tx or tx in ("ブログ",) or "森電気管理事務所" in tx:
                continue
            title = tx
            break
        if not title:
            continue
        out.append({"title": title[:120], "url": u, "date": "", "text": body_text(s)})
    return out


# ───────────── 佐近電気管理事務所（indexから内部リンク収集、<title>をタイトルに） ─────────────
def scrape_sakon():
    base = "http://www.sakon-eco.info/"
    seen, queue, pages = set(), [base], []
    # index と sitemap.html からリンクを集める
    for seed in (base, base + "sitemap.html"):
        try:
            r = get(seed)
        except Exception:
            continue
        s = BeautifulSoup(r.text, "html.parser")
        for a in s.find_all("a", href=True):
            h = urljoin(base, a["href"]).split("#")[0]
            if "sakon-eco.info" not in h:
                continue
            if not h.lower().endswith((".htm", ".html")):
                continue
            if h not in seen:
                seen.add(h)
                queue.append(h)
    skip = ("index", "sitemap", "policy", "link.htm", "ryokin", "sinsei",
            "gyosei", "eigyou", "privacy")
    out = []
    for u in queue:
        low = u.lower()
        if any(k in low for k in skip):
            continue
        try:
            r = get(u)
        except Exception:
            continue
        s = BeautifulSoup(r.text, "html.parser")
        raw = clean(s.title.get_text() if s.title else "")
        title = re.sub(r"\s*[/／｜|]\s*佐近電気.*$", "", raw).strip()
        body = body_text(s)
        if not title or len(body) < 60:
            continue
        out.append({"title": title[:120], "url": u, "date": "", "text": body})
    return out


def add_source(doc, sid, name, url, typ, items):
    existing = {s["id"] for s in doc["sources"]}
    if sid in existing:
        print(f"skip (exists): {sid}")
        return
    # url重複除去
    seen, uniq = set(), []
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        uniq.append(it)
    next_id = max((a["id"] for a in doc["articles"]), default=-1) + 1
    for it in uniq:
        doc["articles"].append({
            "id": next_id,
            "source": sid,
            "sourceName": name,
            "title": it["title"],
            "date": it["date"],
            "url": it["url"],
            "excerpt": it["text"][:EXCERPT_CAP],
            "text": it["text"],
        })
        next_id += 1
    doc["sources"].append({"id": sid, "name": name, "url": url, "type": typ, "count": len(uniq)})
    print(f"  {sid}: {len(uniq)} 件")
    for it in uniq[:5]:
        print("     -", it["title"])


def main():
    with open(INDEX_PATH, encoding="utf-8") as f:
        doc = json.load(f)

    print("== mori ==")
    add_source(doc, "moridenkikanri", "森電気管理事務所", "https://moridenkikanri.com", "html", scrape_mori())
    print("== sakon ==")
    add_source(doc, "sakon", "佐近電気管理事務所", "http://www.sakon-eco.info/", "html", scrape_sakon())

    doc["count"] = len(doc["articles"])
    doc["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n総記事数: {doc['count']} / ソース数: {len(doc['sources'])}")


if __name__ == "__main__":
    main()
