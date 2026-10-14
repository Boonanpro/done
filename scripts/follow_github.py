"""Bring this folder (the code Dan runs from) up to GitHub main, through git itself.

The folder is shared: several workers edit it at once and it always holds work nobody has committed yet. A plain
`git pull` stops on the first such file, so for months nobody pulled, and each worker kept the folder in step with
GitHub by hand. Nothing noticed a fix that was on GitHub and not in the folder, and committing such a file from the
folder would have taken the fix back out of GitHub (2026-10-14: the folder said it was on the commit of 10-11, 34 behind).

What this does, for every file GitHub changed since the commit the folder is on:
- the folder already holds GitHub's content, alone or under uncommitted work of its own: nothing in the file changes
- the folder still has the old content, untouched: git brings in GitHub's
- the folder lacks GitHub's change and has uncommitted work in the same file: STOP. Nothing at all is changed, and the
  files are named. Someone decides how the two fit, commits or puts the file right, and runs this again.
Then the folder's commit moves to GitHub main (a fast-forward; git itself refuses anything else), and `git status`
shows the uncommitted work and nothing more.

Run it after pushing and before restarting Dan (scripts/restart_dan_core.py runs it). In this folder it replaces
`git pull`, which stays forbidden along with stash, reset --hard and checkout.

Usage: python scripts/follow_github.py [--no-fetch] [--dry]     exit 0 = on GitHub main, 1 = stopped (reason printed)
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
NUL, CRLF, LF = bytes([0]), bytes([13, 10]), bytes([10])


def _git(repo, *args, data=None):
    return subprocess.run(['git', '-c', 'core.quotepath=off', '--literal-pathspecs', *args], cwd=str(repo), input=data,
                          capture_output=True, creationflags=NO_WINDOW)


def _out(repo, *args, data=None):
    p = _git(repo, *args, data=data)
    if p.returncode:
        raise RuntimeError(f"git {' '.join(args[:2])}: {p.stderr.decode('utf-8', 'replace').strip()[:400]}")
    return p.stdout


def _tree(repo, rev):
    """path -> blob id for every file of a commit."""
    files = {}
    for entry in _out(repo, 'ls-tree', '-r', '-z', rev).split(NUL):
        if entry:
            meta, path = entry.split(b'\t', 1)
            files[path.decode('utf-8', 'surrogateescape')] = meta.split()[2].decode()
    return files


def _blobs(repo, ids):
    """blob id -> its bytes, in one git process."""
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    out, got, at = _out(repo, 'cat-file', '--batch', data=LF.join(i.encode() for i in ids) + LF), {}, 0
    for blob in ids:
        end = out.index(LF, at)
        size = int(out[at:end].split()[2])
        got[blob] = out[end + 1:end + 1 + size]
        at = end + 1 + size + 1
    return got


def _text(data):
    """Bytes with Windows line endings read as plain ones (a file with a NUL is not text: left as it is). The folder's
    files are saved either way, and git, set to convert them here, does not count that as a change."""
    return data if data is None or NUL in data else data.replace(CRLF, LF)


def _in_folder(repo, path):
    try:
        with open(os.path.join(repo, path), 'rb') as f:
            return f.read()
    except OSError:
        return None


def _holds(here, before, github):
    """True when the file in the folder already has everything GitHub changed in it (merging GitHub's change in would
    leave the file exactly as it is), so the rest of it is uncommitted work on top."""
    with tempfile.TemporaryDirectory() as d:
        names = []
        for name, data in (('here', here), ('before', before or b''), ('github', github)):
            names.append(os.path.join(d, name))
            with open(names[-1], 'wb') as f:
                f.write(data)
        merged = subprocess.run(['git', 'merge-file', '-p', *names], capture_output=True, creationflags=NO_WINDOW)
        return merged.returncode == 0 and merged.stdout == here


def follow(repo=ROOT, target='origin/main', fetch=True, dry=False):
    """(True, what happened) when the folder is on the target; (False, why) when stopped with nothing changed."""
    repo = str(repo)
    remote, _, branch = target.partition('/')
    try:
        on = _git(repo, 'symbolic-ref', '--short', 'HEAD').stdout.decode().strip()
        if on != branch:
            return False, f"the folder is on '{on or 'no branch'}', not '{branch}': not touched"
        if any(os.path.exists(os.path.join(repo, '.git', name)) for name in ('MERGE_HEAD', 'rebase-merge', 'rebase-apply')):
            return False, 'a merge or rebase is open in the folder: not touched'
        if fetch:
            got = _git(repo, 'fetch', '--quiet', remote, branch)
            if got.returncode:   # asked once; never retried here (GitHub is used at a human pace)
                return False, 'GitHub could not be reached, so the folder was not compared: ' + got.stderr.decode('utf-8', 'replace').strip()[-300:]
        base, theirs = _out(repo, 'rev-parse', 'HEAD').decode().strip(), _out(repo, 'rev-parse', target).decode().strip()
        if base == theirs:
            return True, f'already on GitHub {branch} ({theirs[:8]})'
        if _git(repo, 'merge-base', '--is-ancestor', base, theirs).returncode:
            return False, f"the folder's commit {base[:8]} is not part of GitHub {branch}: there are commits here that were never pushed. Not touched"

        changed = [p.decode('utf-8', 'surrogateescape')
                   for p in _out(repo, 'diff', '--name-only', '--no-renames', '-z', base, theirs).split(NUL) if p]
        before, github = _tree(repo, base), _tree(repo, theirs)
        stored = _blobs(repo, [tree.get(p) for p in changed for tree in (before, github)])
        same, brought, blocked = [], [], []
        for path in changed:
            b, t = _text(stored.get(before.get(path))), _text(stored.get(github.get(path)))
            o = _text(_in_folder(repo, path))
            if os.path.isdir(os.path.join(repo, path)):
                blocked.append(f'{path}: a folder here, a file on GitHub')
            elif o == t:
                same.append(path)                        # both None: deleted on GitHub and already gone here
            elif o == b:
                brought.append(path)                     # untouched here (or not here yet): git puts GitHub's in
            elif o is None:
                blocked.append(f'{path}: deleted here, changed on GitHub')
            elif t is None:
                blocked.append(f'{path}: changed here, deleted on GitHub')
            elif _holds(o, b, t):
                same.append(path)                        # GitHub's change plus uncommitted work on top
            else:
                blocked.append(f"{path}: lacks GitHub's change and has uncommitted work in the same file")
        commits = _out(repo, 'rev-list', '--count', f'{base}..{theirs}').decode().strip()
        if blocked:
            return False, (f'NOT brought up to GitHub {branch} ({commits} commits behind); nothing was changed. '
                           'Decide how these fit, then run again:\n  ' + '\n  '.join(blocked))
        said = (f'{commits} commits, {len(changed)} files GitHub changed: {len(same)} already held here, '
                f'{len(brought)} brought in from GitHub' + (': ' + ', '.join(brought[:20]) if brought else ''))
        if dry:
            return True, f'would follow GitHub {branch} — {said}'

        # The files that already hold GitHub's content: tell git so (its list of the files only; no file is written).
        # Without this git sees them as changed against the old commit and refuses the whole fast-forward.
        listed = NUL.join(p.encode('utf-8', 'surrogateescape') for p in same)
        if same:
            _out(repo, 'reset', '-q', theirs, '--pathspec-from-file=-', '--pathspec-file-nul', data=listed)
        moved = _git(repo, 'merge', '--ff-only', '--quiet', theirs)
        if moved.returncode:
            if same:
                _out(repo, 'reset', '-q', base, '--pathspec-from-file=-', '--pathspec-file-nul', data=listed)
            return False, 'git refused the fast-forward; nothing was changed:\n' + moved.stderr.decode('utf-8', 'replace').strip()[-800:]
        return True, f'now on GitHub {branch} ({theirs[:8]}) — {said}'
    except Exception as exc:   # an unexpected git answer: say it, leave the folder as it is
        return False, f'could not compare the folder with GitHub: {type(exc).__name__}: {exc}'


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    ok, what = follow(fetch='--no-fetch' not in sys.argv, dry='--dry' in sys.argv)
    print(what)
    sys.exit(0 if ok else 1)
