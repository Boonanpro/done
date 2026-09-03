# -*- coding: utf-8 -*-
"""
電管ナレッジ検索 索引ビルダー（追加ソース対応版）

既存の frontend/public/denki-knowledge-index.json を読み込み、
新規の同業者ブログ／YouTube チャンネルをスクレイプして索引に追加する。

取り込み方式（サイト種別ごとに自動）:
  - wordpress : WP REST API (/wp-json/wp/v2/posts) 本文付きで一括取得
  - blogger   : Atom フィード (/feeds/posts/default) 本文付きで一括取得
  - livedoor  : sitemap で記事URL収集 → 各ページを取得して抽出
  - html      : sitemap.xml で記事URL収集 → 各ページを取得して抽出
  - youtube   : yt-dlp でチャンネル全動画のタイトル・IDを取得

計算ツール／資料サイト（記事単位で索引化しないもの）は page.tsx 側に
別タブ「資料・ツール」として手動で持つため、ここでは扱わない。
"""
import json
import re
import sys
import io
import html as htmllib
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

requests.packages.urllib3.disable_warnings()  # type: ignore

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

INDEX_PATH = "frontend/public/denki-knowledge-index.json"
UA = "Mozilla/5.0 (compatible; DenkiKnowledgeBot/1.0; +blog cross-search)"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"}

TEXT_CAP = 1500
EXCERPT_CAP = 160
PER_SOURCE_CAP = 320          # 1ソースあたり最大記事数
LIVEDOOR_PAGE_CAP = 220       # livedoor/html は各ページ取得が重いので絞る
TIMEOUT = 20

# 既存5ソースは再取得しない（保持）。以下は新規追加ソース。
NEW_SOURCES = [
    # --- WordPress（本文ごと一括取得・全期間） ---
    {"id": "hoandenkikanri", "name": "保安電気管理", "url": "https://hoandenkikanri.com", "type": "wordpress"},
    {"id": "ogawadenkikanri", "name": "小川電気管理事務所", "url": "https://www.ogawadenkikanri.com", "type": "wordpress"},
    {"id": "denmasu2", "name": "でんます", "url": "https://denmasu2.com", "type": "wordpress"},
    {"id": "bibouroku", "name": "電気技術者の備忘録", "url": "https://電気技術者の備忘録.net", "type": "wordpress"},
    # --- Blogger ---
    {"id": "denken333", "name": "電験・電気管理(denken333)", "url": "https://denken333.blogspot.com", "type": "blogger"},
    # --- livedoor ---
    {"id": "dengamisama", "name": "野生の電気主任技術者の日常", "url": "https://dengamisama.livedoor.blog", "type": "livedoor"},
    {"id": "ain1234", "name": "北の技術者（電気管理事務所）", "url": "https://ain1234livedoor.livedoor.blog", "type": "livedoor"},
    {"id": "wellstone7", "name": "私のデマンド日記", "url": "http://blog.livedoor.jp/wellstone7", "type": "livedoor"},
    # --- 汎用HTML（sitemap → 各ページ取得） ---
    # rara.jp/ponpon は記事ブログでなく掲示板のため、記事索引ではなく資料リンク側で扱う。
    {"id": "memolabo", "name": "でんきメモ (memo-labo)", "url": "https://memo-labo.com", "type": "html"},
    {"id": "moridenkikanri", "name": "森電気管理事務所", "url": "https://moridenkikanri.com", "type": "html"},
    # --- YouTube（チャンネル全動画） ---
    {"id": "yt_yuji", "name": "ゆうじの電気保安の学校(YouTube)", "url": "https://www.youtube.com/channel/UC19zw6C1saxiYD___u3Rz4Q", "type": "youtube"},
    {"id": "yt_ch2", "name": "電気管理YouTube②", "url": "https://www.youtube.com/channel/UCSTYic80CakW6vV6ACbefJA", "type": "youtube"},
    {"id": "yt_ch3", "name": "電気管理YouTube③", "url": "https://www.youtube.com/channel/UCjlN30LA5EP_t7Kl3OP0yWw", "type": "youtube"},
]

session = requests.Session()
session.headers.update(HEADERS)


def clean_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s).strip()
    return s


def strip_html(raw: str) -> str:
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    return clean_text(soup.get_text(" "))


def fetch(url: str):
    return session.get(url, timeout=TIMEOUT, verify=False)


# ───────────────────────── WordPress ─────────────────────────
def scrape_wordpress(src):
    out = []
    page = 1
    while len(out) < PER_SOURCE_CAP:
        api = f"{src['url']}/wp-json/wp/v2/posts?per_page=100&page={page}&_fields=title,link,date,excerpt,content"
        try:
            r = fetch(api)
        except Exception as e:
            print(f"   wp fetch err p{page}: {e}")
            break
        if r.status_code != 200:
            break
        try:
            posts = r.json()
        except Exception:
            break
        if not posts:
            break
        for p in posts:
            title = strip_html(p.get("title", {}).get("rendered", ""))
            body = strip_html(p.get("content", {}).get("rendered", "")) or strip_html(
                p.get("excerpt", {}).get("rendered", "")
            )
            if not title:
                continue
            out.append({
                "title": title,
                "url": p.get("link", ""),
                "date": (p.get("date") or "")[:10],
                "text": body[:TEXT_CAP],
            })
        page += 1
        if page > 8:
            break
    return out


# ───────────────────────── Blogger ─────────────────────────
def scrape_blogger(src):
    out = []
    start = 1
    step = 150
    while len(out) < PER_SOURCE_CAP:
        feed = f"{src['url']}/feeds/posts/default?alt=atom&max-results={step}&start-index={start}"
        try:
            r = fetch(feed)
        except Exception as e:
            print(f"   blogger err: {e}")
            break
        if r.status_code != 200:
            break
        soup = BeautifulSoup(r.text, "xml")
        entries = soup.find_all("entry")
        if not entries:
            break
        for e in entries:
            title = clean_text(e.title.get_text() if e.title else "")
            link = ""
            for l in e.find_all("link"):
                if l.get("rel") == "alternate":
                    link = l.get("href", "")
            date = (e.published.get_text()[:10] if e.published else "")
            content = e.find("content")
            body = strip_html(content.get_text() if content else "")
            if not title:
                continue
            out.append({"title": title, "url": link, "date": date, "text": body[:TEXT_CAP]})
        start += step
    return out


# ───────────────────────── 記事URL収集（sitemap） ─────────────────────────
def collect_urls_from_sitemap(base):
    """sitemap(index)を辿って記事URLを集める。"""
    urls = []
    seen = set()
    candidates = [
        f"{base}/sitemap.xml",
        f"{base}/sitemap_index.xml",
        f"{base}/wp-sitemap.xml",
    ]
    queue = list(candidates)
    visited_sm = set()
    while queue and len(urls) < 2000:
        sm = queue.pop(0)
        if sm in visited_sm:
            continue
        visited_sm.add(sm)
        try:
            r = fetch(sm)
        except Exception:
            continue
        if r.status_code != 200 or "xml" not in r.headers.get("content-type", "") and "<urlset" not in r.text and "<sitemapindex" not in r.text:
            continue
        soup = BeautifulSoup(r.text, "xml")
        # sitemap index ならサブsitemapをキューへ
        sub = [s.loc.get_text() for s in soup.find_all("sitemap") if s.loc]
        if sub:
            queue.extend(sub[:30])
        for u in soup.find_all("url"):
            if u.loc:
                loc = u.loc.get_text().strip()
                if loc not in seen:
                    seen.add(loc)
                    urls.append(loc)
    return urls


def looks_like_article(url, base):
    if not url.startswith("http"):
        return False
    tail = url[len(base):] if url.startswith(base) else url
    # トップ・カテゴリ・タグ・固定ページっぽいものを除外
    if re.search(r"/(category|tag|author|page|about|profile|contact|privacy)/", url, re.I):
        return False
    if url.rstrip("/") in (base.rstrip("/"),):
        return False
    return True


def extract_page(url):
    try:
        r = fetch(url)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    # 宣言済み文字コードを優先。未宣言(requestsが既定のISO-8859-1等)のときだけ推定。
    if not r.encoding or r.encoding.lower() in ("iso-8859-1", "windows-1252", "windows-1254"):
        r.encoding = r.apparent_encoding or r.encoding
    soup = BeautifulSoup(r.text, "html.parser")
    # title
    title = ""
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        title = og["content"]
    if not title and soup.title:
        title = soup.title.get_text()
    title = clean_text(title)
    # date
    date = ""
    for sel, attr in [
        ("meta[property='article:published_time']", "content"),
        ("meta[name='pubdate']", "content"),
        ("time[datetime]", "datetime"),
    ]:
        el = soup.select_one(sel)
        if el and el.get(attr):
            m = re.search(r"\d{4}-\d{2}-\d{2}", el.get(attr))
            if m:
                date = m.group(0)
                break
    # body
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        t.decompose()
    body_el = None
    for sel in [".entry-content", ".article-body", ".post-content", ".articleBody",
                "article", ".entry", ".post", "#main", "main"]:
        body_el = soup.select_one(sel)
        if body_el:
            break
    text = clean_text((body_el or soup).get_text(" "))
    if not title:
        return None
    return {"title": title, "url": url, "date": date, "text": text[:TEXT_CAP]}


def scrape_pages(src, urls):
    urls = [u for u in urls if looks_like_article(u, src["url"])]
    urls = urls[:LIVEDOOR_PAGE_CAP]
    out = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(extract_page, u): u for u in urls}
        for f in as_completed(futs):
            a = f.result()
            if a and len(a["text"]) > 40:
                out.append(a)
    return out


def scrape_livedoor(src):
    urls = collect_urls_from_sitemap(src["url"])
    arts = [u for u in urls if re.search(r"/archives/\d+", u)]
    if not arts:
        arts = urls
    return scrape_pages(src, arts)


def scrape_html(src):
    urls = collect_urls_from_sitemap(src["url"])
    return scrape_pages(src, urls)


# ───────────────────────── YouTube ─────────────────────────
def scrape_youtube(src):
    import yt_dlp
    opts = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
        "playlistend": PER_SOURCE_CAP,
        "http_headers": {"Accept-Language": "ja-JP,ja"},
        "extractor_args": {"youtube": {"lang": ["ja"]}},
    }
    url = src["url"].rstrip("/") + "/videos"
    out = []
    channel_title = None
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=False)
            ct = (info.get("title") or "")
            ct = re.sub(r"\s*[-–]\s*(Videos|動画)\s*$", "", ct).strip()
            channel_title = f"{ct}（YouTube）" if ct else None
            for e in info.get("entries") or []:
                vid = e.get("id")
                title = clean_text(e.get("title") or "")
                if not vid or not title:
                    continue
                out.append({
                    "title": title,
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "date": "",
                    "text": title,
                })
    except Exception as e:
        print(f"   youtube err: {e}")
    return out, channel_title


SCRAPERS = {
    "wordpress": scrape_wordpress,
    "blogger": scrape_blogger,
    "livedoor": scrape_livedoor,
    "html": scrape_html,
}


def main():
    with open(INDEX_PATH, encoding="utf-8") as f:
        doc = json.load(f)

    existing_sources = doc["sources"]
    existing_ids = {s["id"] for s in existing_sources}
    articles = doc["articles"]
    next_id = max((a["id"] for a in articles), default=-1) + 1

    report = []
    for src in NEW_SOURCES:
        if src["id"] in existing_ids:
            print(f"skip (exists): {src['id']}")
            continue
        print(f"== {src['id']} ({src['type']}) ==")
        ch_title = None
        if src["type"] == "youtube":
            items, ch_title = scrape_youtube(src)
        else:
            items = SCRAPERS[src["type"]](src)
        # 重複URL除去
        seen = set()
        uniq = []
        for it in items:
            if it["url"] in seen:
                continue
            seen.add(it["url"])
            uniq.append(it)
        uniq = uniq[:PER_SOURCE_CAP]
        name = ch_title or src["name"]
        for it in uniq:
            excerpt = it["text"][:EXCERPT_CAP]
            articles.append({
                "id": next_id,
                "source": src["id"],
                "sourceName": name,
                "title": it["title"],
                "date": it["date"],
                "url": it["url"],
                "excerpt": excerpt,
                "text": it["text"],
            })
            next_id += 1
        doc["sources"].append({
            "id": src["id"],
            "name": name,
            "url": src["url"],
            "type": src["type"],
            "count": len(uniq),
        })
        print(f"   -> {len(uniq)} 件")
        report.append((src["id"], src["type"], len(uniq)))

    doc["count"] = len(articles)
    doc["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))

    print("\n===== 取り込み結果 =====")
    for sid, typ, n in report:
        print(f"  {sid:18s} {typ:10s} {n}")
    print(f"総記事数: {doc['count']}  / ソース数: {len(doc['sources'])}")


if __name__ == "__main__":
    main()
