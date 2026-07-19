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

import json
import logging
import os
import re
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

# 成果物（クライアント納品物）は Dan infra とは別リポジトリ(done-artifacts)へ公開する。
# Dan は従来通り D:/done の frontend/src/app/artifacts/<slug> に書き（ローカル
# プレビューもそのまま）、publisher がそのファイルを done-artifacts リポジトリへ
# commit & push する（done-artifacts はルートが Next アプリなので frontend/ プレ
# フィックスを剥がしてパス変換する）。done-artifacts は GitHub 連携済みなので
# push → Vercel 自動ビルドで /preview/<slug> が配信される。
ARTIFACTS_REPO = Path(
    os.environ.get("DAN_ARTIFACTS_REPO") or str(PROJECT_ROOT.parent / "done-artifacts")
).resolve()
# done-artifacts 公開用 worktree は両リポジトリの外に置く（D:/done を一切汚さない）。
ARTIFACTS_WORKTREE_DIR = ARTIFACTS_REPO.parent / ".dan-artifacts-publish-wt"
# Each machine may keep a local working copy for fast authoring.  These
# snapshots record the version of every artifact that the local copy was based
# on.  They are deliberately outside either git repository: they are safety
# metadata for this publisher, not source code.
ARTIFACT_BASES_DIR = TMP_DIR / "artifact-source-bases"


def _target_rel(rel: str) -> str:
    """D:/done レイアウト(frontend/...) を done-artifacts レイアウト(ルート=Nextアプリ)へ変換。"""
    return rel[len("frontend/") :] if rel.startswith("frontend/") else rel


# Production host whose /preview/<slug> serves the artifact (done-artifacts on Vercel).
PUBLISH_HOST = (
    os.environ.get("DAN_PUBLISH_HOST")
    or "https://done-artifacts.vercel.app"
).rstrip("/")

PUSH_BRANCH = os.environ.get("DAN_PUBLISH_BRANCH", "main")

# Slugs whose canonical source lives IN the done-artifacts repo itself (edited
# directly there and pushed), NOT as a per-machine gitignored copy under D:/done.
# For these, the "mirror the local D:/done copy over done-artifacts" publish path
# is DISABLED so a stale copy on a second machine can never silently revert edits.
# Background: kittoku regressed repeatedly (2026-07-18) because a second machine
# held an old local copy and its registration-triggered auto-publish kept
# overwriting done-artifacts with it. Editing done-artifacts directly + git push
# is the single shared source of truth; both machines pull/push the same repo.
DONE_ARTIFACTS_NATIVE_SLUGS = {
    s.strip()
    for s in (os.environ.get("DAN_DONE_ARTIFACTS_NATIVE_SLUGS") or "kittoku").split(",")
    if s.strip()
}

# Clean, name-bearing host that users see: <SHARE_ALIAS>/preview/<slug>. It is a
# free vercel.app alias re-pointed to the latest production on every publish so
# it never goes stale (a bare `vercel alias set` pins to one deployment). Set to
# empty to disable. The same value must be configured as NEXT_PUBLIC_SHARE_ORIGIN
# (web) and the mobile app base URL so every device shows the same URL.
# 分離後は done-artifacts の Vercel プロジェクトドメインが本番デプロイへ自動追従
# するため、CLI による share alias 再ポイントは不要（既定は無効）。done-studio
# 等の独自ドメイン移設はフェーズ③で別途行う。env で再有効化可能。
SHARE_ALIAS = os.environ.get("DAN_SHARE_ALIAS", "").strip()
# How long to wait for the new production build before re-pointing the share host.
SHARE_BUILD_ATTEMPTS = 40   # x SHARE_BUILD_DELAY = ~10 min ceiling
SHARE_BUILD_DELAY = 15
VERCEL = shutil.which("vercel") or shutil.which("vercel.cmd") or "vercel"
_DEPLOYMENT_RE = re.compile(r"https://frontend-[a-z0-9]+-[\w-]+\.vercel\.app")

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
    from scripts.scope_classifier import (  # type: ignore
        _APP_API_DIR_TO_OWNER,
        _PUBLIC_DIR_TO_OWNER,
        _PUBLIC_FILE_TO_OWNER,
    )

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
    # API route dirs whose name differs from the slug (e.g. denki-qa->denki-knowledge).
    for apidir, owner in _APP_API_DIR_TO_OWNER.items():
        if owner.kind == "artifact" and owner.name == slug:
            roots.append(f"frontend/src/app/api/{apidir}")
    # Top-level public files owned by this slug (e.g. denki-knowledge-index.json).
    for fname, owner in _PUBLIC_FILE_TO_OWNER.items():
        if owner.kind == "artifact" and owner.name == slug:
            roots.append(f"frontend/public/{fname}")

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
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        with PUBLISH_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {message.rstrip(chr(10))}\n")
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

def _ensure_worktree(repo: Path = PROJECT_ROOT, wt_dir: Path = WORKTREE_DIR) -> Path:
    """Create or refresh a detached worktree of ``repo`` pinned to ``origin/<branch>``."""
    wt_dir.parent.mkdir(parents=True, exist_ok=True)
    _git(["fetch", "origin", PUSH_BRANCH, "--quiet"], cwd=repo)

    git_marker = wt_dir / ".git"
    if not git_marker.exists():
        if wt_dir.exists():
            shutil.rmtree(wt_dir, ignore_errors=True)
        # Prune any stale registration of this path before re-adding.
        _git(["worktree", "prune"], cwd=repo, check=False)
        _git(
            ["worktree", "add", "--force", "--detach", str(wt_dir), f"origin/{PUSH_BRANCH}"],
            cwd=repo,
        )
    else:
        _git(["reset", "--hard", f"origin/{PUSH_BRANCH}"], cwd=wt_dir)
        _git(["clean", "-fd"], cwd=wt_dir)
    return wt_dir


def _mirror_into_worktree(wt: Path, paths: list[str], *, translate: bool = False) -> None:
    """Mirror each slug path from the D:/done live tree into the worktree.

    ``translate=True`` maps D:/done paths (frontend/...) to the done-artifacts
    layout (root = Next app) when copying into the destination worktree.
    """
    for rel in paths:
        src = PROJECT_ROOT / rel
        dst = wt / (_target_rel(rel) if translate else rel)
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


# ---------------------------------------------------------------------------
# Local-copy concurrency guard
# ---------------------------------------------------------------------------

def _tree_files(root: Path) -> dict[str, bytes]:
    """Return a stable ``relative path -> contents`` view of a file tree."""
    if not root.exists():
        return {}
    if root.is_file():
        return {root.name: root.read_bytes()}
    return {
        str(path.relative_to(root)).replace("\\", "/"): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    if source.exists():
        shutil.copytree(source, destination)


def _local_target_tree(paths: list[str], destination: Path) -> None:
    """Materialize local artifact files in done-artifacts' path layout."""
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for rel in paths:
        src = PROJECT_ROOT / rel
        target = destination / _target_rel(rel)
        if src.is_dir():
            shutil.copytree(src, target)
        elif src.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)


def _canonical_target_tree(wt: Path, paths: list[str], destination: Path) -> None:
    """Materialize just this artifact's canonical files from a worktree."""
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for rel in paths:
        target_rel = _target_rel(rel)
        src = wt / target_rel
        target = destination / target_rel
        if src.is_dir():
            shutil.copytree(src, target)
        elif src.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)


def _artifact_snapshot_dir(slug: str) -> Path:
    # Slugs are controlled identifiers, but retain a defensive path check as
    # this directory is used by a background process.
    if not re.fullmatch(r"[A-Za-z0-9_-]+", slug):
        raise ValueError(f"invalid artifact slug for source snapshot: {slug!r}")
    return ARTIFACT_BASES_DIR / slug


def _snapshot_current_source(slug: str, wt: Path, paths: list[str]) -> None:
    """Record the exact canonical source that a successful local edit produced."""
    snapshot = _artifact_snapshot_dir(slug)
    staged = snapshot.with_name(f".{snapshot.name}.staging")
    _canonical_target_tree(wt, paths, staged)
    if snapshot.exists():
        shutil.rmtree(snapshot)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    staged.replace(snapshot)


def _guard_and_apply_local_changes(wt: Path, slug: str, paths: list[str]) -> str:
    """Apply only non-conflicting local changes onto the current canonical tree.

    The legacy publisher removed an artifact directory in ``wt`` and copied a
    machine-local directory over it.  That is a last-writer-wins operation and
    silently loses edits made on another machine.  Here the local tree is a
    change set relative to its recorded base.  A file changed both locally and
    in canonical source is a conflict and publication stops without writing.
    """
    snapshot = _artifact_snapshot_dir(slug)
    local_root = TMP_DIR / "artifact-publish-local" / slug
    _local_target_tree(paths, local_root)

    if not snapshot.exists():
        # Do not guess the base of an already-published artifact.  Seeding a
        # base is safe only when this machine is demonstrably current.
        current_root = TMP_DIR / "artifact-publish-current" / slug
        _canonical_target_tree(wt, paths, current_root)
        canonical_is_new = not _tree_files(current_root)
        if not canonical_is_new and _tree_files(local_root) != _tree_files(current_root):
            return (
                "安全のため公開を中止しました。この端末には成果物の基準版がありません。"
                "共有正本と異なるローカルコピーを自動で上書きすると巻き戻しになるため、"
                "最新の共有正本を同期してからもう一度修正してください。"
            )
        _snapshot_current_source(slug, wt, paths)

    base = _tree_files(snapshot)
    local = _tree_files(local_root)
    current_root = TMP_DIR / "artifact-publish-current" / slug
    _canonical_target_tree(wt, paths, current_root)
    current = _tree_files(current_root)
    for rel in sorted(set(base) | set(local) | set(current)):
        base_value = base.get(rel)
        local_value = local.get(rel)
        current_value = current.get(rel)
        if local_value == base_value:
            continue  # this machine did not change this file
        if current_value not in (base_value, local_value):
            return (
                "安全のため公開を中止しました。別の端末で同じ成果物が更新されています "
                f"({rel})。最新の共有正本を取り込み、修正を重ねてから公開してください。"
            )
        target = wt / rel
        if local_value is None:
            if target.exists():
                target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(local_value)
    return ""


def synchronize_local_artifact_from_canonical(slug: str) -> dict:
    """Back up and refresh one machine-local copy from shared canonical source.

    This is the one-time migration path for a machine that predates the
    concurrency guard.  It never discards a local file: the complete old copy
    is retained under ``_codex_backups`` before canonical files replace it.
    """
    paths = artifact_files_for_slug(slug)
    if not paths:
        return {"ok": False, "detail": "local artifact files not found"}
    wt = _ensure_worktree(ARTIFACTS_REPO, ARTIFACTS_WORKTREE_DIR)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = PROJECT_ROOT / "_codex_backups" / f"artifact-source-sync-{stamp}" / slug
    for rel in paths:
        source = PROJECT_ROOT / rel
        canonical = wt / _target_rel(rel)
        if not canonical.exists():
            return {"ok": False, "detail": f"canonical source missing: {_target_rel(rel)}"}
        backup = backup_root / rel
        if source.is_dir():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, backup)
            shutil.rmtree(source)
            shutil.copytree(canonical, source)
        elif source.is_file():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, backup)
            shutil.copy2(canonical, source)
    _snapshot_current_source(slug, wt, paths)
    return {"ok": True, "backup": str(backup_root)}


# ---------------------------------------------------------------------------
# Liveness check + DB status
# ---------------------------------------------------------------------------

def preview_url_for(slug: str) -> str:
    return f"{PUBLISH_HOST}/preview/{slug}"


def _wait_until_live(slug: str) -> bool:
    # No trailing slash: <host>/preview/<slug>/ 308-redirects to the no-slash
    # form, and urllib (<=3.10) raises on 308 instead of following it.
    url = preview_url_for(slug)
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

# ---------------------------------------------------------------------------
# Pre-publish build prerequisite check
#
# A per-artifact publish only carries the artifact's own files (scope
# artifact:<slug>). If the artifact imports a shared component (@/components/..)
# or an npm package that isn't on `main` yet (those are infra scope), pushing the
# artifact alone breaks the WHOLE frontend build — which blocks every other
# artifact's publish too (this happened with yonago-gojo's gsap/motion deps,
# 2026-06-09). So before pushing, verify everything the artifact imports already
# exists on the target. If not, hold the publish and report exactly what's
# missing, instead of breaking production.
# ---------------------------------------------------------------------------

_IMPORT_RE = re.compile(
    r"""(?:from|import)\s*['"]([^'"]+)['"]|import\s*\(\s*['"]([^'"]+)['"]\s*\)"""
)
_SRC_EXTS = (".tsx", ".ts", ".jsx", ".js")
# Packages assumed always present (Next/React core + Node builtins).
_ALWAYS_PRESENT = {"react", "react-dom", "next", "node"}


def _scan_imports(file_path: Path) -> set[str]:
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return set()
    specs: set[str] = set()
    for m in _IMPORT_RE.finditer(text):
        spec = m.group(1) or m.group(2)
        if spec:
            specs.add(spec)
    return specs


def _alias_target_exists(wt: Path, spec: str) -> bool:
    # done-artifacts はルートが Next アプリ。"@/x/y" は src/x/y にマップ。
    base = wt / "src" / spec[2:]
    for ext in _SRC_EXTS:
        if base.with_suffix(ext).exists():
            return True
        if (base / f"index{ext}").exists():
            return True
    return base.exists()


def _pkg_name(spec: str) -> str:
    if spec.startswith("@"):
        return "/".join(spec.split("/")[:2])
    return spec.split("/")[0]


def _missing_build_prereqs(wt: Path, paths: list[str]) -> list[str]:
    """Return import specs the artifact needs that are NOT present on the target."""
    try:
        pkg = json.loads((wt / "package.json").read_text(encoding="utf-8"))
        deps = set(pkg.get("dependencies", {})) | set(pkg.get("devDependencies", {}))
    except Exception:  # noqa: BLE001 - if we can't read deps, don't block
        deps = None

    missing: set[str] = set()
    for rel in paths:
        root = wt / _target_rel(rel)
        files = [f for f in root.rglob("*") if f.suffix.lower() in _SRC_EXTS] if root.is_dir() \
            else ([root] if root.suffix.lower() in _SRC_EXTS else [])
        for f in files:
            for spec in _scan_imports(f):
                if spec.startswith(".") or spec.startswith("node:"):
                    continue  # relative (own files) / node builtins
                if spec.startswith("@/"):
                    if not _alias_target_exists(wt, spec):
                        missing.add(spec)
                else:
                    name = _pkg_name(spec)
                    if name in _ALWAYS_PRESENT or name.startswith("next/"):
                        continue
                    if deps is not None and name not in deps:
                        missing.add(name)
    return sorted(missing)


def _commit_and_push(wt: Path, slug: str, paths: list[str]) -> tuple[bool, str]:
    """Commit only non-conflicting local artifact changes and push them."""
    last_err = ""
    for attempt in range(1, PUSH_ATTEMPTS + 1):
        # Always start from a clean, up-to-date branch tip.
        _git(["reset", "--hard", f"origin/{PUSH_BRANCH}"], cwd=wt)
        _git(["clean", "-fd"], cwd=wt)
        conflict = _guard_and_apply_local_changes(wt, slug, paths)
        if conflict:
            return False, conflict

        # Gate: don't push an artifact whose imports aren't on the target — it
        # would break the whole-frontend build and block every other publish.
        missing = _missing_build_prereqs(wt, paths)
        if missing:
            return False, (
                "公開を保留しました（このまま出すと本番ビルドが壊れ他の成果物も巻き添えになるため）。"
                f"main にまだ無い依存/共有部品: {', '.join(missing)}. "
                "これらを infra として先に main へ入れてから再公開してください。"
            )

        target_paths = [_target_rel(p) for p in paths]
        _git(["add", "--", *target_paths], cwd=wt)

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
            _snapshot_current_source(slug, wt, paths)
            return True, ""
        last_err = push.stdout
        _emit(f"[git-publish] push attempt {attempt} failed for {slug}; refetching")
        _git(["fetch", "origin", PUSH_BRANCH, "--quiet"], cwd=ARTIFACTS_REPO, check=False)
        time.sleep(min(15, 5 * attempt))
    return False, last_err or "push failed"


REWRITES_REL = "frontend/src/lib/custom-domain-rewrites.generated.ts"


def _publish_rewrites_sync() -> tuple[bool, str]:
    """custom-domain-rewrites 生成ファイル(infra)を main に commit+push する。

    隔離 worktree＋ロックで開発ツリー/Danの作業を汚さない。(changed, error) を返す。
    """
    if not _acquire_lock():
        return False, "publish lock busy"
    try:
        wt = _ensure_worktree()
        last_err = ""
        for attempt in range(1, PUSH_ATTEMPTS + 1):
            _git(["reset", "--hard", f"origin/{PUSH_BRANCH}"], cwd=wt)
            _git(["clean", "-fd"], cwd=wt)
            _mirror_into_worktree(wt, [REWRITES_REL])
            _git(["add", "--", REWRITES_REL], cwd=wt)
            staged = _git(["diff", "--cached", "--name-only"], cwd=wt).stdout.strip()
            if not staged:
                return False, ""  # 既に最新
            message = (
                "chore(routing): 接続ドメインの custom-domain rewrites を自動再生成\n\n"
                "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
            )
            commit = _git(["commit", "-m", message], cwd=wt, check=False)
            if commit.returncode != 0:
                return False, f"commit blocked:\n{commit.stdout}"
            push = _git(["push", "origin", f"HEAD:{PUSH_BRANCH}"], cwd=wt, check=False, timeout=180)
            if push.returncode == 0:
                return True, ""
            last_err = push.stdout
            _emit(f"[git-publish] rewrites push attempt {attempt} failed; refetching")
            _git(["fetch", "origin", PUSH_BRANCH, "--quiet"], cwd=PROJECT_ROOT, check=False)
            time.sleep(min(15, 5 * attempt))
        return False, last_err or "push failed"
    finally:
        _release_lock()


async def publish_custom_domain_rewrites() -> dict:
    """接続ドメインの rewrites を再生成し、変化があれば main に commit+push する。

    ベストエフォート（例外は握りつぶして status を返す）。push されると Vercel が
    再デプロイし、そのドメインのサブパスがクリーンURLで配信されるようになる。
    """
    import asyncio

    try:
        from scripts.generate_custom_domain_rewrites import regenerate

        changed = await regenerate()
        if not changed:
            return {"changed": False, "pushed": False, "detail": "rewrites already current"}
        pushed, err = await asyncio.to_thread(_publish_rewrites_sync)
        if pushed:
            return {"changed": True, "pushed": True,
                    "detail": "rewrites pushed to main (Vercel redeploy で反映)"}
        return {"changed": True, "pushed": False, "detail": err or "nothing to push"}
    except Exception as e:  # noqa: BLE001
        return {"changed": False, "pushed": False, "detail": f"error: {e}"}


def _publish_one(slug: str, *, push: bool, wait_live: bool) -> dict:
    _emit(f"[git-publish] {slug}: publish START (push={push}, wait_live={wait_live})")
    result = {"slug": slug, "status": "pending", "url": preview_url_for(slug), "error": ""}

    # done-artifacts を単一の正とする成果物は、PC内ローカルコピーからのミラー公開を
    # 行わない（古いコピーによる巻き戻し防止）。編集は done-artifacts 直編集＋push で行う。
    if slug in DONE_ARTIFACTS_NATIVE_SLUGS:
        result["status"] = "skipped"
        result["error"] = (
            "done-artifacts を単一の正として直接管理する成果物のため、"
            "ローカルコピーからのミラー公開はスキップしました（巻き戻し防止）。"
        )
        _emit(f"[git-publish] {slug}: done-artifacts-native, skipping mirror publish")
        return result

    paths = artifact_files_for_slug(slug)
    if not paths:
        result["status"] = "skipped"
        result["error"] = "no artifact files found on disk"
        _emit(f"[git-publish] {slug}: no files found, skipping")
        return result

    try:
        wt = _ensure_worktree(ARTIFACTS_REPO, ARTIFACTS_WORKTREE_DIR)
    except Exception as e:  # noqa: BLE001
        result["status"] = "error"
        result["error"] = f"worktree setup failed: {e}"
        _mark_error(slug, result["error"])
        return result

    if not push:
        # Dry run: mirror + stage so the caller can inspect, but do not commit.
        _git(["reset", "--hard", f"origin/{PUSH_BRANCH}"], cwd=wt)
        _git(["clean", "-fd"], cwd=wt)
        _mirror_into_worktree(wt, paths, translate=True)
        _git(["add", "--", *[_target_rel(p) for p in paths]], cwd=wt)
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

    result["changed"] = changed
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
# Share alias (clean name-bearing host, re-pointed to latest production)
# ---------------------------------------------------------------------------

def _latest_ready_production() -> Optional[str]:
    """Return the newest READY production deployment URL (top of `vercel ls`)."""
    try:
        proc = subprocess.run(
            [VERCEL, "ls", "frontend", "--prod"],
            cwd=str(PROJECT_ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=90,
        )
        for line in (proc.stdout or "").splitlines():
            if "Ready" in line and "Production" in line:
                m = _DEPLOYMENT_RE.search(line)
                if m:
                    return m.group(0)
    except Exception as e:  # noqa: BLE001
        _emit(f"[git-publish] could not list production deployments: {e}")
    return None


def _wait_for_new_production(baseline: Optional[str]) -> Optional[str]:
    """Wait until a NEW Ready production deployment (the build of our push) appears."""
    for _ in range(SHARE_BUILD_ATTEMPTS):
        latest = _latest_ready_production()
        if latest and latest != baseline:
            return latest
        time.sleep(SHARE_BUILD_DELAY)
    return None


def _repoint_share_alias(baseline: Optional[str]) -> None:
    """Point SHARE_ALIAS at the build produced by THIS publish.

    Re-points the single clean share host (cheap, one alias) instead of relying
    on per-artifact aliases. Crucially it WAITS until the new production build is
    Ready before re-pointing: re-pointing immediately after `git push` pins
    SHARE_ALIAS to the *pre-build* deployment and serves stale content (the bug
    found 2026-06-09 — edits appeared not to publish). Best-effort: failure must
    not fail the publish.
    """
    if not SHARE_ALIAS:
        return
    target = _wait_for_new_production(baseline)
    if not target:
        _emit("[git-publish] no new build detected in time; pinning current latest")
        target = _latest_ready_production()
    if not target:
        return
    try:
        proc = subprocess.run(
            [VERCEL, "alias", "set", target, SHARE_ALIAS],
            cwd=str(PROJECT_ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        if proc.returncode == 0:
            _emit(f"[git-publish] share alias {SHARE_ALIAS} -> {target} (fresh build)")
        else:
            _emit(f"[git-publish] share alias re-point failed:\n{proc.stdout}")
    except Exception as e:  # noqa: BLE001
        _emit(f"[git-publish] share alias re-point error: {e}")


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
        # Record the production build BEFORE we push, so the share-alias re-point
        # can wait for OUR build (a *different*, newer one) to be Ready.
        baseline = _latest_ready_production() if push else None
        results = [_publish_one(s, push=push, wait_live=wait_live) for s in unique]
        # Point the clean share host at the build produced by this publish.
        if push and any(r.get("status") in ("live", "pushed") for r in results):
            # Only wait for a fresh build when something actually changed; for a
            # no-op publish just re-point to current latest (baseline=None skips the wait).
            changed_any = any(r.get("changed") for r in results)
            _repoint_share_alias(baseline if changed_any else None)
        return results
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
