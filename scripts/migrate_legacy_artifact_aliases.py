"""Move known legacy ``done-artifacts`` aliases to isolated site projects.

Run this once during the shared-publisher retirement.  It never deletes the
legacy project: every alias is re-pointed only after its dedicated deployment
has completed successfully.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from app.services.artifact_publication_service import ArtifactPublicationService
from app.services.chat_artifact_service import ChatArtifactService
from app.tools.publish_site.vercel_domains import get_vercel


# Only aliases with an unambiguous artifact owner are migrated automatically.
# Shared product hosts and ambiguous external domains are intentionally excluded.
ALIASES: dict[str, str] = {
    "kittoku.vercel.app": "kittoku",
    "kittoku-done.vercel.app": "kittoku",
    "kittoku-tokuso.vercel.app": "kittoku",
    "arm-roll-done.vercel.app": "arm-roll",
    "test-edit-done.vercel.app": "test-edit",
    "new-attack-done.vercel.app": "new-attack",
    "yonago-gojo-done.vercel.app": "yonago-gojo",
    "yonago-gojo-v1-done.vercel.app": "yonago-gojo",
    "yonago-gojo-comp-done.vercel.app": "yonago-gojo-comp",
    "aix-dashboard-done.vercel.app": "aix-dashboard",
    "inspection-report-done.vercel.app": "inspection-report",
    "salonboard-monitor-done.vercel.app": "salonboard-monitor",
    "salonboard-styleup-done.vercel.app": "salonboard-styleup",
    "denki-knowledge-done.vercel.app": "denki-knowledge",
    "paina.com": "paina",
}
LEGACY_PROJECT = "done-artifacts"


async def latest_artifact_for_slug(service: ChatArtifactService, slug: str) -> dict | None:
    result = (
        service.supabase.table("chat_artifact")
        .select("*")
        .eq("slug", slug)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


async def main() -> None:
    artifacts = ChatArtifactService()
    publications = ArtifactPublicationService()
    vercel = await get_vercel()
    by_slug: dict[str, list[str]] = {}
    for alias, slug in ALIASES.items():
        by_slug.setdefault(slug, []).append(alias)

    for slug, aliases in by_slug.items():
        artifact = await latest_artifact_for_slug(artifacts, slug)
        if not artifact:
            print(json.dumps({"slug": slug, "status": "skipped", "reason": "artifact not found"}))
            continue
        try:
            release = publications.latest(str(artifact["id"]))
            if not release or not release.get("deployment_project"):
                release = await publications.deploy_dedicated_release(artifact)
            project_id = str(release.get("deployment_project") or "")
            deployments = await vercel.list_deployments(project_id, limit=1)
            if not deployments:
                release = await publications.deploy_dedicated_release(artifact)
                project_id = str(release.get("deployment_project") or "")
                deployments = await vercel.list_deployments(project_id, limit=1)
            deployment_id = str((deployments[0] if deployments else {}).get("uid") or "")
            if not deployment_id or not project_id:
                raise RuntimeError("dedicated deployment did not return an id")
            for alias in aliases:
                # These names were attached as project domains, so the legacy
                # project automatically reclaimed them after a bare alias set.
                # Detach first, then attach to the dedicated owner.
                legacy_domain = await vercel.get_project_domain(LEGACY_PROJECT, alias)
                if legacy_domain is not None:
                    await vercel.remove_domain_from_project(LEGACY_PROJECT, alias)
                current_domain = await vercel.get_project_domain(project_id, alias)
                if current_domain is None:
                    await vercel.add_domain_to_project(project_id, alias)
                await vercel.assign_alias(deployment_id, alias)
                resolved = await vercel._request("GET", f"/v4/aliases/{alias}")
                if resolved.get("projectId") != project_id:
                    raise RuntimeError(f"alias still belongs to {resolved.get('projectId')}")
            now = datetime.now(timezone.utc).isoformat()
            await artifacts.update(
                str(artifact["id"]),
                {
                    "production_url": f"https://{aliases[0]}",
                    "share_url": release.get("shared_url"),
                    "publish_status": "preview_live",
                    "delivery_status": "ready",
                    "last_publish_error": None,
                    "published_at": now,
                },
                str(artifact["created_by"]),
            )
            print(json.dumps({"slug": slug, "status": "migrated", "aliases": aliases}))
        except Exception as exc:  # Continue; an unrelated legacy site must not stop migration.
            publications.mark_failed(str(artifact["id"]), f"legacy alias migration failed: {exc}")
            print(json.dumps({"slug": slug, "status": "failed", "error": str(exc)}))


if __name__ == "__main__":
    asyncio.run(main())
