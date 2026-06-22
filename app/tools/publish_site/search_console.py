"""
Google Search Console 自動申請

公開したサイトを Google Search Console に登録し、sitemap を送信する。
これにより「公開 → 検索でヒット」までを自動化する (Manus/Base44 にはない差別化点)。

## マルチテナント方針

Search Console 連携は **プラットフォーム運営者が 1 つのサービスアカウントを
登録すれば、Dan を使う全ユーザーが公開する全ドメインに対して機能する**。
所有権確認はドメインごとに DNS TXT で行うため、1 つのサービスアカウントで
任意のドメインを検証・申請できる。利用者ごとに JSON を用意する必要はない。

認証情報は credentials DB の運営者アカウント (OPERATOR_USER_ID) 配下、
service="google_search_console" に、サービスアカウント JSON 全体を文字列で
password フィールドに保存する。未登録の場合は全関数が「未設定」を返し、
公開フロー自体は止めずにスキップする。

ドメイン所有権の確認は DNS TXT レコード方式 (Site Verification API):
  - 自社 Cloudflare 管理ドメイン (owner_pays): ``auto_submit`` が TXT を自動投入
  - クライアント所有ドメイン: クライアントが TXT を追加 → ``verify_and_submit`` で確認

使い方:
    from app.tools.publish_site.search_console import (
        get_dns_verification_record, verify_and_submit, auto_submit,
    )
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

from app.services.credentials_service import get_credentials_service

logger = logging.getLogger(__name__)

# プラットフォーム運営者のアカウント。Search Console のサービスアカウントは
# このアカウント配下に 1 度だけ登録すれば全テナントで共有される。
OPERATOR_USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"  # 0aw325171@gmail.com
CREDENTIAL_SERVICE = "google_search_console"
SCOPES = [
    "https://www.googleapis.com/auth/siteverification",
    "https://www.googleapis.com/auth/webmasters",
]
# DNS 伝播待ちのための所有権確認リトライ
VERIFY_RETRY = 6
VERIFY_RETRY_INTERVAL_SEC = 10


class SearchConsoleError(RuntimeError):
    """Search Console / Site Verification API のエラー"""


# ============================================
# サービスアカウント読み込み
# ============================================


async def _load_service_account() -> Optional[dict[str, Any]]:
    """運営者のサービスアカウント JSON を読む。未登録なら None。"""
    cred = await get_credentials_service().get_credential(
        OPERATOR_USER_ID, CREDENTIAL_SERVICE
    )
    if not cred or not cred.get("password"):
        return None
    try:
        return json.loads(cred["password"])
    except (json.JSONDecodeError, TypeError) as e:
        raise SearchConsoleError(f"service account JSON parse failed: {e}")


def _build_clients(sa_info: dict[str, Any]):
    """siteVerification + searchconsole の API クライアントを作る (同期)。"""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as e:  # pragma: no cover
        raise SearchConsoleError(
            f"Google API ライブラリが見つかりません ({e})。"
            "requirements.txt の google-api-python-client を確認してください。"
        )

    creds = service_account.Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    sv = build("siteVerification", "v1", credentials=creds, cache_discovery=False, static_discovery=False)
    sc = build("searchconsole", "v1", credentials=creds, cache_discovery=False, static_discovery=False)
    return sv, sc


def _get_token_sync(sv, domain: str) -> str:
    """所有権確認用の DNS TXT トークンを取得する (同期)。"""
    resp = (
        sv.webResource()
        .getToken(
            body={
                "verificationMethod": "DNS_TXT",
                "site": {"type": "INET_DOMAIN", "identifier": domain},
            }
        )
        .execute()
    )
    token = resp.get("token")
    if not token:
        raise SearchConsoleError(f"getToken returned no token for {domain}")
    return token


# ============================================
# 公開 API
# ============================================


async def get_dns_verification_record(domain: str) -> Optional[dict[str, str]]:
    """Google 所有権確認用の DNS TXT レコードを返す。

    クライアント所有ドメインで、設定すべきレコードをクライアントに案内するために使う。

    Returns:
        ``{"type": "TXT", "name": "@", "value": "google-site-verification=..."}``
        サービスアカウント未設定なら None。
    """
    sa_info = await _load_service_account()
    if sa_info is None:
        return None

    def _work() -> str:
        sv, _ = _build_clients(sa_info)
        return _get_token_sync(sv, domain)

    token = await asyncio.to_thread(_work)
    return {"type": "TXT", "name": "@", "value": token}


async def verify_and_submit(domain: str, sitemap_url: str) -> dict[str, Any]:
    """所有権を確認し、Search Console に sitemap を申請する。

    DNS TXT レコードが既に設定済みである前提 (クライアントが追加済み、
    または ``auto_submit`` が投入済み)。

    Returns:
        ``{"configured": bool, "verified": bool, "sitemap_submitted": bool, "detail": str}``
    """
    sa_info = await _load_service_account()
    if sa_info is None:
        return {
            "configured": False,
            "verified": False,
            "sitemap_submitted": False,
            "detail": "Search Console のサービスアカウントが未設定です",
        }

    def _work() -> dict[str, Any]:
        sv, sc = _build_clients(sa_info)

        # 1. 所有権確認 (DNS 伝播待ちのためリトライ)
        verified = False
        last_err = ""
        for attempt in range(VERIFY_RETRY):
            try:
                sv.webResource().insert(
                    verificationMethod="DNS_TXT",
                    body={"site": {"type": "INET_DOMAIN", "identifier": domain}},
                ).execute()
                verified = True
                break
            except Exception as e:  # googleapiclient.errors.HttpError 等
                last_err = str(e)
                if attempt < VERIFY_RETRY - 1:
                    time.sleep(VERIFY_RETRY_INTERVAL_SEC)
        if not verified:
            return {
                "configured": True,
                "verified": False,
                "sitemap_submitted": False,
                "detail": f"所有権確認に失敗 (TXT レコード未反映の可能性): {last_err[:200]}",
            }

        # 2. sc-domain プロパティを追加 (既存なら無視)
        site_url = f"sc-domain:{domain}"
        try:
            sc.sites().add(siteUrl=site_url).execute()
        except Exception as e:
            logger.info("sites.add (既存の可能性): %s", e)

        # 3. sitemap を申請
        try:
            sc.sitemaps().submit(siteUrl=site_url, feedpath=sitemap_url).execute()
            return {
                "configured": True,
                "verified": True,
                "sitemap_submitted": True,
                "detail": f"{site_url} に {sitemap_url} を申請しました",
            }
        except Exception as e:
            return {
                "configured": True,
                "verified": True,
                "sitemap_submitted": False,
                "detail": f"所有権確認OK / sitemap 申請に失敗: {str(e)[:200]}",
            }

    return await asyncio.to_thread(_work)


async def fetch_search_performance(
    domain: str,
    *,
    days: int = 28,
    row_limit: int = 25,
) -> dict[str, Any]:
    """Search Console の検索パフォーマンスを引き戻す（改善ループの土台）。

    「どの検索語で表示/クリックされているか」(impressions/clicks/CTR/掲載順位) を返す。
    申請するだけだった Search Console から実データを取り戻し、後段の自動改善
    （弱い検索語のページを直す）の入力にする。

    Returns:
        ``{
            "configured": bool, "domain": str,
            "range": {"start","end","days"},
            "summary": {"clicks","impressions","ctr","position"},
            "top_queries": [{"query","clicks","impressions","ctr","position"}, ...],
            "top_pages": [{"page","clicks","impressions","ctr","position"}, ...],
            "detail": str,
        }``
        サービスアカウント未設定なら ``configured=False``。所有権未確認や
        データ未蓄積（公開直後）の場合は summary が空で detail に理由が入る。
    """
    sa_info = await _load_service_account()
    if sa_info is None:
        return {
            "configured": False,
            "domain": domain,
            "summary": None,
            "top_queries": [],
            "top_pages": [],
            "detail": "Search Console のサービスアカウントが未設定です",
        }

    def _work() -> dict[str, Any]:
        from datetime import date, timedelta

        _, sc = _build_clients(sa_info)
        site_url = f"sc-domain:{domain}"

        # Search Console のデータは 2〜3 日遅れて確定するため終端を 3 日前に寄せる
        end_eff = date.today() - timedelta(days=3)
        start = end_eff - timedelta(days=days)
        start_s, end_s = start.isoformat(), end_eff.isoformat()

        def _query(dimensions: list[str]) -> list[dict[str, Any]]:
            body = {
                "startDate": start_s,
                "endDate": end_s,
                "dimensions": dimensions,
                "rowLimit": row_limit,
            }
            resp = sc.searchanalytics().query(siteUrl=site_url, body=body).execute()
            return resp.get("rows", [])

        def _fmt(r: dict[str, Any]) -> dict[str, Any]:
            return {
                "clicks": int(r.get("clicks", 0)),
                "impressions": int(r.get("impressions", 0)),
                "ctr": round(float(r.get("ctr", 0.0)), 4),
                "position": round(float(r.get("position", 0.0)), 1),
            }

        # まず合計（dimension なし＝1行に集計）を取得。ここで失敗するのは
        # 所有権未確認・プロパティ未登録・データ未蓄積のいずれか。
        try:
            total_rows = _query([])
        except Exception as e:  # googleapiclient.errors.HttpError 等
            return {
                "configured": True,
                "domain": domain,
                "range": {"start": start_s, "end": end_s, "days": days},
                "summary": None,
                "top_queries": [],
                "top_pages": [],
                "detail": f"検索データ取得に失敗（未検証/データ未蓄積の可能性）: {str(e)[:200]}",
            }

        summary = (
            _fmt(total_rows[0])
            if total_rows
            else {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0}
        )

        def _safe(dimensions: list[str]) -> list[dict[str, Any]]:
            try:
                return _query(dimensions)
            except Exception:  # noqa: BLE001
                return []

        top_queries = [
            {"query": r["keys"][0], **_fmt(r)}
            for r in _safe(["query"])
            if r.get("keys")
        ]
        top_pages = [
            {"page": r["keys"][0], **_fmt(r)}
            for r in _safe(["page"])
            if r.get("keys")
        ]

        return {
            "configured": True,
            "domain": domain,
            "range": {"start": start_s, "end": end_s, "days": days},
            "summary": summary,
            "top_queries": top_queries,
            "top_pages": top_pages,
            "detail": "ok",
        }

    return await asyncio.to_thread(_work)


async def auto_submit(
    domain: str,
    sitemap_url: str,
    *,
    zone_id: str,
    cf_dns,
) -> dict[str, Any]:
    """自社 Cloudflare 管理ドメイン用: 所有権確認 TXT を自動投入してから申請する。

    Args:
        zone_id: Cloudflare の zone ID
        cf_dns: :class:`CloudflareDNS` インスタンス
    """
    record = await get_dns_verification_record(domain)
    if record is None:
        return {
            "configured": False,
            "verified": False,
            "sitemap_submitted": False,
            "detail": "Search Console のサービスアカウントが未設定です",
        }

    # 既存の verification TXT を確認し、なければ作成する
    try:
        existing = await cf_dns.list_records(zone_id, type="TXT")
        already = any(
            (r.get("content") or "").strip('"') == record["value"] for r in existing
        )
        if not already:
            await cf_dns.create_record(
                zone_id,
                type="TXT",
                name="@",
                content=record["value"],
                comment="Google Search Console 所有権確認",
            )
    except Exception as e:
        return {
            "configured": True,
            "verified": False,
            "sitemap_submitted": False,
            "detail": f"DNS TXT レコードの投入に失敗: {str(e)[:200]}",
        }

    return await verify_and_submit(domain, sitemap_url)
