"""One factual, inspectable publication state for each artifact.

``artifact_publication`` is the publication ledger.  Its ``job_status`` keeps
the observed external state so the worker, UI, and DAN conversation context do
not independently guess whether a site is live or registered with Google.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.services.artifact_publication_service import ArtifactPublicationService
from app.services.chat_artifact_service import ChatArtifactService


class PublicationStatusService:
    async def reconcile(self, artifact_id: str, *, user_id: Optional[str] = None) -> dict[str, Any]:
        artifacts = ChatArtifactService()
        artifact = (
            await artifacts.get(artifact_id, user_id)
            if user_id
            else (artifacts.supabase.table(artifacts.table).select("*").eq("id", artifact_id).limit(1).execute().data or [None])[0]
        )
        if not artifact:
            raise RuntimeError("Artifact not found")

        ledger = ArtifactPublicationService()
        release = ledger.latest(artifact_id)
        domain = (artifact.get("custom_domain") or (release or {}).get("custom_domain") or "").strip().lower()
        canonical_url = artifact.get("production_url") or (release or {}).get("production_url")
        preview_url = (release or {}).get("shared_url") or artifact.get("share_url") or artifact.get("draft_url")
        domain_status = "live" if domain and artifact.get("publish_status") == "live" else (release or {}).get("domain_status") or artifact.get("publish_status")
        observed: dict[str, Any] = {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "canonical_url": canonical_url,
            "preview_url": preview_url,
            "domain": {"name": domain or None, "status": domain_status},
        }

        if domain:
            from app.tools.publish_site.search_console import inspect_domain_registration

            observed["search_console"] = await inspect_domain_registration(domain)
            try:
                from app.tools.publish_site.vercel_domains import get_vercel

                config = await (await get_vercel(user_id)).get_domain_config(domain)
                observed["vercel"] = {
                    "attached": not bool(config.get("misconfigured", True)),
                    "misconfigured": bool(config.get("misconfigured", True)),
                }
            except Exception as exc:  # The observation remains useful when Vercel is temporarily unavailable.
                observed["vercel"] = {"attached": None, "detail": str(exc)[:180]}

        if release:
            job_status = dict(release.get("job_status") or {})
            job_status["observed"] = observed
            update: dict[str, Any] = {"job_status": job_status}
            if domain:
                update.update({
                    "custom_domain": domain,
                    "production_url": canonical_url or f"https://{domain}",
                    "domain_status": domain_status,
                })
            ledger.supabase.table(ledger.table).update(update).eq("id", release["id"]).execute()
        return observed


_service: Optional[PublicationStatusService] = None


def get_publication_status_service() -> PublicationStatusService:
    global _service
    if _service is None:
        _service = PublicationStatusService()
    return _service
