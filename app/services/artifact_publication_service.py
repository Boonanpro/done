"""The durable publication ledger for generated sites.

``chat_artifact`` answers "what did the user make?".  This service answers
"which concrete release is being delivered, where, and with what result?".
The separation is deliberate: a domain is an optional address of a release,
not the definition of the artifact itself.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.services.supabase_client import get_supabase_client

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
VERCEL = shutil.which("vercel") or shutil.which("vercel.cmd") or "vercel"
DEPLOYMENT_URL_RE = re.compile(r"https://[^\s]+\.vercel\.app")


def current_source_revision() -> str:
    """Return the source revision without making publication depend on a push."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        revision = result.stdout.strip()
        if revision:
            return revision
    except Exception:
        pass
    # A release remains traceable even while GitHub is unavailable.
    return f"workspace:{datetime.now(timezone.utc).isoformat()}"


class ArtifactPublicationService:
    table = "artifact_publication"

    def __init__(self) -> None:
        self.supabase = get_supabase_client().client

    def latest(self, artifact_id: str) -> Optional[dict[str, Any]]:
        result = (
            self.supabase.table(self.table)
            .select("*")
            .eq("artifact_id", artifact_id)
            .order("release_number", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def create_release(self, artifact_id: str, *, source_revision: Optional[str] = None) -> dict[str, Any]:
        latest = self.latest(artifact_id)
        release_number = int(latest["release_number"]) + 1 if latest else 1
        payload = {
            "artifact_id": artifact_id,
            "release_number": release_number,
            "source_revision": source_revision or current_source_revision(),
            "status": "draft",
            "domain_status": "not_requested",
            "job_status": {"phase": "created"},
        }
        result = self.supabase.table(self.table).insert(payload).execute()
        if not result.data:
            raise RuntimeError("publication release could not be recorded")
        return result.data[0]

    def ensure_draft_release(self, artifact_id: str) -> dict[str, Any]:
        latest = self.latest(artifact_id)
        if latest and latest.get("status") in {"draft", "shared", "deploying", "live"}:
            return latest
        # A failed attempt made before the project ID was recorded must not
        # cause the next retry to create a second destination.  Reuse the most
        # recent provisioned release for this artifact; it is the durable
        # identity of the site's Vercel project.
        if latest and not (latest.get("deployment_project") or "").strip():
            previous = (
                self.supabase.table(self.table)
                .select("*")
                .eq("artifact_id", artifact_id)
                .not_.is_("deployment_project", "null")
                .order("release_number", desc=True)
                .limit(1)
                .execute()
            )
            if previous.data:
                return previous.data[0]
        return self.create_release(artifact_id)

    def delivery_project_for(self, artifact_id: str, *, legacy_project: str) -> str:
        """Resolve the target on the server, never from browser input.

        Existing sites still use the documented legacy delivery project until
        they are migrated one by one. A provisioned per-site project always
        wins, so the compatibility rule has a single removable home.
        """
        release = self.latest(artifact_id)
        project = (release or {}).get("deployment_project")
        return project if isinstance(project, str) and project.strip() else legacy_project

    async def provision_dedicated_project(self, artifact: dict[str, Any], *, user_id: Optional[str] = None) -> dict[str, Any]:
        """Create and record the dedicated, Git-unlinked Vercel project.

        Provisioning is idempotent.  It only reserves a delivery target; it
        does not change an existing domain or promote any deployment.
        """
        artifact_id = str(artifact["id"])
        release = self.ensure_draft_release(artifact_id)
        existing = (release.get("deployment_project") or "").strip()
        if existing:
            return release

        from app.tools.publish_site.vercel_domains import VercelError, get_vercel

        slug = re.sub(r"[^a-z0-9-]+", "-", str(artifact.get("slug") or "site").lower()).strip("-") or "site"
        project_name = f"dan-site-{slug[:34]}-{artifact_id.replace('-', '')[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        created_project = False
        try:
            vercel = await get_vercel(user_id)
            try:
                project = await vercel.create_project(project_name)
                created_project = True
            except VercelError as exc:
                # A prior process can have created the project but failed before
                # writing its ID to the ledger.  Recover that exact project;
                # never invent a second destination for the same artifact.
                if exc.status != 409:
                    raise
                project = await vercel.get_project(project_name)
            project_id = str(project.get("id") or project.get("name") or project_name)
            # This variable makes the same frontend source a one-site delivery
            # application in this project, without global host routing.
            if created_project:
                await vercel.create_project_environment_variable(
                    project_id, key="ARTIFACT_ONLY_SLUG", value=slug
                )
        except Exception as exc:
            self.mark_failed(artifact_id, f"dedicated project provisioning failed: {exc}")
            raise

        result = (
            self.supabase.table(self.table)
            .update(
                {
                    "deployment_provider": "vercel",
                    "deployment_project": project_id,
                    "status": "draft",
                    "job_status": {
                        "phase": "project_provisioned",
                        "project_name": project_name,
                        "completed_at": now,
                    },
                    "last_error": None,
                }
            )
            .eq("id", release["id"])
            .execute()
        )
        return result.data[0] if result.data else {**release, "deployment_project": project_id}

    async def deploy_dedicated_release(self, artifact: dict[str, Any], *, user_id: Optional[str] = None) -> dict[str, Any]:
        """Deploy locally to the site's project, verify it, then promote it.

        The CLI receives explicit project/team IDs and never writes the shared
        frontend's ``.vercel/project.json``.  ``--skip-domain`` prevents a new
        build from becoming live before its immutable deployment URL succeeds.
        """
        artifact_id = str(artifact["id"])
        release = await self.provision_dedicated_project(artifact, user_id=user_id)
        project_id = str(release["deployment_project"])
        from app.tools.publish_site.vercel_domains import get_vercel

        vercel = await get_vercel(user_id)
        # Older saved Vercel credentials may contain a token but no team ID.
        # The project itself still belongs to DAN's configured Vercel team, so
        # retain the process-level team fallback instead of overwriting it with
        # an empty string.  Without this, a perfectly valid dedicated project
        # cannot be redeployed after a credential migration.
        vercel_team_id = vercel.team_id or os.environ.get("VERCEL_ORG_ID") or os.environ.get("VERCEL_TEAM_ID") or ""
        env = os.environ.copy()
        env.update(
            {
                "VERCEL_TOKEN": vercel.token,
                "VERCEL_PROJECT_ID": project_id,
                "VERCEL_ORG_ID": vercel_team_id,
                "ARTIFACT_ONLY_SLUG": str(artifact.get("slug") or ""),
            }
        )
        self.mark_deploying(artifact_id)
        cmd = [VERCEL, "deploy", "--prod", "--yes", "--force", "--skip-domain"]
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            cwd=str(FRONTEND_ROOT),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=1800,
        )
        output = proc.stdout or ""
        if proc.returncode != 0:
            self.mark_failed(artifact_id, f"dedicated Vercel deploy failed: {output[-1500:]}")
            raise RuntimeError(f"dedicated Vercel deploy failed: {output[-1500:]}")
        urls = DEPLOYMENT_URL_RE.findall(output)
        if not urls:
            self.mark_failed(artifact_id, "Vercel deploy completed without a deployment URL")
            raise RuntimeError("Vercel deploy completed without a deployment URL")
        deployment_url = urls[-1].rstrip("/")
        # A READY deployment is then explicitly promoted.  Existing production
        # aliases remain untouched until this point.
        promote = await asyncio.to_thread(
            subprocess.run,
            [VERCEL, "promote", deployment_url, "--yes"],
            cwd=str(FRONTEND_ROOT),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=240,
        )
        if promote.returncode != 0:
            self.mark_failed(artifact_id, f"Vercel promotion failed: {(promote.stdout or '')[-1500:]}")
            raise RuntimeError("Vercel deployment was built but could not be promoted")
        now = datetime.now(timezone.utc).isoformat()
        project = await vercel.get_project(project_id)
        project_name = str(project.get("name") or project_id)
        shared_url = f"https://{project_name}.vercel.app"
        result = (
            self.supabase.table(self.table)
            .update(
                {
                    "status": "shared",
                    "deployment_id": deployment_url,
                    "shared_url": shared_url,
                    "published_at": now,
                    "last_error": None,
                    "job_status": {
                        "phase": "promoted",
                        "deployment_url": deployment_url,
                        "promoted_at": now,
                    },
                }
            )
            .eq("id", release["id"])
            .execute()
        )
        return result.data[0] if result.data else {**release, "shared_url": shared_url}

    def mark_shared(self, artifact_id: str, shared_url: str) -> Optional[dict[str, Any]]:
        release = self.ensure_draft_release(artifact_id)
        now = datetime.now(timezone.utc).isoformat()
        result = (
            self.supabase.table(self.table)
            .update(
                {
                    "status": "shared",
                    "shared_url": shared_url,
                    "published_at": now,
                    "last_error": None,
                    "job_status": {"phase": "shared", "completed_at": now},
                }
            )
            .eq("id", release["id"])
            .execute()
        )
        return result.data[0] if result.data else None

    def mark_deploying(self, artifact_id: str) -> Optional[dict[str, Any]]:
        release = self.ensure_draft_release(artifact_id)
        now = datetime.now(timezone.utc).isoformat()
        result = (
            self.supabase.table(self.table)
            .update(
                {
                    "status": "deploying",
                    "last_error": None,
                    "job_status": {"phase": "deploying", "started_at": now},
                }
            )
            .eq("id", release["id"])
            .execute()
        )
        return result.data[0] if result.data else None

    def mark_failed(self, artifact_id: str, message: str) -> Optional[dict[str, Any]]:
        release = self.ensure_draft_release(artifact_id)
        now = datetime.now(timezone.utc).isoformat()
        result = (
            self.supabase.table(self.table)
            .update(
                {
                    "status": "failed",
                    "last_error": message[-1500:],
                    "job_status": {"phase": "failed", "failed_at": now},
                }
            )
            .eq("id", release["id"])
            .execute()
        )
        return result.data[0] if result.data else None


def schedule_dedicated_deploy(artifact_id: str, user_id: str) -> None:
    """Publish one newly-created artifact to its own Vercel project.

    This deliberately replaces the former shared ``done-artifacts`` Git push.
    The job is detached from the chat response, but it has one concrete target:
    the project recorded for this artifact in ``artifact_publication``.
    """
    async def run() -> None:
        from app.services.chat_artifact_service import ChatArtifactService

        artifacts = ChatArtifactService()
        artifact = await artifacts.get(artifact_id, user_id)
        if not artifact:
            return
        try:
            release = await ArtifactPublicationService().deploy_dedicated_release(
                artifact, user_id=user_id
            )
            await artifacts.update(
                artifact_id,
                {
                    "share_url": release.get("shared_url"),
                    "draft_url": release.get("shared_url"),
                    "publish_status": "preview_live",
                    "delivery_status": "ready",
                    "last_publish_error": None,
                },
                user_id,
            )
        except Exception as exc:  # The ledger records the exact deployment failure.
            await artifacts.update(
                artifact_id,
                {
                    "publish_status": "failed",
                    "delivery_status": "failed",
                    "last_publish_error": str(exc)[-1500:],
                },
                user_id,
            )

    def worker() -> None:
        asyncio.run(run())

    # Registration is called from both async HTTP handlers and CLI/SSE code.
    # A thread gives both callers the same detached, dedicated delivery job.
    threading.Thread(
        target=worker,
        name=f"artifact-deploy-{artifact_id[:8]}",
        daemon=True,
    ).start()
