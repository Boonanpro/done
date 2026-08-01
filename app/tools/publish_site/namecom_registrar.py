"""
Name.com Registrar API (v4) クライアント

Cloudflare が扱わない TLD（.ai/.io 等）を、**前払い残高なしでカード都度課金**で
取得するためのレジストラ。Name.com は登録時に「アカウント残高があればそこから、
無ければ登録済みのデフォルト支払いプロファイル(カード)に課金」する＝Cloudflare と
同じく立替フロート不要。`cloudflare_registrar` / `porkbun_registrar` と同一I/F。

API: name.com Core API v1（旧 v4 は deprecated）。
- Base ``https://api.name.com/core/v1``（dev は api.dev.name.com）。HTTP Basic 認証(username:token)。
  ⚠️ 本番トークンの username はアカウント名（例 painainc）。Dev環境トークンは別物で
  username が ``<acct>-test`` になる点に注意（混同すると 401）。
- ``POST /core/v1/domains:checkAvailability`` 空き＋価格
- ``POST /core/v1/domains`` 登録（``purchasePrice`` は見積額の確認＝過剰請求ガード）
- ``POST /core/v1/domains/{domain}:setNameservers`` ネームサーバ更新

使い方:
    reg = await get_namecom_registrar()
    avail = await reg.check_availability(["paina.ai"])
    if avail[0]["registrable"]:
        await reg.register("paina.ai", years=2)
        await reg.update_nameservers("paina.ai", ["a.ns.cloudflare.com", "b.ns.cloudflare.com"])
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.services.credentials_service import get_credentials_service

logger = logging.getLogger(__name__)

API_BASE = "https://api.name.com/core/v1"
DEFAULT_USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"  # 0aw325171@gmail.com
HTTP_TIMEOUT = 30.0


class NameComError(RuntimeError):
    """Name.com API がエラーを返した時の例外。"""

    def __init__(self, status_http: int, message: str, payload: Any = None):
        self.status_http = status_http
        self.payload = payload
        super().__init__(f"Name.com error (HTTP {status_http}): {message}")


def _to_str_price(v: Any) -> Optional[str]:
    if v is None:
        return None
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return None


class NameComRegistrar:
    """Name.com v4 API の薄いラッパー。Cloudflare/Porkbun と互換I/F。"""

    def __init__(self, username: str, token: str) -> None:
        self._auth = (username, token)

    async def _request(self, method: str, path: str, json: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.request(method, f"{API_BASE}{path}", auth=self._auth, json=json)
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code >= 400:
            msg = (data.get("message") or "") + (f": {data.get('details')}" if data.get("details") else "")
            raise NameComError(resp.status_code, msg or resp.text[:200], data)
        return data

    # ---- 空き確認・価格 ----

    async def _check_one(self, domain: str) -> dict[str, Any]:
        data = await self._request("POST", "/domains:checkAvailability", {"domainNames": [domain]})
        results = data.get("results") or []
        return results[0] if results else {}

    async def check_availability(self, domains: list[str]) -> list[dict[str, Any]]:
        """Cloudflare の check_availability と同じ形に正規化して返す。

        各要素に ``reason`` を付ける: ``available`` / ``taken`` / ``unsupported``。
        未対応TLDは Name.com が 422「not valid」を返すので、例外にせず unsupported とする。
        """
        try:
            data = await self._request("POST", "/domains:checkAvailability", {"domainNames": domains})
        except NameComError as e:
            # 422 = 扱っていないTLD（無効ドメイン）。例外にせず unsupported を返す。
            if e.status_http == 422 or "valid" in str(e).lower():
                return [{"name": d, "registrable": False, "tier": "standard",
                         "pricing": None, "reason": "unsupported"} for d in domains]
            raise
        by_name = {r.get("domainName"): r for r in (data.get("results") or [])}
        out: list[dict[str, Any]] = []
        for d in domains:
            r = by_name.get(d)
            if r is None:
                # 結果に無い = そのTLDを扱っていない
                out.append({"name": d, "registrable": False, "tier": "standard",
                            "pricing": None, "reason": "unsupported"})
                continue
            price = _to_str_price(r.get("purchasePrice"))
            renew = _to_str_price(r.get("renewalPrice")) or price
            pricing = (
                {"currency": "USD", "registration_cost": price, "renewal_cost": renew}
                if price is not None else None
            )
            purchasable = bool(r.get("purchasable"))
            out.append({
                "name": d,
                "registrable": purchasable,
                "tier": "premium" if r.get("purchaseType") not in (None, "registration") else "standard",
                "pricing": pricing,
                "reason": "available" if purchasable else "taken",
            })
        return out

    async def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        """候補サジェストは orchestrator 側で Cloudflare 検索に一本化しているので空配列。"""
        return []

    # ---- 購入 ----

    async def register(
        self,
        domain: str,
        *,
        years: int = 1,
        auto_renew: bool = True,
        privacy_mode: str = "redaction",
        contact: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """ドメインを登録。``purchasePrice`` は checkAvailability の見積を渡す
        （Name.com 側で実価格と不一致なら拒否＝過剰請求ガード）。残高が無ければ
        登録済みデフォルト支払いプロファイル(カード)に課金される。
        """
        chk = await self._check_one(domain)
        if not chk.get("purchasable"):
            raise NameComError(200, f"{domain} is not available for registration", chk)
        price = chk.get("purchasePrice")
        if price is None:
            raise NameComError(200, f"{domain}: price unavailable, refusing to register", chk)
        body = {
            "domain": {"domainName": domain},
            "purchasePrice": float(price),
            "purchaseType": "registration",
            "years": max(int(years or 1), 1),
        }
        # Name.com keeps an account address book, but sending the registrant
        # explicitly makes purchase behavior deterministic just like Cloudflare.
        if contact:
            postal = contact.get("postal_info") or {}
            address = postal.get("address") or {}
            name = str(postal.get("name") or "").strip().split(" ", 1)
            body["contacts"] = {"registrant": {
                "firstName": name[0] if name else "",
                "lastName": name[1] if len(name) > 1 else "-",
                "companyName": postal.get("organization") or "",
                "email": contact.get("email"), "phone": contact.get("phone"),
                "address1": address.get("street"), "city": address.get("city"),
                "state": address.get("state"), "zip": address.get("postal_code"),
                "country": address.get("country_code"),
            }}
        return await self._request("POST", "/domains", body)

    async def get_registration_status(self, domain: str) -> dict[str, Any]:
        """Name.com の登録は同期完了。常に active を返す（互換用）。"""
        return {"status": "active", "domain": domain}

    async def list_owned_domains(self) -> set[str]:
        """このアカウントで保有しているドメイン名の集合。"""
        data = await self._request("GET", "/domains")
        return {d.get("domainName") for d in (data.get("domains") or []) if d.get("domainName")}

    # ---- DNS（ネームサーバ / レコード）----

    async def update_nameservers(self, domain: str, nameservers: list[str]) -> dict[str, Any]:
        return await self._request(
            "POST", f"/domains/{domain}:setNameservers", {"nameservers": nameservers}
        )

    async def set_vercel_dns(
        self, domain: str, apex_ip: str = "76.76.21.21",
        cname_target: str = "cname.vercel-dns.com",
    ) -> None:
        """root を Vercel の A、www を Vercel の CNAME に向ける（既存の root A / www は置換）。

        Name.com の NS を保ったまま、DNSレコードだけで Vercel に向ける（NS切替不要）。
        """
        data = await self._request("GET", f"/domains/{domain}/records")
        for r in (data.get("records") or []):
            host = r.get("host") or ""
            is_root_a = r.get("type") == "A" and host in ("", "@")
            is_www = host == "www" and r.get("type") in ("A", "AAAA", "CNAME", "ALIAS")
            if is_root_a or is_www:
                try:
                    await self._request("DELETE", f"/domains/{domain}/records/{r.get('id')}")
                except NameComError:
                    pass
        await self._request("POST", f"/domains/{domain}/records",
                            {"host": "", "type": "A", "answer": apex_ip, "ttl": 300})
        await self._request("POST", f"/domains/{domain}/records",
                            {"host": "www", "type": "CNAME", "answer": cname_target, "ttl": 300})

    async def set_txt_record(self, domain: str, value: str, host: str = "") -> None:
        """TXT レコードを設定（Search Console 所有権確認等）。同 host の既存TXTは置換。"""
        data = await self._request("GET", f"/domains/{domain}/records")
        for r in (data.get("records") or []):
            if r.get("type") == "TXT" and (r.get("host") or "") == host:
                try:
                    await self._request("DELETE", f"/domains/{domain}/records/{r.get('id')}")
                except NameComError:
                    pass
        await self._request("POST", f"/domains/{domain}/records",
                            {"host": host, "type": "TXT", "answer": value, "ttl": 300})


async def get_namecom_registrar(user_id: Optional[str] = None) -> NameComRegistrar:
    """credentials DB から認証情報を取得して :class:`NameComRegistrar` を返す。

    service=namecom で ``{id: username, password: token}`` の形で保存する想定。
    """
    cred = await get_credentials_service().get_credential(
        user_id or DEFAULT_USER_ID, "namecom"
    )
    if not cred or not cred.get("id") or not cred.get("password"):
        raise RuntimeError(
            "Name.com credentials が credentials DB に存在しません。"
            "service=namecom で username(id) と token(password) を保存してください。"
        )
    return NameComRegistrar(username=cred["id"], token=cred["password"])
