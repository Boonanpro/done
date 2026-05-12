"""
Cloudflare Registrar API クライアント

Beta API (2026-04公開) の domain-search / domain-check / registrations を扱う。
DNS API (zones/dns_records) は別ファイルで扱う想定。

使い方:
    registrar = await get_cloudflare_registrar()
    available = await registrar.check_availability(["paina.com"])
    result = await registrar.register("paina.com", years=1, contact=DEFAULT_CONTACT)
"""
from __future__ import annotations

import logging
from typing import Any, Optional, TypedDict

import httpx

from app.services.credentials_service import get_credentials_service

logger = logging.getLogger(__name__)

API_BASE = "https://api.cloudflare.com/client/v4"
DEFAULT_USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"  # 0aw325171@gmail.com
HTTP_TIMEOUT = 30.0


class RegistrarError(RuntimeError):
    """Cloudflare Registrar API がエラーレスポンスを返した時の例外"""

    def __init__(self, status: int, errors: list[dict[str, Any]]):
        self.status = status
        self.errors = errors
        msg_parts = [f"code={e.get('code')} message={e.get('message')}" for e in errors]
        super().__init__(f"HTTP {status}: " + "; ".join(msg_parts))


class PostalAddress(TypedDict, total=False):
    street: str
    city: str
    state: str
    postal_code: str
    country_code: str  # ISO 3166-1 alpha-2 (例: "JP")


class PostalInfo(TypedDict, total=False):
    name: str
    organization: str
    address: PostalAddress


class Contact(TypedDict, total=False):
    email: str
    phone: str  # E.164 形式 (例: "+81.7083524060")
    fax: str
    postal_info: PostalInfo


class CloudflareRegistrar:
    """Cloudflare Registrar API の薄いラッパー。

    すべてのメソッドは success レスポンスの ``result`` をそのまま返す。
    エラー時は :class:`RegistrarError` を raise する。
    """

    def __init__(self, account_id: str, token: str) -> None:
        self.account_id = account_id
        self.token = token
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _account_url(self, path: str) -> str:
        return f"{API_BASE}/accounts/{self.account_id}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
    ) -> Any:
        url = self._account_url(path)
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.request(
                method, url, headers=self._headers, params=params, json=json
            )
        try:
            body = resp.json()
        except ValueError:
            raise RegistrarError(resp.status_code, [{"code": -1, "message": resp.text[:200]}])
        if not body.get("success"):
            raise RegistrarError(resp.status_code, body.get("errors", []))
        return body.get("result")

    async def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """サジェスト: ``query`` から候補ドメイン名を生成。

        各要素には ``name`` / ``registrable`` / ``tier`` / ``pricing`` が含まれる。
        """
        result = await self._request(
            "GET",
            "/registrar/domain-search",
            params={"q": query, "limit": limit},
        )
        return result["domains"]

    async def check_availability(self, domains: list[str]) -> list[dict[str, Any]]:
        """ドメインの空き状況と価格を一括取得。

        Returns:
            ``[{"name": "...", "registrable": bool, "tier": str, "pricing": {...}}, ...]``
        """
        return (await self._request(
            "POST",
            "/registrar/domain-check",
            json={"domains": domains},
        ))["domains"]

    async def register(
        self,
        domain: str,
        *,
        years: int = 1,
        auto_renew: bool = True,
        privacy_mode: str = "redaction",
        contact: Optional[Contact] = None,
    ) -> dict[str, Any]:
        """新規ドメインを登録 (購入)。

        Args:
            domain: 取得するドメイン名 (FQDN)
            years: 登録年数 (1-10)
            auto_renew: 自動更新 ON/OFF
            privacy_mode: WHOIS プライバシー保護 ("redaction" or "off")
            contact: Registrant Contact。None の場合はアカウントのデフォルト連絡先が使用される。

        Returns:
            登録結果の生レスポンス (workflow URL や status を含む)
        """
        body: dict[str, Any] = {
            "domain_name": domain,
            "years": years,
            "auto_renew": auto_renew,
            "privacy_mode": privacy_mode,
        }
        if contact is not None:
            body["contacts"] = {"registrant": contact}
        return await self._request(
            "POST",
            "/registrar/registrations",
            json=body,
        )

    async def list_registrations(self) -> list[dict[str, Any]]:
        """このアカウントで登録済みのドメイン一覧"""
        return await self._request("GET", "/registrar/registrations")

    async def get_registration(self, domain: str) -> dict[str, Any]:
        """ドメインのフル登録情報"""
        return await self._request("GET", f"/registrar/registrations/{domain}")

    async def get_registration_status(self, domain: str) -> dict[str, Any]:
        """ドメインの登録ワークフロー状況 (購入処理が進行中の場合のステータス確認用)"""
        return await self._request(
            "GET", f"/registrar/registrations/{domain}/registration-status"
        )


async def get_cloudflare_registrar(user_id: Optional[str] = None) -> CloudflareRegistrar:
    """credentials DB から認証情報を取得して :class:`CloudflareRegistrar` を返す。

    service=cloudflare で保存された ``{id: account_id, password: token}`` を期待する。
    """
    cred = await get_credentials_service().get_credential(
        user_id or DEFAULT_USER_ID, "cloudflare"
    )
    if not cred or not cred.get("id") or not cred.get("password"):
        raise RuntimeError(
            "Cloudflare credentials が credentials DB に存在しません。"
            "service=cloudflare で account_id と token を保存してください。"
        )
    return CloudflareRegistrar(account_id=cred["id"], token=cred["password"])
