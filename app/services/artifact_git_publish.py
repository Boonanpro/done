"""Publish chat artifacts to production by committing them to ``main``.

An artifact's provisional public URL is ``<host>/preview/<slug>``, served by the
production frontend deployment (Vercel builds the ``main`` branch). So
"registered == published" means the artifact's files must reach ``main``.

This module commits ONLY a single artifact's files (scope ``artifact:<slug>``)
on a dedicated *detached* ``main`` worktree under ``.tmp/publish-main`` — it
never touches the developer's working tree or current branch — pushes to
``origin/main``, then waits for ``/preview/<slug>`` to answer before marking the
``chat_artifact`` row ready. Failures are recorded to ``last_publish_error``
instead of being swallowed.

The legacy ``<slug>-done.vercel.app`` alias path is intentionally not used; the
clean single delivery URL is ``<host>/preview/<slug>`` (see RULES.md).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TMP_DIR = PROJECT_ROOT / ".tmp"
WORKTREE_DIR = TMP_DIR / "publish-main"
GLOBAL_LOCK = TMP_DIR / "artifact_git_publish.lock"
PUBLISH_LOG = PROJECT_ROOT / "artifact_git_publish.log"

# Production host whose /preview/<slug> serves the artifact (Vercel `main`).
PUBLISH_HOST = (
    os.environ.get("DAN_PUBLISH_HOST")
    or "https://frontend-mikis-projects-86652663.vercel.app"
).rstrip("/")

PUSH_BRANCH = os.environ.get("DAN_PUBLISH_BRANCH", "main")

GLOBAL_LOCK_TIMEOUT = 900
GLOBAL_LOCK_STALE = 1800
PUSH_ATTEMPTS = 3
LIVE_CHECK_ATTEMPTS = 20
LIVE_CHECK_DELAY = 6


# ---------------------------------------------------------------------------
# Which files belong to a slug
# ---------------------------------------------------------------------------

def artifact_files_for_slug(slug: str) -> list[str]:
    """Return repo-relative paths on disk that belong to ``artifact:<slug>``."""
    from scripts.scope_classifier import _PUBLIC_DIR_TO_OWNER  # type: ignore

    roots: list[str] = [
        f"frontend/src/app/artifacts/{slug}",
        f"frontend/src/app/api/{slug}",
        f"frontend/public/{slug}",
        f"frontend/public/artifacts/{slug}",
    ]
    # Public asset dirs whose name differs from the slug (e.g. kittoku->kikkawa).
    for pubdir, owner in _PUBLIC_DIR_TO_OWNER.items():
        if owner.kind == "artifact" and owner.name == slug:
            roots.append(f"frontend/public/{pubdir}")

    seen: set[str] = set()
    existing: list[str] = []
    for rel in roots:
        if rel in seen:
            continue
        seen.add(rel)
        if (PROJECT_ROOT / rel).exists():
            existing.append(rel)
    return existing


# ---------------------------------------------------------------------------
# Subprocess + logging helpers
# ---------------------------------------------------------------------------

def _emit(message: str) -> None:
    logger.info(message)
    try:
        with PUBLISH_LOG.open("a", encoding="utf-8") as fh:
            fh.write(message.rstrip("\n") + "\n")
    except Exception:  # noqa: BLE001
        pass


def _git(args: list[str], cwd: Path, *, check: bool = True, timeout: int = 300) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, args, proc.stdout)
    return proc


# ---------------------------------------------------------------------------
# Global serialization (one push to main at a time)
# ---------------------------------------------------------------------------

def _acquire_lock() -> bool:
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
                _emit(f"[git-publish] removing stale lock (age={int(age)}s)")
                try:
                    GLOBAL_LOCK.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() - start > GLOBAL_LOCK_TIMEOUT:
                _emit("[git-publish] timed out waiting for publish lock")
                return False
            time.sleep(3)


def _release_lock() -> None:
    try:
        GLOBAL_LOCK.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:  # noqa: BLE001
        _emit(f"[git-publish] failed to release lock: {e}")


# ---------------------------------------------------------------------------
# Worktree management
# ---------------------------------------------------------------------------

def _ensure_worktree() -> Path:
    """Create or refresh a detached worktree pinned to ``origin/<branch>``."""
    TMP_DIR.mkdir(exist_ok=True)
    _git(["fetch", "origin", PUSH_BRANCH, "--quiet"], cwd=PROJECT_ROOT)

    git_marker = WORKTREE_DIR / ".git"
    if not git_marker.exists():
        if WORKTREE_DIR.exists():
            shutil.rmtree(WORKTREE_DIR, ignore_errors=True)
        # Prune any stale registration of this path before re-adding.
        _git(["worktree", "prune"], cwd=PROJECT_ROOT, check=False)
        _git(
            ["worktree", "add", "--force", "--detach", str(WORKTREE_DIR), f"origin/{PUSH_BRANCH}"],
            cwd=PROJECT_ROOT,
        )
    else:
        _git(["reset", "--hard", f"origin/{PUSH_BRANCH}"], cwd=WORKTREE_DIR)
        _git(["clean", "-fd"], cwd=WORKTREE_DIR)
    return WORKTREE_DIR


def _mirror_into_worktree(wt: Path, paths: list[str]) -> None:
    """Mirror each slug path from the live tree into the worktree."""
    for rel in paths:
        src = PROJECT_ROOT / rel
        dst = wt / rel
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


# ---------------------------------------------------------------------------
# Liveness check + DB status
# ---------------------------------------------------------------------------

def preview_url_for(slug: str) -> str:
    return f"{PUBLISH_HOST}/preview/{slug}"


def _wait_until_live(slug: str) -> bool:
    url = preview_url_for(slug) + "/"
    for _ in range(LIVE_CHECK_ATTEMPTS):
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "dan-publish-check"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                if 200 <= resp.status < 400:
                    return True
        except Exception:  # noqa: BLE001 - build/propagation lag is expected
            pass
        time.sleep(LIVE_CHECK_DELAY)
    return False


def _supabase():
    from app.services.supabase_client import get_supabase_client

    return get_supabase_client().client


def _mark_ready(slug: str) -> None:
    try:
        sb = _supabase()
        now = datetime.now(timezone.utc).isoformat()
        public_url = preview_url_for(slug)
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
            checklist = {**checklist, "delivery_url": f"{public_url}/", "deployed_at": now}
            (
                sb.table("chat_artifact")
                .update(
                    {
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
    except Exception as e:  # noqa: BLE001 - publish success matters more than metadata
        _emit(f"[git-publish] DB mark-ready failed for {slug}: {e}")


def _mark_error(slug: str, message: str) -> None:
    msg = (message or "").strip()[-1500:] or "publish failed (no output captured)"
    try:
        sb = _supabase()
        (
            sb.table("chat_artifact")
            .update({"delivery_status": "error", "last_publish_error": msg})
            .eq("slug", slug)
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        _emit(f"[git-publish] DB mark-error failed for {slug}: {e}")


# ---------------------------------------------------------------------------
# Publish one slug
# ---------------------------------------------------------------------------

def _commit_and_push(wt: Path, slug: str, paths: list[str]) -> tuple[bool, str]:
    """Mirror, commit (scope-isolated), and push. Returns (changed, error)."""
    last_err = ""
    for attempt in range(1, PUSH_ATTEMPTS + 1):
        # Always start from a clean, up-to-date branch tip.
        _git(["reset", "--hard", f"origin/{PUSH_BRANCH}"], cwd=wt)
        _git(["clean", "-fd"], cwd=wt)
        _mirror_into_worktree(wt, paths)
        _git(["add", "--", *paths], cwd=wt)

        staged = _git(["diff", "--cached", "--name-only"], cwd=wt).stdout.strip()
        if not staged:
            return False, ""  # nothing to publish — already current

        message = (
            f"publish(artifact:{slug}): auto-publish {slug} on registration\n\n"
            "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
        )
        commit = _git(["commit", "-m", message], cwd=wt, check=False)
        if commit.returncode != 0:
            return False, f"commit blocked:\n{commit.stdout}"

        push = _git(["push", "origin", f"HEAD:{PUSH_BRANCH}"], cwd=wt, check=False, timeout=180)
        if push.returncode == 0:
            return True, ""
        last_err = push.stdout
        _emit(f"[git-publish] push attempt {attempt} failed for {slug}; refetching")
        _git(["fetch", "origin", PUSH_BRANCH, "--quiet"], cwd=PROJECT_ROOT, check=False)
        time.sleep(min(15, 5 * attempt))
    return False, last_err or "push failed"


def _publish_one(slug: str, *, push: bool, wait_live: bool) -> dict:
    result = {"slug": slug, "status": "pending", "url": preview_url_for(slug), "error": ""}
    paths = artifact_files_for_slug(slug)
    if not paths:
        result["status"] = "skipped"
        result["error"] = "no artifact files found on disk"
        _emit(f"[git-publish] {slug}: no files found, skipping")
        return result

    try:
        wt = _ensure_worktree()
    except Exception as e:  # noqa: BLE001
        result["status"] = "error"
        result["error"] = f"worktree setup failed: {e}"
        _mark_error(slug, result["error"])
        return result

    if not push:
        # Dry run: mirror + stage so the caller can inspect, but do not commit.
        _git(["reset", "--hard", f"origin/{PUSH_BRANCH}"], cwd=wt)
        _git(["clean", "-fd"], cwd=wt)
        _mirror_into_worktree(wt, paths)
        _git(["add", "--", *paths], cwd=wt)
        staged = _git(["diff", "--cached", "--name-only"], cwd=wt).stdout.strip()
        result["status"] = "dry-run"
        result["error"] = ""
        _emit(f"[git-publish] {slug}: dry-run staged:\n{staged}")
        return result

    try:
        changed, err = _commit_and_push(wt, slug, paths)
    except Exception as e:  # noqa: BLE001
        result["status"] = "error"
        result["error"] = f"git publish failed: {e}"
        _mark_error(slug, result["error"])
        return result

    if err:
        result["status"] = "error"
        result["error"] = err
        _mark_error(slug, err)
        _emit(f"[git-publish] {slug}: FAILED\n{err}")
        return result

    if not changed:
        _emit(f"[git-publish] {slug}: already up to date on {PUSH_BRANCH}")

    if wait_live:
        if _wait_until_live(slug):
            _mark_ready(slug)
            result["status"] = "live"
            _emit(f"[git-publish] {slug}: live at {preview_url_for(slug)}")
        else:
            result["status"] = "pushed"
            result["error"] = "pushed to main but /preview did not respond in time"
            _mark_error(slug, result["error"])
            _emit(f"[git-publish] {slug}: pushed but not yet live")
    else:
        result["status"] = "pushed"
        _mark_ready(slug)
    return result


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def publish_artifacts_via_git(
    slugs: Iterable[str], *, push: bool = True, wait_live: bool = True
) -> list[dict]:
    """Publish each slug to ``main``. Serialized by a global lock."""
    unique: list[str] = []
    seen: set[str] = set()
    for raw in slugs:
        s = (raw or "").strip()
        if s and s not in seen:
            seen.add(s)
            unique.append(s)
    if not unique:
        return []

    if not _acquire_lock():
        return [{"slug": s, "status": "deferred", "url": preview_url_for(s), "error": "another publish in progress"} for s in unique]
    try:
        return [_publish_one(s, push=push, wait_live=wait_live) for s in unique]
    finally:
        _release_lock()


def schedule_artifact_git_publish(slugs: Iterable[str]) -> None:
    """Spawn a background process that publishes the given slugs to ``main``."""
    unique: list[str] = []
    seen: set[str] = set()
    for raw in slugs:
        s = (raw or "").strip()
        if s and s not in seen:
            seen.add(s)
            unique.append(s)
    if not unique:
        return
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        with PUBLISH_LOG.open("ab") as log_file:
            subprocess.Popen(
                [sys.executable, "-m", "app.services.artifact_git_publish", *unique],
                cwd=str(PROJECT_ROOT),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
        _emit(f"[git-publish] scheduled publish for slugs={','.join(unique)}")
    except Exception as e:  # noqa: BLE001 - publishing must not break chat completion
        _emit(f"[git-publish] failed to schedule publish: {e}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv[1:]
    no_wait = "--no-wait" in sys.argv[1:]
    results = publish_artifacts_via_git(args, push=not dry, wait_live=not no_wait)
    for r in results:
        print(r)
    raise SystemExit(0 if all(r["status"] in ("live", "pushed", "skipped", "dry-run") for r in results) else 1)
