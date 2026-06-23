"""
Umami アクセス計測サービス（運営者所有・マルチテナント）

公開した独自ドメインを Umami に website 登録し、計測スクリプト用の website_id を
払い出し、訪問数（pageviews/visitors 等）を引き戻す。

## マルチテナント方針

Search Console と同じく、**運営者（プラットフォーム提供者）が 1 つの Umami admin を
持てば、Dan を使う全ユーザーの公開ドメインを 1 インスタンスで計測できる**。
Umami の「website」= テナントの 1 独自ドメイン。各クライアントには自分の website の
データだけ見せられる（運営者は全 website を横断で見られる）。

認証情報は .env の以下に置く（運営者固定）:
  - ``UMAMI_BASE_URL``       例: https://dan-analytics-ten.vercel.app
  - ``UMAMI_ADMIN_USER``     例: admin
  - ``UMAMI_ADMIN_PASSWORD``

未設定なら全関数が「未設定」を返し、公開フロー自体は止めずにスキップする。

使い方:
    from app.services.umami_service import (
        ensure_website, fetch_stats, tracking_for_host, is_configured,
    )
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# 運営者 admin ログインで得た JWT をプロセス内にキャッシュ（Umami のトークンは
# 長命なので 12h で更新。401 が出たら都度再ログインする）。
_TOKEN_CACHE: dict[str, Any] = {"token": None, "fetched_at": 0.0}
_TOKEN_TTL_SEC = 12 * 3600

# host -> website_id の解決結果を短期キャッシュ（タグ注入が毎リクエスト Umami を
# 叩かないように）。website は公開時に一度作られたら不変なので長めで良い。
_WEBSITE_ID_CACHE: dict[str, Optional[str]] = {}

_HTTP_TIMEOUT = 15.0


def is_configured() -> bool:
    return bool(
        settings.UMAMI_BASE_URL
        and settings.UMAMI_ADMIN_USER
        and settings.UMAMI_ADMIN_PASSWORD
    )


def _base() -> str:
    return settings.UMAMI_BASE_URL.rstrip("/")


def _norm_domain(host_or_domain: str) -> str:
    """host/domain を website 照合用に正規化（小文字・ポート除去・www 除去）。"""
    d = (host_or_domain or "").strip().lower()
    d = d.split(":")[0]
    if d.startswith("www."):
        d = d[4:]
    return d


async def _login(client: httpx.AsyncClient) -> Optional[str]:
    """運営者 admin でログインしてトークンを返す。失敗時 None。"""
    try:
        r = await client.post(
            f"{_base()}/api/auth/login",
            json={
                "username": settings.UMAMI_ADMIN_USER,
                "password": settings.UMAMI_ADMIN_PASSWORD,
            },
        )
        if r.status_code != 200:
            logger.warning("umami login failed: HTTP %s", r.status_code)
            return None
        return r.json().get("token")
    except Exception as e:  # noqa: BLE001
        logger.warning("umami login error: %s", e)
        return None


async def _get_token(client: httpx.AsyncClient, force: bool = False) -> Optional[str]:
    now = time.time()
    if (
        not force
        and _TOKEN_CACHE["token"]
        and (now - _TOKEN_CACHE["fetched_at"]) < _TOKEN_TTL_SEC
    ):
        return _TOKEN_CACHE["token"]
    token = await _login(client)
    if token:
        _TOKEN_CACHE["token"] = token
        _TOKEN_CACHE["fetched_at"] = now
    return token


async def _api(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    json: Optional[dict] = None,
    params: Optional[dict] = None,
) -> Optional[httpx.Response]:
    """認証付きで Umami API を叩く。401 なら 1 度だけ再ログインして再試行。"""
    token = await _get_token(client)
    if not token:
        return None
    for attempt in range(2):
        r = await client.request(
            method,
            f"{_base()}{path}",
            headers={"Authorization": f"Bearer {token}"},
            json=json,
            params=params,
        )
        if r.status_code == 401 and attempt == 0:
            token = await _get_token(client, force=True)
            if not token:
                return None
            continue
        return r
    return None


async def _find_website_id(client: httpx.AsyncClient, domain: str) -> Optional[str]:
    """登録済み website から domain 一致のものを探して id を返す。無ければ None。"""
    target = _norm_domain(domain)
    r = await _api(
        client, "GET", "/api/websites", params={"pageSize": 200, "page": 1}
    )
    if r is None or r.status_code != 200:
        return None
    rows = r.json().get("data", [])
    for w in rows:
        if _norm_domain(w.get("domain", "")) == target:
            return w.get("id")
    return None


async def ensure_website(domain: str, name: Optional[str] = None) -> Optional[str]:
    """domain の website を Umami に用意して website_id を返す（冪等）。

    既にあればその id、無ければ作成。未設定/失敗時は None（公開フローは止めない）。
    """
    if not is_configured():
        return None
    domain = _norm_domain(domain)
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            existing = await _find_website_id(client, domain)
            if existing:
                _WEBSITE_ID_CACHE[domain] = existing
                return existing
            r = await _api(
                client,
                "POST",
                "/api/websites",
                json={"name": name or domain, "domain": domain},
            )
            if r is None or r.status_code not in (200, 201):
                logger.warning(
                    "umami create website failed for %s: HTTP %s",
                    domain,
                    getattr(r, "status_code", "none"),
                )
                return None
            wid = r.json().get("id")
            if wid:
                _WEBSITE_ID_CACHE[domain] = wid
            return wid
    except Exception as e:  # noqa: BLE001
        logger.warning("ensure_website error for %s: %s", domain, e)
        return None


async def get_website_id(domain: str) -> Optional[str]:
    """domain の website_id を解決（作成はしない）。タグ注入・stats 用。"""
    if not is_configured():
        return None
    domain = _norm_domain(domain)
    if domain in _WEBSITE_ID_CACHE:
        return _WEBSITE_ID_CACHE[domain]
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            wid = await _find_website_id(client, domain)
            _WEBSITE_ID_CACHE[domain] = wid  # None もキャッシュ（未登録の連打防止）
            return wid
    except Exception as e:  # noqa: BLE001
        logger.warning("get_website_id error for %s: %s", domain, e)
        return None


async def tracking_for_host(host: str) -> Optional[dict[str, str]]:
    """独自ドメイン host の計測タグ情報 {website_id, src} を返す。未登録なら None。

    フロント共通レイアウトが <script> を差し込むために使う。
    """
    wid = await get_website_id(host)
    if not wid:
        return None
    return {"website_id": wid, "src": f"{_base()}/script.js"}


def _metric(stats: dict, key: str) -> int:
    v = stats.get(key)
    if isinstance(v, dict):
        return int(v.get("value", 0) or 0)
    return int(v or 0)


async def fetch_stats(domain: str, *, days: int = 28) -> dict[str, Any]:
    """独自ドメインの訪問数を Umami から引き戻す。

    Returns:
        ``{"configured", "domain", "website_id", "range", "pageviews",
           "visitors", "visits", "bounce_rate", "detail"}``
        未設定/未登録なら configured/website_id で判別できる。
    """
    if not is_configured():
        return {
            "configured": False,
            "domain": domain,
            "website_id": None,
            "summary": None,
            "detail": "Umami が未設定です（UMAMI_BASE_URL 等）",
        }
    domain = _norm_domain(domain)
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            wid = await _find_website_id(client, domain)
            if not wid:
                return {
                    "configured": True,
                    "domain": domain,
                    "website_id": None,
                    "summary": None,
                    "detail": "このドメインは Umami に未登録です（未公開の可能性）",
                }
            r = await _api(
                client,
                "GET",
                f"/api/websites/{wid}/stats",
                params={"startAt": start_ms, "endAt": end_ms},
            )
            if r is None or r.status_code != 200:
                return {
                    "configured": True,
                    "domain": domain,
                    "website_id": wid,
                    "summary": None,
                    "detail": f"stats 取得に失敗: HTTP {getattr(r,'status_code','none')}",
                }
            s = r.json()
            visits = _metric(s, "visits")
            bounces = _metric(s, "bounces")
            bounce_rate = round(bounces / visits, 3) if visits else 0.0
            return {
                "configured": True,
                "domain": domain,
                "website_id": wid,
                "range": {"days": days, "start_ms": start_ms, "end_ms": end_ms},
                "summary": {
                    "pageviews": _metric(s, "pageviews"),
                    "visitors": _metric(s, "visitors"),
                    "visits": visits,
                    "bounce_rate": bounce_rate,
                },
                "detail": "ok",
            }
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch_stats error for %s: %s", domain, e)
        return {
            "configured": True,
            "domain": domain,
            "website_id": None,
            "summary": None,
            "detail": f"例外: {str(e)[:200]}",
        }
