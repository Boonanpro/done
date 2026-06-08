"""Deploy frontend and point artifact delivery aliases at the new deployment.

Usage:
    python scripts/deploy_frontend_artifacts.py
    python scripts/deploy_frontend_artifacts.py salonboard-styleup kittoku

The Vercel deployment URL (frontend-*.vercel.app) is an internal build target.
Client-facing artifact URLs are always https://<slug>-done.vercel.app/.

Reliability guarantees (so "registered == published" actually holds):
  * Global lock — only one whole-frontend deploy runs at a time. Concurrent
    `vercel deploy --prod` of the same project collide and exit 1, which used to
    leave the alias unassigned (-> 404 DEPLOYMENT_NOT_FOUND).
  * Coalescing — a deploy that just succeeded is reused for alias assignment
    instead of redeploying the whole frontend again.
  * Retry with backoff on transient deploy failures.
  * Alias health check — the alias must answer 2xx/3xx before we mark the
    artifact `ready`. Until then we never claim it is published.
  * Failures are recorded to `chat_artifact.last_publish_error` and printed in
    full, instead of being swallowed by `check=True`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = ROOT / "frontend" / "src" / "app" / "artifacts"
DEPLOYMENT_RE = re.compile(r"https://frontend-[^\s]+\.vercel\.app")
VERCEL = shutil.which("vercel") or shutil.which("vercel.cmd") or "vercel"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TMP_DIR = ROOT / ".tmp"
GLOBAL_LOCK = TMP_DIR / "artifact_deploy_global.lock"
LAST_DEPLOY_CACHE = TMP_DIR / "artifact_last_deploy.json"
GLOBAL_LOCK_TIMEOUT = 900        # max seconds to wait for another deploy to finish
GLOBAL_LOCK_STALE = 1200         # treat a lock older than this as crashed
COALESCE_WINDOW = 150            # reuse a deployment this fresh instead of redeploying
DEPLOY_ATTEMPTS = 3
ALIAS_HEALTH_ATTEMPTS = 12
ALIAS_HEALTH_DELAY = 6


def artifact_slugs() -> list[str]:
    slugs: list[str] = []
    for path in sorted(ARTIFACTS_DIR.iterdir()):
        if path.name.startswith("_") or path.name == "publish":
            continue
        if (path / "page.tsx").exists():
            slugs.append(path.name)
    return slugs


def _emit(text: str) -> None:
    sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
    if text and not text.endswith("\n"):
        sys.stdout.buffer.write(b"\n")
    sys.stdout.flush()


def run(cmd: list[str]) -> str:
    """Run a command, stream output, and raise on non-zero exit (alias step)."""
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    _emit(proc.stdout or "")
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, proc.stdout)
    return proc.stdout


# ---------------------------------------------------------------------------
# Global serialization + coalescing
# ---------------------------------------------------------------------------

def acquire_global_lock() -> bool:
    TMP_DIR.mkdir(exist_ok=True)
    start = time.monotonic()
    while True:
        try:
            fd = os.open(str(GLOBAL_LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                age = time.time() - GLOBAL_LOCK.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > GLOBAL_LOCK_STALE:
                _emit(f"[artifact-deploy] removing stale global lock (age={int(age)}s)")
                try:
                    GLOBAL_LOCK.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() - start > GLOBAL_LOCK_TIMEOUT:
                _emit("[artifact-deploy] timed out waiting for the global deploy lock")
                return False
            time.sleep(3)


def release_global_lock() -> None:
    try:
        GLOBAL_LOCK.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:  # noqa: BLE001
        _emit(f"[artifact-deploy] failed to release global lock: {e}")


def recent_deployment() -> str | None:
    try:
        data = json.loads(LAST_DEPLOY_CACHE.read_text(encoding="utf-8"))
        if time.time() - float(data["ts"]) < COALESCE_WINDOW:
            return str(data["deployment"])
    except Exception:  # noqa: BLE001 - cache is best-effort
        pass
    return None


def record_deployment(deployment: str) -> None:
    try:
        TMP_DIR.mkdir(exist_ok=True)
        LAST_DEPLOY_CACHE.write_text(
            json.dumps({"deployment": deployment, "ts": time.time()}),
            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001
        _emit(f"[artifact-deploy] failed to cache deployment: {e}")


def deploy_prod() -> tuple[str | None, str]:
    """Deploy the whole frontend with retry. Returns (deployment_url, last_output)."""
    last_output = ""
    for attempt in range(1, DEPLOY_ATTEMPTS + 1):
        _emit(f"[artifact-deploy] vercel deploy --prod (attempt {attempt}/{DEPLOY_ATTEMPTS})")
        proc = subprocess.run(
            [VERCEL, "deploy", "--prod", "--yes"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        out = proc.stdout or ""
        _emit(out)
        last_output = out
        if proc.returncode == 0:
            matches = DEPLOYMENT_RE.findall(out)
            if matches:
                return matches[-1], out
            _emit("[artifact-deploy] deploy succeeded but no deployment URL found")
        else:
            _emit(f"[artifact-deploy] deploy attempt {attempt} failed (exit {proc.returncode})")
        if attempt < DEPLOY_ATTEMPTS:
            time.sleep(min(45, 10 * attempt))
    return None, last_output


# ---------------------------------------------------------------------------
# Alias health + DB status
# ---------------------------------------------------------------------------

def alias_is_live(alias: str) -> bool:
    """Poll the alias until it answers, so we never claim an unpublished URL."""
    url = f"https://{alias}/"
    for _ in range(ALIAS_HEALTH_ATTEMPTS):
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "dan-deploy-check"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                if 200 <= resp.status < 400:
                    return True
        except Exception:  # noqa: BLE001 - propagation/DNS lag is expected right after alias set
            pass
        time.sleep(ALIAS_HEALTH_DELAY)
    return False


def _supabase():
    from app.services.supabase_client import get_supabase_client

    return get_supabase_client().client


def mark_alias_ready(slug: str, alias: str, deployment: str) -> None:
    """Best-effort DB update after a stable artifact alias is verified live."""
    try:
        sb = _supabase()
        public_url = f"https://{alias}/"
        now = datetime.now(timezone.utc).isoformat()
        rows = (
            sb.table("chat_artifact")
            .select("id, delivery_checklist")
            .eq("slug", slug)
            .execute()
            .data
            or []
        )
        for row in rows:
            checklist = row.get("delivery_checklist") if isinstance(row, dict) else {}
            if not isinstance(checklist, dict):
                checklist = {}
            profile = checklist.get("public_profile")
            if not isinstance(profile, dict):
                profile = {}
            checklist = {
                **checklist,
                "delivery_url": public_url,
                "deployment_url": deployment,
                "deployed_at": now,
                "public_profile": {
                    **profile,
                    "artifact_slug": slug,
                    "public_url": public_url,
                    "alias_domain": alias,
                    "start_url": f"/preview/{slug}",
                    "scope": f"/preview/{slug}",
                },
            }
            (
                sb.table("chat_artifact")
                .update(
                    {
                        "production_url": public_url,
                        "delivery_status": "ready",
                        "delivery_mode": "preview_share",
                        "delivery_checklist": checklist,
                        "last_publish_error": None,
                        "published_at": now,
                    }
                )
                .eq("id", row["id"])
                .execute()
            )
    except Exception as e:  # noqa: BLE001 - alias success is more important than metadata
        print(f"[artifact-alias] DB update failed for {slug}: {e}", file=sys.stderr)


def mark_publish_failed(slugs: list[str], error_output: str) -> None:
    """Record a deploy/alias failure so the card stops claiming it is published."""
    message = (error_output or "").strip()
    # Keep the tail — vercel prints the actual error near the end.
    message = message[-1500:] if message else "deploy failed (no output captured)"
    try:
        sb = _supabase()
        for slug in slugs:
            try:
                (
                    sb.table("chat_artifact")
                    .update(
                        {
                            "delivery_status": "error",
                            "last_publish_error": message,
                        }
                    )
                    .eq("slug", slug)
                    .execute()
                )
            except Exception as e:  # noqa: BLE001
                print(f"[artifact-alias] failed to record error for {slug}: {e}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[artifact-alias] could not reach DB to record failure: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _deploy_and_alias(slugs: list[str]) -> int:
    deployment = recent_deployment()
    if deployment:
        _emit(f"[artifact-deploy] reusing recent deployment {deployment}")
    else:
        deployment, out = deploy_prod()
        if not deployment:
            _emit("[artifact-deploy] all deploy attempts failed — marking artifacts as errored")
            mark_publish_failed(slugs, out)
            return 1
        record_deployment(deployment)

    failures: list[str] = []
    for slug in slugs:
        alias = f"{slug}-done.vercel.app"
        try:
            run([VERCEL, "alias", "set", deployment, alias])
        except subprocess.CalledProcessError as e:
            _emit(f"[artifact-alias] alias assignment failed for {slug}")
            mark_publish_failed([slug], e.output or f"vercel alias set failed for {alias}")
            failures.append(slug)
            continue
        if not alias_is_live(alias):
            _emit(f"[artifact-alias] {alias} did not respond after assignment — marking errored")
            mark_publish_failed([slug], f"alias {alias} assigned but not reachable")
            failures.append(slug)
            continue
        mark_alias_ready(slug, alias, deployment)
        _emit(f"[artifact-alias] https://{alias} -> {deployment} (live)")

    _emit("\nClient-facing URLs:")
    for slug in slugs:
        status = "FAILED" if slug in failures else "live"
        _emit(f"  https://{slug}-done.vercel.app/  [{status}]")
    return 1 if failures else 0


def main() -> int:
    slugs = sys.argv[1:] or artifact_slugs()
    if not slugs:
        print("No artifact slugs found.", file=sys.stderr)
        return 1

    if not acquire_global_lock():
        # Another deploy is in flight; it deploys the whole frontend (all slugs
        # on disk), so our artifacts are covered. Surface non-zero so the caller
        # can see we deferred, but do not flag the artifacts as errored.
        _emit("[artifact-deploy] another deploy holds the global lock; deferring")
        return 1
    try:
        return _deploy_and_alias(slugs)
    finally:
        release_global_lock()


if __name__ == "__main__":
    raise SystemExit(main())
