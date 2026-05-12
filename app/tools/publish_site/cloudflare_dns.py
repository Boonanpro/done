"""
Cloudflare DNS API クライアント

Registrar でドメインを購入すると Cloudflare に zone が自動作成される。
このモジュールはその zone に対する DNS レコード操作 (CNAME / A / TXT) を扱う。

使い方:
    dns = await get_cloudflare_dns()
    zone = await dns.get_zone_by_name("example.com")
    await dns.create_record(zone["id"], type="CNAME", name="@", content="cname.vercel-dns.com")
"""
from __future__ import annotations

import logging
from typing import Any, Literal, Optional

import httpx

from app.services.credentials_service import get_credentials_service

logger = logging.getLogger(__name__)

API_BASE = "https://api.cloudflare.com/client/v4"
DEFAULT_USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"
HTTP_TIMEOUT = 30.0

DnsRecordType = Literal["A", "AAAA", "CNAME", "TXT", "MX", "NS", "CAA"]


class CloudflareDNSError(RuntimeError):
    def __init__(self, status: int, errors: list[dict[str, Any]]):
        self.status = status
        self.errors = errors
        super().__init__(
            f"HTTP {status}: " + "; ".join(f"{e.get('code')}: {e.get('message')}" for e in errors)
        )


class CloudflareDNS:
    """zone-scoped DNS レコード操作の薄いラッパー"""

    def __init__(self, token: str) -> None:
        self.token = token
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
    ) -> Any:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.request(
                method, f"{API_BASE}{path}", headers=self._headers, params=params, json=json
            )
        try:
            body = resp.json()
        except ValueError:
            raise CloudflareDNSError(
                resp.status_code, [{"code": -1, "message": resp.text[:200]}]
            )
        if not body.get("success"):
            raise CloudflareDNSError(resp.status_code, body.get("errors", []))
        return body.get("result")

    async def list_zones(self, *, name: Optional[str] = None) -> list[dict[str, Any]]:
        params = {"per_page": 50}
        if name:
            params["name"] = name
        return await self._request("GET", "/zones", params=params)

    async def get_zone_by_name(self, name: str) -> Optional[dict[str, Any]]:
        """ドメイン名で zone を1件取得 (なければ None)"""
        zones = await self.list_zones(name=name)
        return zones[0] if zones else None

    async def list_records(
        self, zone_id: str, *, type: Optional[DnsRecordType] = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"per_page": 100}
        if type:
            params["type"] = type
        return await self._request("GET", f"/zones/{zone_id}/dns_records", params=params)

    async def create_record(
        self,
        zone_id: str,
        *,
        type: DnsRecordType,
        name: str,
        content: str,
        ttl: int = 1,  # 1 = Auto
        proxied: bool = False,
        priority: Optional[int] = None,
        comment: Optional[str] = None,
    ) -> dict[str, Any]:
        """DNS レコード作成。

        Vercel 紐付け時の典型例:
            CNAME @ cname.vercel-dns.com   (apex - Cloudflare の CNAME flattening が効く)
            CNAME www cname.vercel-dns.com
        """
        body: dict[str, Any] = {
            "type": type,
            "name": name,
            "content": content,
            "ttl": ttl,
            "proxied": proxied,
        }
        if priority is not None:
            body["priority"] = priority
        if comment is not None:
            body["comment"] = comment
        return await self._request("POST", f"/zones/{zone_id}/dns_records", json=body)

    async def delete_record(self, zone_id: str, record_id: str) -> None:
        await self._request("DELETE", f"/zones/{zone_id}/dns_records/{record_id}")

    async def upsert_record(
        self,
        zone_id: str,
        *,
        type: DnsRecordType,
        name: str,
        content: str,
        ttl: int = 1,
        proxied: bool = False,
    ) -> dict[str, Any]:
        """同名同タイプのレコードがあれば置き換え、なければ作成"""
        existing = await self.list_records(zone_id, type=type)
        for rec in existing:
            if rec.get("name") == name and rec.get("type") == type:
                await self.delete_record(zone_id, rec["id"])
        return await self.create_record(
            zone_id, type=type, name=name, content=content, ttl=ttl, proxied=proxied
        )


async def get_cloudflare_dns(user_id: Optional[str] = None) -> CloudflareDNS:
    """credentials DB から token を取得して :class:`CloudflareDNS` を返す"""
    cred = await get_credentials_service().get_credential(
        user_id or DEFAULT_USER_ID, "cloudflare"
    )
    if not cred or not cred.get("password"):
        raise RuntimeError("Cloudflare credentials が credentials DB に存在しません")
    return CloudflareDNS(token=cred["password"])
