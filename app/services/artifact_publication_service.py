"""The durable publication ledger for generated sites.

``chat_artifact`` answers "what did the user make?".  This service answers
"which concrete release is being delivered, where, and with what result?".
The separation is deliberate: a domain is an optional address of a release,
not the definition of the artifact itself.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import settings
from app.services.supabase_client import get_supabase_client

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
VERCEL = shutil.which("vercel") or shutil.which("vercel.cmd") or "vercel"
DEPLOYMENT_URL_RE = re.compile(r"https://[^\s]+\.vercel\.app")


def public_backend_urls() -> dict[str, str]:
    """Publicly reachable addresses of DAN's own backends.

    A dedicated artifact site rewrites ``/api/*`` to these at BUILD time
    (``frontend/next.config.mjs``).  When they are absent the build falls back
    to ``http://127.0.0.1:8000``, and every tool call from the published site
    dies with ``404 DNS_HOSTNAME_RESOLVED_PRIVATE`` — the site loads but nothing
    inside it works.  Only public ``https://`` values are returned: writing a
    loopback address into a Vercel project is worse than leaving the previous
    value, which at least pointed somewhere real.
    """
    urls: dict[str, str] = {}
    for key, filename in (
        ("BACKEND_URL", ".tunnel_sandbox_url"),
        ("CORE_BACKEND_URL", ".tunnel_core_url"),
    ):
        try:
            value = (PROJECT_ROOT / filename).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value.startswith("https://"):
            urls[key] = value
    return urls


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
        # A failed attempt must be retried against the SAME provisioned target.
        # The ledger holds one row per delivery project (unique index on
        # deployment_provider + deployment_project), so opening a second row for
        # an artifact whose project already exists can never be provisioned: the
        # retry dies on a duplicate key instead of redeploying. Status is about
        # the last attempt; the project is the durable identity of the site.
        if latest and (latest.get("deployment_project") or "").strip():
            return latest
        if latest and latest.get("status") in {"draft", "shared", "deploying", "live"}:
            return latest
        return self.create_release(artifact_id)

    def mark_interrupted(self, artifact_id: str, *, reason: str) -> None:
        """Return an interrupted hand-off to its last known serving state.

        A caller process may be stopped after `mark_deploying` but before it
        starts a Vercel build.  Leaving that record as "deploying" makes the
        delivery ledger lie forever.  The existing immutable deployment stays
        live, so this is a truthful state repair rather than a retry.
        """
        now = datetime.now(timezone.utc).isoformat()
        self.supabase.table(self.table).update(
            {
                "status": "shared",
                "job_status": {"phase": "interrupted", "recovered_at": now, "reason": reason},
                "last_error": reason,
            }
        ).eq("artifact_id", artifact_id).eq("status", "deploying").execute()

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

    def write_release_snapshot(self, artifact_slug: str) -> Optional[Path]:
        """最新の公開リビジョンを成果物ディレクトリの release.gen.json に焼き込む。

        配信ページはこのファイルを build 時に取り込み、初回 HTML に公開済み編集を
        描画する（frontend/src/lib/editable-release.ts）。ここで焼き込む＝デプロイ
        成果物そのものに内容が入るので、配信は実行時に DB を読む必要がない。
        リビジョンが1つも無ければ空 JSON を書く（「公開済み編集なし」も正しい状態）。
        """
        slug = artifact_slug.strip().lower()
        # ディレクトリ名として安全な slug だけを受け付ける（パストラバーサル防止）。
        if not slug or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
            return None
        artifact_dir = FRONTEND_ROOT / "src" / "app" / "artifacts" / slug
        if not artifact_dir.is_dir():
            return None
        result = (
            self.supabase.table("artifact_edit_releases")
            .select("overrides")
            .eq("artifact_slug", slug)
            .order("revision", desc=True)
            .limit(1)
            .execute()
        )
        overrides = (result.data[0].get("overrides") if result.data else None) or {}
        path = artifact_dir / "release.gen.json"
        tmp = artifact_dir / "release.gen.json.tmp"
        tmp.write_text(
            json.dumps(overrides, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
        # 書きかけのファイルを next build が読まないよう、完成後に置き換える。
        tmp.replace(path)
        return path

    async def deploy_dedicated_release(self, artifact: dict[str, Any], *, user_id: Optional[str] = None) -> dict[str, Any]:
        """Deploy locally to the site's project, verify it, then promote it.

        The CLI receives explicit project/team IDs and never writes the shared
        frontend's ``.vercel/project.json``.  ``--skip-domain`` prevents a new
        build from becoming live before its immutable deployment URL succeeds.

        同一 artifact のデプロイは直列化される。呼び出し口は複数ある
        （インスペクタ公開 / チャットの「公開して」/ 登録時自動公開）ため、
        並走を許すと古いビルドが新しいビルドの後に promote される競合が起きる。
        後から来た呼び出しはロック待ちの間に進んだ最新のソース＋最新リビジョンを
        焼き直すので、待たされても結果は常に「全変更を含む最終状態」になる。
        """
        artifact_id = str(artifact["id"])
        serial_lock = _deploy_serial_lock(artifact_id)
        # threading.Lock を event loop を塞がずに獲得する（デプロイは分単位）。
        await asyncio.to_thread(serial_lock.acquire)
        try:
            return await self._deploy_dedicated_release_locked(artifact, user_id=user_id)
        finally:
            serial_lock.release()

    async def _deploy_dedicated_release_locked(self, artifact: dict[str, Any], *, user_id: Optional[str] = None) -> dict[str, Any]:
        artifact_id = str(artifact["id"])
        release = await self.provision_dedicated_project(artifact, user_id=user_id)
        project_id = str(release["deployment_project"])
        from app.tools.publish_site.vercel_domains import VercelError, get_vercel

        vercel = await get_vercel(user_id)
        # Every dedicated site must be able to read published revisions without
        # a tunnel to DAN. These are public Supabase browser credentials; the
        # database policy exposes only completed releases. Existing projects
        # receive them lazily on their next deployment as well.
        for key, value in (
            ("NEXT_PUBLIC_SUPABASE_URL", settings.SUPABASE_URL),
            ("NEXT_PUBLIC_SUPABASE_ANON_KEY", settings.SUPABASE_KEY),
        ):
            try:
                await vercel.create_project_environment_variable(project_id, key=key, value=value)
            except VercelError as exc:
                if exc.status not in (400, 409) or "ENV_CONFLICT" not in str(exc):
                    raise
        # Tools inside a dedicated site talk to DAN through /api/*, which is
        # rewritten to these addresses when the site is built.  They are
        # upserted, not created: the quick tunnel hostname changes on every PC
        # reboot, so a create-only call would pin every published tool to a dead
        # address until someone noticed by hand.
        for key, value in public_backend_urls().items():
            await vercel.create_project_environment_variable(
                project_id, key=key, value=value, upsert=True
            )
        # Older saved Vercel credentials may contain a token but no team ID.
        # The project itself still belongs to DAN's configured Vercel team, so
        # retain the process-level team fallback instead of overwriting it with
        # an empty string.  Without this, a perfectly valid dedicated project
        # cannot be redeployed after a credential migration.
        vercel_team_id = vercel.team_id or os.environ.get("VERCEL_ORG_ID") or os.environ.get("VERCEL_TEAM_ID") or ""
        # デプロイ直前に最新の公開リビジョンをビルドへ焼き込む。これが配信内容の
        # 唯一の供給路（配信ページは実行時に DB を読まない）。
        self.write_release_snapshot(str(artifact.get("slug") or ""))
        env = os.environ.copy()
        env.update(
            {
                "VERCEL_TOKEN": vercel.token,
                "VERCEL_PROJECT_ID": project_id,
                "VERCEL_ORG_ID": vercel_team_id,
                "ARTIFACT_ONLY_SLUG": str(artifact.get("slug") or ""),
                # A dedicated delivery project needs no live tunnel or shared
                # backend. These are Supabase's public browser credentials;
                # RLS exposes only completed edit releases, never drafts.
                "NEXT_PUBLIC_SUPABASE_URL": settings.SUPABASE_URL,
                "NEXT_PUBLIC_SUPABASE_ANON_KEY": settings.SUPABASE_KEY,
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
        # Vercel truncates the generated ``*.vercel.app`` host when the project
        # name is long (e.g. ``dan-site-oku-yukadanbou-real-5854b034`` is served
        # from ``dan-site-oku-yukadanbou-real-5854b0.vercel.app``).  Composing the
        # URL from the project name therefore hands out a DEPLOYMENT_NOT_FOUND
        # address.  Ask the project which host it actually serves.
        shared_url = f"https://{project_name}.vercel.app"
        try:
            domains = await vercel.list_project_domains(project_id)
            generated = [
                str(d.get("name"))
                for d in domains or []
                if str(d.get("apexName") or "") == "vercel.app" and not d.get("redirect")
            ]
            if generated:
                # Prefer the host derived from the project's own name.  Picking
                # merely the shortest host hands out a retired alias when one is
                # still attached (``<slug>-done.vercel.app`` is shorter than
                # ``dan-site-<slug>-<id>.vercel.app`` but is exactly the URL that
                # must no longer be advertised).  Among the project's own hosts
                # the shortest is the plain alias; longer ones carry the team
                # suffix.
                own = [
                    host
                    for host in generated
                    if project_name.startswith(host.split(".", 1)[0])
                ]
                shared_url = f"https://{min(own or generated, key=len)}"
        except Exception:
            # A naming-derived URL is still better than failing a live release.
            pass
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


# 公開ボタンの連打で Vercel ビルドを積み上げないための合流表。
# artifact_id ごとに「実行中か」「実行中にもう1回頼まれたか」だけを持つ。
# 実行中に来た依頼は「もう1回」フラグに畳まれ、走行中のジョブが終わった直後に
# 1回だけ追加実行される（最新スナップショットを焼き直すので取りこぼしは無い）。
_DEPLOY_COALESCE_LOCK = threading.Lock()
_DEPLOY_COALESCE: dict[str, dict[str, bool]] = {}

# deploy_dedicated_release 本体の直列化ロック（artifact_id ごと）。
# 合流表はスケジューラ経由の依頼だけを畳む。直接呼び出し（チャットの「公開して」等）
# との並走はこちらで防ぐ。
_DEPLOY_SERIAL_LOCKS: dict[str, threading.Lock] = {}


def _deploy_serial_lock(artifact_id: str) -> threading.Lock:
    with _DEPLOY_COALESCE_LOCK:
        return _DEPLOY_SERIAL_LOCKS.setdefault(artifact_id, threading.Lock())


def schedule_dedicated_deploy(artifact_id: str, user_id: str) -> None:
    """Publish one newly-created artifact to its own Vercel project.

    This deliberately replaces the former shared ``done-artifacts`` Git push.
    The job is detached from the chat response, but it has one concrete target:
    the project recorded for this artifact in ``artifact_publication``.
    """
    with _DEPLOY_COALESCE_LOCK:
        state = _DEPLOY_COALESCE.get(artifact_id)
        if state and state.get("running"):
            state["again"] = True
            return
        _DEPLOY_COALESCE[artifact_id] = {"running": True, "again": False}

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
        while True:
            asyncio.run(run())
            with _DEPLOY_COALESCE_LOCK:
                state = _DEPLOY_COALESCE.get(artifact_id) or {}
                if state.get("again"):
                    # 走行中に来た公開依頼をここで1回に畳んで実行し直す。
                    state["again"] = False
                    continue
                state["running"] = False
                break

    # Registration is called from both async HTTP handlers and CLI/SSE code.
    # A thread gives both callers the same detached, dedicated delivery job.
    threading.Thread(
        target=worker,
        name=f"artifact-deploy-{artifact_id[:8]}",
        daemon=True,
    ).start()


def resync_dedicated_sites_after_tunnel_change() -> list[str]:
    """Rebuild every dedicated site against the current public backend address.

    ``next.config.mjs`` resolves ``/api/*`` at build time, so a published tool
    keeps talking to whatever address existed when it was last built.  The quick
    tunnel hostname changes on every PC reboot, which silently turns each
    published tool into a page that loads and then fails on the first action
    (404 ``DNS_HOSTNAME_RESOLVED_PRIVATE``).  Rebuilding here is what keeps a
    delivered site usable across reboots.

    Returns the artifact ids whose rebuild was scheduled.
    """
    if not public_backend_urls():
        # No public address known yet — rebuilding now would bake in loopback.
        return []
    service = ArtifactPublicationService()
    releases = (
        service.supabase.table(service.table)
        .select("artifact_id,deployment_project")
        .execute()
    )
    artifact_ids = {
        str(row["artifact_id"])
        for row in (releases.data or [])
        if row.get("deployment_project") and row.get("artifact_id")
    }
    if not artifact_ids:
        return []
    owners = (
        service.supabase.table("chat_artifact")
        .select("id,created_by")
        .in_("id", sorted(artifact_ids))
        .execute()
    )
    targets = [
        (str(row["id"]), str(row["created_by"]))
        for row in (owners.data or [])
        if row.get("created_by")
    ]
    if not targets:
        return []

    async def rebuild_all() -> None:
        from app.services.chat_artifact_service import ChatArtifactService

        artifacts = ChatArtifactService()
        for artifact_id, owner_id in targets:
            artifact = await artifacts.get(artifact_id, owner_id)
            if not artifact:
                continue
            try:
                await service.deploy_dedicated_release(artifact, user_id=owner_id)
            except Exception:
                # One unpublishable site must not strand the remaining ones.
                continue

    # Serial, not one thread per site: every dedicated project is deployed from
    # the same frontend directory, and concurrent `vercel deploy` runs there
    # collide and exit 1.
    threading.Thread(
        target=lambda: asyncio.run(rebuild_all()),
        name="artifact-deploy-tunnel-resync",
        daemon=True,
    ).start()
    return [artifact_id for artifact_id, _ in targets]
