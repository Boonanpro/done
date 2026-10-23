"""The running folder's code cannot be written: every file git tracks, and the folders that hold only code, carry the
"user immutable" flag of macOS (chflags uchg). Writing, editing in place, replacing, deleting, renaming, changing the
mode and adding a file to such a folder all fail with "Operation not permitted", whatever program tries.

Only the updaters take the flag off, for exactly the files they change, and put it back: scripts/follow_github.py
(the running folder follows GitHub main), scripts/rescue_wip.py (putting a file back) and the first install. Dan's own
runtime writes stay possible because they go to what git does not track: artifacts, .data, logs, builds, node_modules.

Why the flag (2026-10-23/24): the earlier guard looked at the folder after every tool and guessed who wrote what, moving
it to a branch. With many sessions at once it took one session's work into another's branch and missed writes that
kept size and time. A file that cannot be written needs no guess. The flag can be taken off by the same user
(chflags nouchg), so scripts/hook_live_tree_guard.py refuses chflags / chmod / xattr on the running folder; that is the
explanation for a session that tries, the flag is what holds.

Which folders are locked: every folder that holds tracked files, except the folders where Dan's runtime keeps creating
things (logs at the top, .next-* builds and .env in frontend/, uploads and data in app/, artifacts...). A folder stays
open when it holds anything git does not track other than Python caches, or when it is listed in ALWAYS_OPEN.
In an open folder a new file can still be added (never a change to an existing code file); the guard refuses that for
paths git would track.

    python scripts/live_lock.py status   how many files and folders are locked, and what is not
    python scripts/live_lock.py lock     lock (and from now on follow_github locks again after every update)
    python scripts/live_lock.py unlock   take every flag off and stop locking (by the owner's decision only)

On a system without chflags (the Windows standby) these do nothing and say so.
"""
from __future__ import annotations

import contextlib
import os
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from follow_github import _git, dan_dir, live_root  # noqa: E402

FLAG = getattr(stat, 'UF_IMMUTABLE', 0)
SUPPORTED = bool(FLAG) and hasattr(os, 'chflags') and sys.platform == 'darwin'
CACHES = {'__pycache__', '.DS_Store'}
# Folders Dan's runtime creates things in, open even on a fresh checkout where they hold nothing else yet:
# logs and .data at the top, .claude/mcp_<room>.json, app/uploads, app/logs and app/database.db, the frontend's .next-*
# builds, .env.local and tsconfig.<build>.json, generated public files, and new artifacts.
ALWAYS_OPEN = {'', '.claude', 'app', 'frontend', 'frontend/public', 'frontend/src/app/artifacts', 'frontend/public/artifacts'}


def active(repo) -> bool:
    """The running folder is kept locked (set by `lock`, cleared by `unlock`)."""
    return SUPPORTED and (dan_dir(repo) / 'locked').exists()


def _tracked(repo):
    out = _git(repo, 'ls-files', '-z').stdout.decode('utf-8', 'surrogateescape')
    return [p for p in out.split('\0') if p]


def plan(repo):
    """(files, folders) to lock, relative to repo. Files: what git tracks and exists. Folders: those holding tracked
    files and nothing else that git does not track (Python caches aside), minus ALWAYS_OPEN."""
    repo = str(repo)
    files = [p for p in _tracked(repo) if os.path.lexists(os.path.join(repo, p))]
    tracked = set(files)
    holders = set()
    for p in files:
        parts = p.split('/')
        for k in range(len(parts)):
            holders.add('/'.join(parts[:k]))
    folders = []
    for d in sorted(holders):
        if d in ALWAYS_OPEN or d == '.git' or d.startswith('.git/'):
            continue
        full = os.path.join(repo, d)
        if not os.path.isdir(full) or os.path.islink(full):
            continue
        try:
            names = os.listdir(full)
        except OSError:
            continue
        other = [n for n in names if n not in CACHES and not n.endswith('.pyc')
                 and (f'{d}/{n}' if d else n) not in tracked and (f'{d}/{n}' if d else n) not in holders]
        if not other:
            folders.append(d)
    return files, folders


def _set(repo, rel, on: bool):
    full = os.path.join(str(repo), rel) if rel else str(repo)
    try:
        st = os.lstat(full)
    except OSError:
        return False
    flags = (st.st_flags | FLAG) if on else (st.st_flags & ~FLAG)
    if flags == st.st_flags:
        return True
    try:
        (os.lchflags if stat.S_ISLNK(st.st_mode) else os.chflags)(full, flags)
        return True
    except OSError:
        return False


def lock(repo=None) -> tuple[int, int, list[str]]:
    """Lock the plan; mark the folder as kept locked. Returns (files, folders, failures)."""
    repo = str(repo or live_root())
    if not SUPPORTED:
        return 0, 0, ['chflags is not available here: nothing locked']
    files, folders = plan(repo)
    bad = [p for p in files if not _set(repo, p, True)]
    bad += [d + '/' for d in folders if not _set(repo, d, True)]
    (dan_dir(repo) / 'locked').write_text('1\n', encoding='utf-8')
    return len(files), len(folders), bad


def unlock(repo=None, keep_active=False) -> int:
    """Take the flag off everything git tracks and every folder above it. Returns how many flags were taken off."""
    repo = str(repo or live_root())
    if not SUPPORTED:
        return 0
    files = [p for p in _tracked(repo) if os.path.lexists(os.path.join(repo, p))]
    dirs = {'/'.join(p.split('/')[:k]) for p in files for k in range(len(p.split('/')))}
    n = 0
    for rel in [*files, *sorted(dirs, key=len, reverse=True)]:
        full = os.path.join(repo, rel) if rel else repo
        try:
            if os.lstat(full).st_flags & FLAG and _set(repo, rel, False):
                n += 1
        except OSError:
            pass
    if not keep_active:
        with contextlib.suppress(OSError):
            (dan_dir(repo) / 'locked').unlink()
    return n


@contextlib.contextmanager
def opened(repo, rels):
    """For an updater: the files rels and every folder above them (and above the folders they will create) can be
    written inside the block; afterwards the whole plan is locked again. Nothing happens when locking is not active."""
    repo = str(repo)
    if not active(repo):
        yield
        return
    taken = set()
    for rel in rels:
        parts = rel.split('/')
        for k in range(len(parts) + 1):
            taken.add('/'.join(parts[:k]))
    try:
        for rel in sorted(taken, key=len):          # folders first, so a missing file's folder is open
            _set(repo, rel, False)
        yield
    finally:
        lock(repo)


def status(repo=None):
    repo = str(repo or live_root())
    if not SUPPORTED:
        return 'chflags is not available here: the running folder is not locked'
    files, folders = plan(repo)
    off = [p for p in files if not os.lstat(os.path.join(repo, p)).st_flags & FLAG]
    off += [d + '/' for d in folders if not os.lstat(os.path.join(repo, d) if d else repo).st_flags & FLAG]
    head = 'kept locked' if active(repo) else 'NOT kept locked (python scripts/live_lock.py lock)'
    return (f'{head}: {len(files)} files, {len(folders)} folders in the plan; not locked now: {len(off)}'
            + (': ' + ', '.join(off[:10]) + (' ...' if len(off) > 10 else '') if off else ''))


def main(argv):
    sys.stdout.reconfigure(encoding='utf-8')
    repo = argv[argv.index('--repo') + 1] if '--repo' in argv else str(live_root())
    cmd = next((a for a in argv if a in ('status', 'lock', 'unlock')), 'status')
    if cmd == 'lock':
        nf, nd, bad = lock(repo)
        print(f'locked {nf} files and {nd} folders' + (f'; could not lock: {bad[:10]}' if bad else ''))
        return 1 if bad else 0
    if cmd == 'unlock':
        print(f'took the flag off {unlock(repo)} files and folders; the folder is no longer kept locked')
        return 0
    print(status(repo))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
