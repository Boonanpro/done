"""Keep every published copy of an artifact in step with its source files.

An artifact has exactly one source: the files under
``frontend/src/app/artifacts/<slug>/``.  Its dedicated Vercel site is a copy.
A copy used to be rebuilt only when something *announced* a change (an agent
turn that wrote ``page.tsx``).  Edits to any other file in the folder, edits
from another room and edits by hand announced nothing, so the copy silently
stayed old (2026-10-16: the 面談受付 table shipped as page-body.tsx only, and
the 成果物 tab kept showing the former chat layout).

Here a copy is judged by what it was built from, not by who touched what:

* ``source_fingerprint(slug)`` hashes the folder's files.
* A deploy records the fingerprint it started from (``job_status``).
* ``loop()`` compares each published site with its current fingerprint and
  redeploys the ones that differ once the folder has been quiet for a minute.
* ``release_state()`` tells the UI whether the copy is current, so a copy that
  is known to be old is never presented as the artifact.
* Every pass writes what it saw to ``.tmp/artifact-releases.json``.  The phone
  app opens this copy, so ``scripts/artifact_seen.py`` reads it to tell whether
  the owner's phone shows the current files yet (2026-10-18).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_ROOT = PROJECT_ROOT / "frontend" / "src" / "app" / "artifacts"

# Not part of what the dedicated site renders: the artifact's own backend
# (run by Dan Core), caches, and the release snapshot that the deploy itself
# rewrites just before building.
_SKIP_DIRS = {"_server", "__pycache__", "node_modules", ".next"}
_SKIP_FILES = {"release.gen.json", "release.gen.json.tmp"}

SNAPSHOT = PROJECT_ROOT / ".tmp" / "artifact-releases.json"
QUIET_SECONDS = 60        # the folder must stop changing this long before a rebuild
LOOP_SECONDS = 60
FAILURE_BACKOFF = 30 * 60  # a source that failed to deploy is retried after this

_cache_lock = threading.Lock()
# slug -> (stat signature, fingerprint, newest mtime)
_cache: dict[str, tuple[tuple, str, float]] = {}
# artifact_id -> (fingerprint that failed, when)
_failed: dict[str, tuple[str, float]] = {}


def artifact_dir(slug: str) -> Optional[Path]:
    slug = (slug or "").strip().lower()
    if not slug or "/" in slug or "\\" in slug or slug.startswith("."):
        return None
    path = ARTIFACTS_ROOT / slug
    return path if path.is_dir() else None


def _files(root: Path) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if name in _SKIP_FILES or name.startswith(".") or name.endswith((".pyc", ".tmp")):
                continue
            out.append(Path(dirpath) / name)
    return out


def source_fingerprint(slug: str) -> Optional[tuple[str, float]]:
    """Return (sha256 of the folder's files, newest mtime) or None if absent.

    Stats are cheap; contents are read only when a stat changed, so callers
    may ask on every API read.
    """
    root = artifact_dir(slug)
    if root is None:
        return None
    files = _files(root)
    stats = []
    for path in files:
        try:
            st = path.stat()
        except OSError:
            continue
        stats.append((path.relative_to(root).as_posix(), st.st_size, st.st_mtime_ns))
    signature = tuple(stats)
    with _cache_lock:
        cached = _cache.get(slug)
        if cached and cached[0] == signature:
            return cached[1], cached[2]
    digest = hashlib.sha256()
    for rel, _size, _mtime in stats:
        try:
            data = (root / rel).read_bytes()
        except OSError:
            continue
        digest.update(rel.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(data).digest())
    newest = max((m for _r, _s, m in stats), default=0) / 1e9
    value = (digest.hexdigest(), newest)
    with _cache_lock:
        _cache[slug] = (signature, value[0], value[1])
    return value


def _parse_time(value: Any) -> Optional[float]:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    # Supabase trims trailing zeros of the fraction (".92148"); Python 3.10's
    # fromisoformat accepts only 3 or 6 digits.
    text = re.sub(r"\.(\d{1,6})(?=[+-]|$)", lambda m: "." + m.group(1).ljust(6, "0"), text)
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def release_state(slug: str, release: Optional[dict[str, Any]], *, deploying: bool = False) -> str:
    """How the published copy relates to the current files.

    ``none``      never published
    ``current``   built from exactly the current files
    ``updating``  differs, and a rebuild is running or about to start
    ``stale``     differs, and no rebuild is in progress (failed, or source
                  missing)
    """
    if not release or not (release.get("shared_url") or "").strip():
        return "none"
    current = source_fingerprint(slug)
    if current is None:
        return "current"  # nothing local to compare with (external or removed source)
    job = release.get("job_status") or {}
    built_from = job.get("source_fingerprint") if isinstance(job, dict) else None
    if built_from:
        same = built_from == current[0]
    else:
        # Releases made before fingerprints were recorded: a file newer than the
        # publication means the copy predates it.
        published = _parse_time(release.get("published_at")) or _parse_time(job.get("promoted_at") if isinstance(job, dict) else None)
        if published is None:
            return "current"  # no record of when it was built; nothing to compare with
        same = current[1] <= published + 1
    if same:
        return "current"
    if deploying or release.get("status") == "deploying":
        return "updating"
    return "stale" if release.get("status") == "failed" else "updating"


def _deploy_running() -> set[str]:
    from app.services import artifact_publication_service as pub

    with pub._DEPLOY_COALESCE_LOCK:
        return set(pub._DEPLOY_COALESCE)


def _published_rows() -> list[dict[str, Any]]:
    """Latest delivered release of every production artifact, with its owner and slug."""
    from app.services.supabase_client import get_supabase_client

    sb = get_supabase_client().client
    releases = (
        sb.table("artifact_publication")
        .select("artifact_id,status,shared_url,published_at,job_status,release_number")
        .not_.is_("shared_url", "null")
        .order("release_number", desc=True)
        .execute()
    ).data or []
    latest: dict[str, dict[str, Any]] = {}
    for row in releases:
        latest.setdefault(str(row["artifact_id"]), row)
    if not latest:
        return []
    cards = (
        sb.table("chat_artifact")
        .select("id,slug,created_by,kind")
        .in_("id", list(latest))
        .execute()
    ).data or []
    out = []
    for card in cards:
        if card.get("kind") not in (None, "production") or not card.get("created_by") or not card.get("slug"):
            continue
        out.append({**latest[str(card["id"])], "slug": card["slug"], "created_by": card["created_by"]})
    return out


def write_snapshot(rows: list[dict[str, Any]], running: set[str]) -> None:
    """What the published copies were built from, for scripts/artifact_seen.py (no DB access there)."""
    sites = {}
    for row in rows:
        sites[row["slug"]] = {
            "artifact_id": str(row["artifact_id"]),
            "status": row.get("status"),
            "shared_url": row.get("shared_url"),
            "published_at": row.get("published_at"),
            "release_number": row.get("release_number"),
            "job_status": {k: v for k, v in (row.get("job_status") or {}).items()
                           if k in ("source_fingerprint", "promoted_at")} if isinstance(row.get("job_status"), dict) else {},
            "deploying": str(row["artifact_id"]) in running,
        }
    data = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sites": sites}
    try:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        tmp = SNAPSHOT.with_name(f"{SNAPSHOT.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, SNAPSHOT)
    except OSError as exc:
        logger.warning("[artifact-fresh] snapshot write failed: %s", exc)


def reconcile_once(now: Optional[float] = None) -> list[str]:
    """Schedule a rebuild for the first published site whose files changed.

    One at a time: every dedicated site is built from the same frontend
    directory behind one lock, so queuing all of them at once would only make
    each wait.  The next stale site is picked up on the next pass.
    """
    from app.services.artifact_publication_service import schedule_dedicated_deploy

    now = now or time.time()
    running = _deploy_running()
    rows = _published_rows()
    write_snapshot(rows, running)
    if running:
        return []
    for row in rows:
        artifact_id = str(row["artifact_id"])
        current = source_fingerprint(row["slug"])
        if current is None or row.get("status") == "deploying":
            continue
        if release_state(row["slug"], row) == "current":
            continue
        if now - current[1] < QUIET_SECONDS:
            continue  # still being edited; build the finished state, not a half-written one
        failed = _failed.get(artifact_id)
        if failed and failed[0] == current[0] and now - failed[1] < FAILURE_BACKOFF:
            continue
        if row.get("status") == "failed":
            _failed[artifact_id] = (current[0], now)
        logger.info("[artifact-fresh] %s: files differ from the published copy, rebuilding", row["slug"])
        schedule_dedicated_deploy(artifact_id, str(row["created_by"]))
        return [artifact_id]
    return []


async def loop() -> None:
    await asyncio.sleep(30)  # let startup work (pending publications) go first
    while True:
        try:
            await asyncio.to_thread(reconcile_once)
        except Exception as exc:  # noqa: BLE001 - the next pass retries
            logger.warning("[artifact-fresh] pass failed: %s", exc)
        await asyncio.sleep(LOOP_SECONDS)

