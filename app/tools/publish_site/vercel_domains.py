"""
Vercel Domains API クライアント

カスタムドメインを Vercel プロジェクトに紐付ける。
Cloudflare Registrar で購入 → DNS設定 → このモジュールで Vercel に attach の順で使用される。

使い方:
    v = await get_vercel()
    await v.add_domain_to_project("yoshikawa-tokuso", "yoshikawa-tokuso.com")
    config = await v.get_domain_config("yoshikawa-tokuso.com")
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

import httpx

from app.services.credentials_service import get_credentials_service

logger = logging.getLogger(__name__)

API_BASE = "https://api.vercel.com"
DEFAULT_USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"  # 0aw325171@gmail.com
HTTP_TIMEOUT = 30.0


class VercelError(RuntimeError):
    """Vercel API がエラーレスポンスを返した時の例外"""

    def __init__(self, status: int, body: Any):
        self.status = status
        self.body = body
        err = body.get("error") if isinstance(body, dict) else body
        super().__init__(f"HTTP {status}: {err}")


class VercelDomains:
    """Vercel Domains API の薄いラッパー。

    team_id を指定するとチームスコープで操作、None だと個人スコープ。
    """

    def __init__(self, token: str, team_id: Optional[str] = None) -> None:
        self.token = token
        self.team_id = team_id
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _params(self, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if self.team_id:
            params["teamId"] = self.team_id
        if extra:
            params.update(extra)
        return params

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        accept_404: bool = False,
    ) -> Any:
        url = f"{API_BASE}{path}"
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.request(
                method, url, headers=self._headers, params=self._params(params), json=json
            )
        if resp.status_code == 404 and accept_404:
            return None
        try:
            body = resp.json()
        except ValueError:
            body = {"error": resp.text[:200]}
        if resp.status_code >= 400:
            raise VercelError(resp.status_code, body)
        return body

    # ---- User / Team / Project 情報 ----

    async def get_user(self) -> dict[str, Any]:
        return (await self._request("GET", "/v2/user"))["user"]

    async def list_teams(self) -> list[dict[str, Any]]:
        return (await self._request("GET", "/v2/teams"))["teams"]

    async def list_projects(self, limit: int = 100) -> list[dict[str, Any]]:
        return (await self._request("GET", "/v9/projects", params={"limit": limit}))["projects"]

    async def get_project(self, project_id_or_name: str) -> dict[str, Any]:
        return await self._request("GET", f"/v9/projects/{project_id_or_name}")

    async def create_project(self, name: str) -> dict[str, Any]:
        """Create an unlinked Next.js project for one artifact.

        Deliberately no Git repository is attached: DAN promotes explicit,
        immutable deployments and a Git provider outage must not publish a
        different version behind its back.
        """
        return await self._request(
            "POST",
            "/v9/projects",
            json={"name": name, "framework": "nextjs"},
        )

    async def create_project_environment_variable(
        self,
        project_id_or_name: str,
        *,
        key: str,
        value: str,
        targets: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Set a build/runtime variable on a dedicated project."""
        return await self._request(
            "POST",
            f"/v10/projects/{project_id_or_name}/env",
            json={
                "key": key,
                "value": value,
                "type": "encrypted",
                "target": targets or ["production", "preview"],
            },
        )

    async def list_deployments(
        self,
        project_id_or_name: str,
        *,
        target: str = "production",
        limit: int = 1,
    ) -> list[dict[str, Any]]:
        """Return recent deployments for a project."""
        result = await self._request(
            "GET",
            "/v6/deployments",
            params={
                "projectId": project_id_or_name,
                "target": target,
                "state": "READY",
                "limit": limit,
            },
        )
        return result.get("deployments", [])

    async def assign_alias(self, deployment_id: str, alias: str) -> dict[str, Any]:
        """Assign a vercel.app alias to a deployment."""
        return await self._request(
            "POST",
            f"/v2/deployments/{deployment_id}/aliases",
            json={"alias": alias, "redirect": None},
        )

    # ---- Project Domains ----

    async def list_project_domains(self, project_id_or_name: str) -> list[dict[str, Any]]:
        """プロジェクトに紐付くドメイン一覧"""
        result = await self._request(
            "GET", f"/v9/projects/{project_id_or_name}/domains"
        )
        return result.get("domains", [])

    async def add_domain_to_project(
        self,
        project_id_or_name: str,
        domain: str,
        *,
        git_branch: Optional[str] = None,
        redirect: Optional[str] = None,
    ) -> dict[str, Any]:
        """ドメインをプロジェクトに紐付ける (Vercel Domains attach)。

        Vercel側で自動的にSSL証明書をプロビジョニングする。
        紐付け後、ドメイン側でDNS設定（A/CNAMEレコード）を別途行う必要がある。
        """
        body: dict[str, Any] = {"name": domain}
        if git_branch is not None:
            body["gitBranch"] = git_branch
        if redirect is not None:
            body["redirect"] = redirect
        return await self._request(
            "POST",
            f"/v10/projects/{project_id_or_name}/domains",
            json=body,
        )

    async def remove_domain_from_project(
        self, project_id_or_name: str, domain: str
    ) -> None:
        """プロジェクトからドメインを外す"""
        await self._request(
            "DELETE", f"/v9/projects/{project_id_or_name}/domains/{domain}"
        )

    async def get_project_domain(
        self, project_id_or_name: str, domain: str
    ) -> Optional[dict[str, Any]]:
        """プロジェクト配下のドメイン詳細"""
        return await self._request(
            "GET",
            f"/v9/projects/{project_id_or_name}/domains/{domain}",
            accept_404=True,
        )

    # ---- Domain Config (DNS verification) ----

    async def get_domain_config(self, domain: str) -> dict[str, Any]:
        """ドメインのDNS構成検証ステータス。

        ``misconfigured: True`` ならユーザー側DNSが未反映。
        Cloudflare DNS で A/CNAME を入れた直後は数十秒〜数分で False になる。
        """
        return await self._request("GET", f"/v6/domains/{domain}/config")


def _detect_team_id() -> Optional[str]:
    """デプロイ先のチーム(org)IDを解決する。

    プロジェクトがチーム配下にあると、個人スコープで API を叩いても
    "Project not found" になるため、チームIDを必ず付けて呼ぶ必要がある。
    """
    env_team = os.getenv("VERCEL_TEAM_ID") or os.getenv("VERCEL_ORG_ID")
    if env_team:
        return env_team
    # .vercel/project.json の orgId が実際のデプロイ先スコープ。
    root = Path(__file__).resolve().parents[3]
    for candidate in (
        root / "frontend" / ".vercel" / "project.json",
        root / ".vercel" / "project.json",
    ):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        org = data.get("orgId")
        if isinstance(org, str) and org.startswith("team_"):
            return org
    return None


async def get_vercel(user_id: Optional[str] = None) -> VercelDomains:
    """credentials DB から token を取得して :class:`VercelDomains` を返す。

    team_id は VERCEL_TEAM_ID か .vercel/project.json の orgId から解決する。
    """
    cred = await get_credentials_service().get_credential(
        user_id or DEFAULT_USER_ID, "vercel"
    )
    if not cred or not cred.get("password"):
        raise RuntimeError(
            "Vercel credentials が credentials DB に存在しません。"
            "service=vercel で token を保存してください。"
        )
    return VercelDomains(token=cred["password"], team_id=_detect_team_id())
