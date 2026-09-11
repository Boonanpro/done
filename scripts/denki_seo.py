"""電気主任技術者応援サイト（denkiouen.com）の検索対策を自動で回すための道具。

やること:
  auth              Google Search Console に接続する（初回だけ。ブラウザで 0aw325171 のログインが要る）
  report            直近N日の検索成績（クリック・表示回数・掲載順位）を取り、改善候補を洗い出して
                    D:/dan-workspace/denki_seo/ に JSON と Markdown で保存する
  ensure-ai-answers 質問・相談の全件に AI 一次回答が付いているか確かめ、無ければ作らせる
                    （質問1件＝1ページなので、回答が無いページを検索エンジンに見せない）
  submit-sitemap    サイト地図を Search Console に出し直す（新しい質問ページを早く拾わせる）
  weekly            ensure-ai-answers → submit-sitemap → report をまとめて実行（毎週の定期実行用）

接続情報:
  OAuth クライアントは ~/.ai_secretary/gmail_credentials.json（installed 型・localhost リダイレクト可）。
  取得したトークンは app.services.encryption で暗号化して ~/.dan/gsc_token.enc に置く。
  対象プロパティは URL プレフィックス型 https://denkiouen.com/（layout.tsx の確認タグ2本目）。

使い方:
  python scripts/denki_seo.py auth
  python scripts/denki_seo.py report --days 28
  python scripts/denki_seo.py weekly
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SITE_URL = "https://denkiouen.com/"
SITEMAP_URL = "https://denkiouen.com/sitemap.xml"
SCOPES = ["https://www.googleapis.com/auth/webmasters"]
CLIENT_JSON = Path.home() / ".ai_secretary" / "gmail_credentials.json"
TOKEN_PATH = Path.home() / ".dan" / "gsc_token.enc"
OUT_DIR = Path("D:/dan-workspace/denki_seo")
LOG_PATH = ROOT / ".tmp" / "denki_seo.log"


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- 認証
def _encrypt(text: str) -> str:
    from app.services.encryption import encrypt_data

    return encrypt_data(text)


def _decrypt(text: str) -> str:
    from app.services.encryption import decrypt_data

    return decrypt_data(text)


def cmd_auth(args) -> None:
    """ブラウザで Google にログインして許可をもらい、トークンを暗号化保存する。

    open_browser=False なので、表示される URL を browser ツールで開く（この PC のブラウザなら
    localhost へのリダイレクトがこのプロセスに届く）。
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_JSON), scopes=SCOPES)
    creds = flow.run_local_server(
        host="127.0.0.1",
        port=int(args.port),
        open_browser=False,
        authorization_prompt_message="AUTH_URL: {url}\n",
        success_message="Search Console との接続が完了しました。このタブは閉じて構いません。",
        access_type="offline",
        prompt="consent",
        login_hint="0aw325171@gmail.com",
    )
    data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
    }
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(_encrypt(json.dumps(data)), encoding="utf-8")
    log(f"token saved: {TOKEN_PATH} (refresh_token={'yes' if creds.refresh_token else 'NO'})")


def _credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not TOKEN_PATH.exists():
        raise SystemExit("トークンがありません。先に `denki_seo.py auth` を実行してください。")
    data = json.loads(_decrypt(TOKEN_PATH.read_text(encoding="utf-8")))
    creds = Credentials(
        token=data["token"],
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes", SCOPES),
    )
    if creds.expired or not creds.valid:
        creds.refresh(Request())
        data["token"] = creds.token
        TOKEN_PATH.write_text(_encrypt(json.dumps(data)), encoding="utf-8")
    return creds


def _service():
    from googleapiclient.discovery import build

    return build("searchconsole", "v1", credentials=_credentials(), cache_discovery=False)


# ---------------------------------------------------------------- 検索成績
def _query(svc, start: date, end: date, dimensions: list[str], row_limit: int = 500, **extra):
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": dimensions,
        "rowLimit": row_limit,
        "dataState": "all",
    }
    body.update(extra)
    res = svc.searchanalytics().query(siteUrl=SITE_URL, body=body).execute()
    return res.get("rows", [])


def cmd_report(args) -> dict:
    svc = _service()
    days = int(args.days)
    # Search Console の数字は2〜3日遅れて確定するので、終点を3日前にする
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)

    total = _query(svc, start, end, [], row_limit=1)
    prev_total = _query(svc, prev_start, prev_end, [], row_limit=1)
    by_query = _query(svc, start, end, ["query"], row_limit=500)
    by_page = _query(svc, start, end, ["page"], row_limit=500)
    by_page_query = _query(svc, start, end, ["page", "query"], row_limit=1000)
    by_day = _query(svc, start, end, ["date"], row_limit=days)

    def flat(rows):
        return [
            {
                "keys": r.get("keys", []),
                "clicks": r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "ctr": round(r.get("ctr", 0) * 100, 2),
                "position": round(r.get("position", 0), 1),
            }
            for r in rows
        ]

    queries = flat(by_query)
    pages = flat(by_page)
    page_queries = flat(by_page_query)

    # 改善候補
    # 1) 表示は多いのにクリックされない（題名・説明文の見直し候補）
    low_ctr = [
        q for q in queries if q["impressions"] >= 20 and q["ctr"] < 2.0 and q["position"] <= 20
    ]
    # 2) 5〜20位の「惜しい」言葉（中身を足せば上がる候補）
    near_top = [q for q in queries if 5 <= q["position"] <= 20 and q["impressions"] >= 10]
    # 3) 検索されているのに、受け皿ページが弱い言葉（新しい特集・Q&Aの候補）
    weak_landing = [
        pq
        for pq in page_queries
        if pq["impressions"] >= 10 and pq["position"] > 20
    ]

    # サイト地図の状態
    sitemaps = []
    try:
        sm = svc.sitemaps().list(siteUrl=SITE_URL).execute()
        for s in sm.get("sitemap", []):
            sitemaps.append(
                {
                    "path": s.get("path"),
                    "lastSubmitted": s.get("lastSubmitted"),
                    "lastDownloaded": s.get("lastDownloaded"),
                    "errors": s.get("errors"),
                    "warnings": s.get("warnings"),
                    "contents": s.get("contents"),
                }
            )
    except Exception as e:  # noqa: BLE001
        sitemaps.append({"error": str(e)})

    # 主要URLの登録状況（URL検査。1日2000回の上限があるので、まとめて少数だけ）
    coverage = []
    try:
        import urllib.request
        import xml.etree.ElementTree as ET

        xml = urllib.request.urlopen(SITEMAP_URL, timeout=30).read()
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = [loc.text for loc in ET.fromstring(xml).findall(".//s:loc", ns)]
        for u in urls[: int(args.inspect_limit)]:
            try:
                r = (
                    svc.urlInspection()
                    .index()
                    .inspect(body={"inspectionUrl": u, "siteUrl": SITE_URL, "languageCode": "ja"})
                    .execute()
                )
                idx = r.get("inspectionResult", {}).get("indexStatusResult", {})
                coverage.append(
                    {
                        "url": u,
                        "verdict": idx.get("verdict"),
                        "coverageState": idx.get("coverageState"),
                        "lastCrawlTime": idx.get("lastCrawlTime"),
                        "pageFetchState": idx.get("pageFetchState"),
                    }
                )
            except Exception as e:  # noqa: BLE001
                coverage.append({"url": u, "error": str(e)[:200]})
            time.sleep(0.3)
    except Exception as e:  # noqa: BLE001
        coverage.append({"error": str(e)[:200]})

    def tot(rows):
        r = rows[0] if rows else {}
        return {
            "clicks": r.get("clicks", 0),
            "impressions": r.get("impressions", 0),
            "ctr": round(r.get("ctr", 0) * 100, 2),
            "position": round(r.get("position", 0), 1),
        }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "site": SITE_URL,
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "total": tot(total),
        "previous_total": tot(prev_total),
        "by_day": flat(by_day),
        "top_queries": queries[:50],
        "top_pages": pages[:50],
        "opportunities": {
            "low_ctr": low_ctr[:30],
            "near_top": near_top[:30],
            "weak_landing": weak_landing[:30],
        },
        "sitemaps": sitemaps,
        "coverage": coverage,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = end.isoformat()
    (OUT_DIR / f"report-{stamp}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md = _render_md(report)
    (OUT_DIR / f"report-{stamp}.md").write_text(md, encoding="utf-8")
    (OUT_DIR / "latest.md").write_text(md, encoding="utf-8")
    log(f"report saved: {OUT_DIR / f'report-{stamp}.md'}")
    print(md)
    return report


def _render_md(r: dict) -> str:
    t, p = r["total"], r["previous_total"]
    lines = [
        f"# denkiouen.com 検索成績 {r['period']['start']} 〜 {r['period']['end']}（{r['period']['days']}日）",
        "",
        "| | 今回 | 前の期間 |",
        "|---|---|---|",
        f"| クリック（検索から来た人） | {t['clicks']} | {p['clicks']} |",
        f"| 表示回数 | {t['impressions']} | {p['impressions']} |",
        f"| クリック率 | {t['ctr']}% | {p['ctr']}% |",
        f"| 平均掲載順位 | {t['position']} | {p['position']} |",
        "",
        "## よく出ている検索語（上位20）",
        "",
        "| 検索語 | クリック | 表示 | 率 | 順位 |",
        "|---|---|---|---|---|",
    ]
    for q in r["top_queries"][:20]:
        lines.append(
            f"| {q['keys'][0]} | {q['clicks']} | {q['impressions']} | {q['ctr']}% | {q['position']} |"
        )
    lines += ["", "## ページ別（上位20）", "", "| ページ | クリック | 表示 | 率 | 順位 |", "|---|---|---|---|---|"]
    for pg in r["top_pages"][:20]:
        lines.append(
            f"| {pg['keys'][0].replace('https://denkiouen.com', '')} | {pg['clicks']} | {pg['impressions']} | {pg['ctr']}% | {pg['position']} |"
        )
    op = r["opportunities"]
    lines += ["", "## 改善候補", ""]
    lines.append(f"- 表示は多いのにクリックされない語（題名・説明文の見直し）: {len(op['low_ctr'])}件")
    for q in op["low_ctr"][:10]:
        lines.append(f"  - {q['keys'][0]}（表示{q['impressions']}・率{q['ctr']}%・{q['position']}位）")
    lines.append(f"- 5〜20位の惜しい語（中身を足せば上がる）: {len(op['near_top'])}件")
    for q in op["near_top"][:10]:
        lines.append(f"  - {q['keys'][0]}（表示{q['impressions']}・{q['position']}位）")
    lines.append(f"- 受け皿が弱い語（新しい特集・Q&Aの候補）: {len(op['weak_landing'])}件")
    for pq in op["weak_landing"][:10]:
        lines.append(
            f"  - {pq['keys'][1]} → {pq['keys'][0].replace('https://denkiouen.com', '')}（表示{pq['impressions']}・{pq['position']}位）"
        )
    lines += ["", "## サイト地図", ""]
    for s in r["sitemaps"]:
        lines.append(f"- {json.dumps(s, ensure_ascii=False)}")
    lines += ["", "## 主要URLの登録状況", ""]
    for c in r["coverage"]:
        if "error" in c and "url" not in c:
            lines.append(f"- 取得できず: {c['error']}")
            continue
        lines.append(
            f"- {c.get('url','').replace('https://denkiouen.com', '') or '/'}: {c.get('verdict')} / {c.get('coverageState')} / 最終巡回 {c.get('lastCrawlTime')}"
            if "error" not in c
            else f"- {c['url']}: エラー {c['error']}"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 自動作業
def _env() -> dict:
    env = {}
    try:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return env


def cmd_ensure_ai_answers(args) -> list[str]:
    """公開中の質問で AI 一次回答が無いものに、本番の回答APIで一次回答を付けさせる。"""
    import urllib.request

    env = _env()
    url = env.get("SUPABASE_URL") or env.get("NEXT_PUBLIC_SUPABASE_URL")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_SERVICE_KEY") or env.get("SUPABASE_KEY")
    if not url or not key:
        log("supabase config missing")
        return []
    req = urllib.request.Request(
        f"{url}/rest/v1/denki_qa_question?select=id,title,is_hidden,denki_qa_answer(is_ai,is_hidden)&is_hidden=eq.false&order=created_at.desc",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
    )
    rows = json.load(urllib.request.urlopen(req, timeout=60))
    missing = [
        r for r in rows if not any(a.get("is_ai") and not a.get("is_hidden") for a in r.get("denki_qa_answer", []))
    ]
    log(f"questions={len(rows)} missing_ai_answer={len(missing)}")
    done = []
    for r in missing:
        body = json.dumps({"question_id": r["id"]}).encode()
        api = urllib.request.Request(
            "https://denkiouen.com/api/denki-ai/answer",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            res = json.load(urllib.request.urlopen(api, timeout=120))
            log(f"ai answer for {r['id'][:8]} {r['title'][:30]!r}: {res.get('ok') or res}")
            done.append(r["id"])
        except Exception as e:  # noqa: BLE001
            log(f"ai answer failed for {r['id'][:8]}: {e}")
        time.sleep(2)
    return done


def cmd_submit_sitemap(args) -> None:
    svc = _service()
    svc.sitemaps().submit(siteUrl=SITE_URL, feedpath=SITEMAP_URL).execute()
    log(f"sitemap submitted: {SITEMAP_URL}")


def cmd_weekly(args) -> None:
    try:
        cmd_ensure_ai_answers(args)
    except Exception as e:  # noqa: BLE001
        log(f"ensure-ai-answers failed: {e}")
    try:
        cmd_submit_sitemap(args)
    except Exception as e:  # noqa: BLE001
        log(f"submit-sitemap failed: {e}")
    cmd_report(args)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("auth")
    a.add_argument("--port", default="8765")
    r = sub.add_parser("report")
    r.add_argument("--days", default="28")
    r.add_argument("--inspect-limit", default="12")
    sub.add_parser("ensure-ai-answers")
    sub.add_parser("submit-sitemap")
    w = sub.add_parser("weekly")
    w.add_argument("--days", default="28")
    w.add_argument("--inspect-limit", default="12")
    args = p.parse_args()
    {
        "auth": cmd_auth,
        "report": cmd_report,
        "ensure-ai-answers": cmd_ensure_ai_answers,
        "submit-sitemap": cmd_submit_sitemap,
        "weekly": cmd_weekly,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
