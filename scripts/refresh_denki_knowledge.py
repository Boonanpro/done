# -*- coding: utf-8 -*-
"""
電管ナレッジ索引の増分更新（新着だけ軽くチェックして追加）

既存の frontend/public/denki-knowledge-index.json を読み込み、
各情報源の「新着一覧」だけを軽く取得して、まだ索引に無い記事/動画だけを追加する。
サイト全体の再取得はしない（相手サーバへの負担を最小化）。

使い方:
    python scripts/refresh_denki_knowledge.py            # 索引の更新のみ
    python scripts/refresh_denki_knowledge.py --deploy   # 更新があれば本番反映まで
    python scripts/refresh_denki_knowledge.py --publish-only  # 索引取得はせず反映だけ

朝1回、Windowsタスクスケジューラから --deploy 付きで実行する想定。
"""
import asyncio
import json
import os
import re
import sys
import io
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

requests.packages.urllib3.disable_warnings()  # type: ignore
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# スクリプトの位置を基準にした絶対パス（タスクスケジューラ等、作業フォルダがD:\done以外でも動くように）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_PATH = os.path.join(ROOT, "frontend", "public", "denki-knowledge-index.json")
# 公開サイトを配信しているのは done-artifacts リポジトリ / Vercel プロジェクト。
# ただしこのスクリプトから done-artifacts を直接触ってはいけない（publish_index の
# docstring 参照）。反映は app.services.artifact_git_publish に任せる。
UA = "Mozilla/5.0 (compatible; DenkiKnowledgeBot/1.0; +blog cross-search)"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"}
TEXT_CAP = 1500
EXCERPT_CAP = 160
NEW_PER_SOURCE_CAP = 60   # 1回の更新で1ソースに足す上限（暴走防止）
TIMEOUT = 20

session = requests.Session()
session.headers.update(HEADERS)


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def strip_html(raw: str) -> str:
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    return clean(soup.get_text(" "))


def get(url: str):
    r = session.get(url, timeout=TIMEOUT, verify=False)
    if not r.encoding or r.encoding.lower() in ("iso-8859-1", "windows-1252", "windows-1254"):
        r.encoding = r.apparent_encoding or r.encoding
    return r


def norm_url(u: str) -> str:
    return (u or "").split("#")[0].rstrip("/")


def body_text_from_soup(soup: BeautifulSoup) -> str:
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        t.decompose()
    body_el = None
    for sel in [".entry-content", ".article-body", ".post-content", ".articleBody",
                "article", ".entry", ".post", "#main", "main"]:
        body_el = soup.select_one(sel)
        if body_el:
            break
    return clean((body_el or soup).get_text(" "))[:TEXT_CAP]


# ───────── 新着取得（タイプ別・新しい順の一覧だけを軽く見る） ─────────
def newest_wordpress(base):
    api = f"{base}/wp-json/wp/v2/posts?per_page=30&orderby=date&order=desc&_fields=title,link,date,excerpt,content"
    out = []
    try:
        r = get(api)
        if r.status_code == 200:
            for p in r.json():
                title = strip_html(p.get("title", {}).get("rendered", ""))
                body = strip_html(p.get("content", {}).get("rendered", "")) or strip_html(
                    p.get("excerpt", {}).get("rendered", ""))
                if title:
                    out.append({"title": title, "url": p.get("link", ""),
                                "date": (p.get("date") or "")[:10], "text": body[:TEXT_CAP]})
    except Exception as e:
        print(f"   wp err: {e}")
    return out


def newest_blogger(base):
    feed = f"{base}/feeds/posts/default?alt=atom&max-results=30"
    out = []
    try:
        r = get(feed)
        soup = BeautifulSoup(r.text, "xml")
        for e in soup.find_all("entry"):
            title = clean(e.title.get_text() if e.title else "")
            link = ""
            for l in e.find_all("link"):
                if l.get("rel") == "alternate":
                    link = l.get("href", "")
            date = (e.published.get_text()[:10] if e.published else "")
            content = e.find("content")
            body = strip_html(content.get_text() if content else "")
            if title:
                out.append({"title": title, "url": link, "date": date, "text": body[:TEXT_CAP]})
    except Exception as e:
        print(f"   blogger err: {e}")
    return out


def _parse_rss(text):
    """RSS2.0 / RSS1.0(RDF) の item を新しい順で返す。"""
    soup = BeautifulSoup(text, "xml")
    out = []
    for it in soup.find_all("item"):
        title = clean(it.title.get_text() if it.title else "")
        link = clean(it.link.get_text() if it.link else "")
        # RSS1.0 は link が空のことがあるので rdf:about / guid を見る
        if not link:
            link = it.get("rdf:about", "") or (it.guid.get_text() if it.guid else "")
        date = ""
        for tag in ("pubDate", "dc:date", "date"):
            el = it.find(tag)
            if el:
                m = re.search(r"\d{4}-\d{2}-\d{2}", el.get_text())
                date = m.group(0) if m else ""
                break
        desc = it.find("description") or it.find("content:encoded")
        body = strip_html(desc.get_text() if desc else "")
        if title and link:
            out.append({"title": title, "url": link, "date": date, "text": body[:TEXT_CAP]})
    return out


def newest_fc2(base):
    for feed in (f"{base}/?xml", f"{base}?xml"):
        try:
            r = get(feed)
            items = _parse_rss(r.text)
            if items:
                return items
        except Exception as e:
            print(f"   fc2 err: {e}")
    return []


def newest_livedoor(base):
    for feed in (f"{base}/index.rdf", f"{base}/index.xml"):
        try:
            r = get(feed)
            if r.status_code == 200:
                items = _parse_rss(r.text)
                if items:
                    return items
        except Exception:
            pass
    # フォールバック: sitemapから新着の /archives/ を拾って各ページ取得
    return newest_html(base, kind="livedoor")


def collect_sitemap_urls(base):
    urls, seen, visited = [], set(), set()
    queue = [f"{base}/sitemap.xml", f"{base}/sitemap_index.xml", f"{base}/wp-sitemap.xml"]
    while queue and len(urls) < 3000:
        sm = queue.pop(0)
        if sm in visited:
            continue
        visited.add(sm)
        try:
            r = get(sm)
        except Exception:
            continue
        if r.status_code != 200:
            continue
        soup = BeautifulSoup(r.text, "xml")
        sub = [s.loc.get_text() for s in soup.find_all("sitemap") if s.loc]
        queue.extend(sub[:30])
        for u in soup.find_all("url"):
            if u.loc:
                loc = u.loc.get_text().strip()
                if loc not in seen:
                    seen.add(loc)
                    urls.append(loc)
    return urls


def extract_generic(url):
    try:
        r = get(url)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    title = ""
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        title = og["content"]
    if not title and soup.title:
        title = soup.title.get_text()
    title = clean(title)
    date = ""
    for sel, attr in [("meta[property='article:published_time']", "content"),
                      ("time[datetime]", "datetime")]:
        el = soup.select_one(sel)
        if el and el.get(attr):
            m = re.search(r"\d{4}-\d{2}-\d{2}", el.get(attr))
            if m:
                date = m.group(0)
                break
    body = body_text_from_soup(soup)
    if not title:
        return None
    return {"title": title, "url": url, "date": date, "text": body}


def newest_html(base, kind="html", known=None):
    urls = collect_sitemap_urls(base)
    if kind == "livedoor":
        arts = [u for u in urls if re.search(r"/archives/\d+", u)] or urls
    else:
        arts = [u for u in urls
                if u.rstrip("/") != base.rstrip("/")
                and not re.search(r"/(category|tag|author|page|about|profile|contact|privacy)/", u, re.I)]
    # 既知URLは飛ばし、未知の先頭だけ取得（新着想定）
    known = known or set()
    fresh = [u for u in arts if norm_url(u) not in known][:NEW_PER_SOURCE_CAP]
    out = []
    for u in fresh:
        a = extract_generic(u)
        if a and len(a["text"]) > 40:
            out.append(a)
    return out


def newest_mori(known):
    base = "https://moridenkikanri.com"
    urls = collect_sitemap_urls(base)
    arts = [u for u in urls if re.search(r"/blog/\d+", u)]
    fresh = [u for u in arts if norm_url(u) not in known][:NEW_PER_SOURCE_CAP]
    out = []
    for u in fresh:
        try:
            s = BeautifulSoup(get(u).text, "html.parser")
        except Exception:
            continue
        title = ""
        for h in s.find_all(["h1", "h2", "h3"]):
            tx = clean(h.get_text(" "))
            if not tx or tx == "ブログ" or "森電気管理事務所" in tx:
                continue
            title = tx
            break
        if title:
            out.append({"title": title[:120], "url": u, "date": "", "text": body_text_from_soup(s)})
    return out


def newest_sakon(known):
    base = "http://www.sakon-eco.info/"
    seen, queue = set(), []
    for seed in (base, base + "sitemap.html"):
        try:
            s = BeautifulSoup(get(seed).text, "html.parser")
        except Exception:
            continue
        for a in s.find_all("a", href=True):
            h = urljoin(base, a["href"]).split("#")[0]
            if "sakon-eco.info" in h and h.lower().endswith((".htm", ".html")) and h not in seen:
                seen.add(h)
                queue.append(h)
    skip = ("index", "sitemap", "policy", "link.htm", "ryokin", "sinsei", "gyosei", "eigyou", "privacy")
    out = []
    for u in queue:
        if any(k in u.lower() for k in skip) or norm_url(u) in known:
            continue
        a = extract_generic(u)
        if a:
            a["title"] = re.sub(r"\s*[/／｜|]\s*佐近電気.*$", "", a["title"]).strip()[:120]
            if a["title"] and len(a["text"]) >= 60:
                out.append(a)
    return out


def newest_youtube(url, known):
    import yt_dlp
    opts = {"quiet": True, "extract_flat": True, "skip_download": True,
            "playlistend": 40, "http_headers": {"Accept-Language": "ja-JP,ja"},
            "extractor_args": {"youtube": {"lang": ["ja"]}}}
    out = []
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url.rstrip("/") + "/videos", download=False)
            for e in info.get("entries") or []:
                vid, title = e.get("id"), clean(e.get("title") or "")
                if vid and title:
                    out.append({"title": title, "url": f"https://www.youtube.com/watch?v={vid}",
                                "date": "", "text": title})
    except Exception as e:
        print(f"   youtube err: {e}")
    return out


def fetch_newest(src, known):
    t, base = src.get("type"), src["url"]
    if src["id"] == "moridenkikanri":
        return newest_mori(known)
    if src["id"] == "sakon":
        return newest_sakon(known)
    if t == "wordpress":
        return newest_wordpress(base)
    if t == "blogger":
        return newest_blogger(base)
    if t == "fc2":
        return newest_fc2(base)
    if t == "livedoor":
        return newest_livedoor(base)
    if t == "html":
        return newest_html(base, known=known)
    if t == "youtube":
        return newest_youtube(base, known)
    return []


def _verify_published(generated_at: str, attempts: int = 12, wait: int = 30) -> bool:
    """公開URLの索引が新しい generated_at に切り替わるまで確認する。"""
    # <slug>-done.vercel.app の alias は廃止済み（RULES.md）。索引は public 直下に
    # 置かれるので、成果物本体を配信している done-artifacts のホストで確認する。
    url = "https://denki-knowledge-done.vercel.app/denki-knowledge-index.json"
    for _ in range(attempts):
        try:
            r = session.get(url, headers={"Range": "bytes=0-200"}, timeout=TIMEOUT)
            if generated_at in r.text:
                print(f"[publish] 公開反映を確認: {generated_at}")
                return True
        except Exception:
            pass
        time.sleep(wait)
    print("[publish] 公開反映を確認できませんでした（後で再実行してください）")
    return False


def publish_index() -> bool:
    """索引を正規の公開経路（artifact_git_publish）で公開する。

    ここで done-artifacts の作業ツリー main へ直接 commit し、push が失敗したら
    その作業ツリーをそのまま `vercel --prod` で上げる、という実装をしてはいけない。
    ローカル main が origin/main から分岐していると、本番が「分岐した古い main」で
    丸ごと置き換わり、他の成果物（吉川特装など）が巻き戻る。
    2026-07-30 に吉川特装のトップが6月18日の v1 に戻った事故の原因はこれだった。

    artifact_git_publish は origin/main（push できない間は publish-pending）を
    土台に隔離 worktree を作り、denki-knowledge のファイルだけを載せて公開するので、
    他の成果物を巻き戻さない。索引 frontend/public/denki-knowledge-index.json は
    denki-knowledge 所有ファイルとして公開対象に含まれている。
    """
    with open(INDEX_PATH, encoding="utf-8") as f:
        generated_at = json.load(f)["generated_at"]

    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    try:
        from app.services.artifact_publication_service import ArtifactPublicationService
        from app.services.chat_artifact_service import ChatArtifactService

        def deploy_dedicated_index():
            rows = (ChatArtifactService().supabase.table("chat_artifact").select("*")
                    .eq("slug", "denki-knowledge").order("created_at", desc=True).limit(1).execute())
            if not rows.data:
                return [{"status": "error", "error": "denki-knowledge artifact is not registered"}]
            asyncio.run(ArtifactPublicationService().deploy_dedicated_release(rows.data[0]))
            return [{"status": "live", "changed": True}]
    except Exception as e:  # noqa: BLE001
        print("[publish] 公開処理を読み込めません:", e)
        return False

    results = deploy_dedicated_index()
    result = results[0] if results else {}
    status = result.get("status")
    if status not in ("live", "pushed", "skipped"):
        print("[publish] 公開に失敗:", str(result.get("error", ""))[:1000])
        return False
    if not result.get("changed"):
        print("[publish] 索引に差分なし（公開はすでに最新）")
        return True

    return _verify_published(generated_at)


def main():
    do_deploy = "--deploy" in sys.argv
    if "--publish-only" in sys.argv:
        sys.exit(0 if publish_index() else 1)
    with open(INDEX_PATH, encoding="utf-8") as f:
        doc = json.load(f)

    known_by_src = {}
    for a in doc["articles"]:
        known_by_src.setdefault(a["source"], set()).add(norm_url(a["url"]))

    src_by_id = {s["id"]: s for s in doc["sources"]}
    next_id = max((a["id"] for a in doc["articles"]), default=-1) + 1
    added_total = 0
    report = []

    for s in doc["sources"]:
        known = known_by_src.get(s["id"], set())
        items = fetch_newest(s, known)
        # 新着だけ抽出（URL重複・既知を除く）
        fresh, seen_now = [], set()
        for it in items:
            nu = norm_url(it.get("url", ""))
            if not nu or nu in known or nu in seen_now:
                continue
            seen_now.add(nu)
            fresh.append(it)
        fresh = fresh[:NEW_PER_SOURCE_CAP]
        for it in fresh:
            doc["articles"].append({
                "id": next_id, "source": s["id"], "sourceName": s["name"],
                "title": it["title"][:120], "date": it.get("date", ""),
                "url": it["url"], "excerpt": it["text"][:EXCERPT_CAP], "text": it["text"],
            })
            next_id += 1
        if fresh:
            s["count"] = s.get("count", 0) + len(fresh)
            added_total += len(fresh)
            report.append((s["id"], len(fresh)))

    doc["count"] = len(doc["articles"])
    doc["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    print(f"[{stamp}] 新着追加: {added_total} 件 / 総数 {doc['count']}")
    for sid, n in report:
        print(f"    + {sid}: {n}")

    if do_deploy and added_total > 0:
        print("新着があったため本番反映します…")
        publish_index()
    elif do_deploy:
        print("新着なし。本番反映はスキップ。")


if __name__ == "__main__":
    main()
