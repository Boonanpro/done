"""Bring this folder (the code Dan runs from) up to GitHub main. It is the only thing that changes what git tracks here.

Since 2026-10-18 nobody writes the tracked files of this folder: every piece of work has its own worktree and branch
(scripts/work.py), and scripts/hook_live_tree_guard.py refuses writes here. So following GitHub is git's own
fast-forward. Git refuses it, changing nothing, when a file left uncommitted here would be overwritten; that file is
named, and scripts/rescue_wip.py moves it to a branch of its own.

One more case is handled: a file GitHub stops tracking and now ignores (a file a machine writes, such as
.claude/settings.local.json) stays here as it is, instead of being deleted by the fast-forward.

Before 2026-10-18 the folder held everyone's unfinished work, files were copied in by hand, and this script compared
three versions of every file to get past them (the history of scripts/follow_github.py has that version).

Run it after a merge on GitHub (scripts/work.py ship does) and before restarting Dan (scripts/restart_dan_core.py does).
`git pull`, stash, reset, checkout and restore stay off-limits here.

Usage: python scripts/follow_github.py [--no-fetch] [--dry] [--repo PATH]   exit 0 = on GitHub main, 1 = stopped
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
NUL = bytes([0])


def _git(repo, *args, data=None, env=None):
    return subprocess.run(['git', '-c', 'core.quotepath=off', *args], cwd=str(repo), input=data, capture_output=True,
                          creationflags=NO_WINDOW, env=env)


def _out(repo, *args, data=None):
    p = _git(repo, *args, data=data)
    if p.returncode:
        raise RuntimeError(f"git {' '.join(args[:2])}: {p.stderr.decode('utf-8', 'replace').strip()[:400]}")
    return p.stdout


def _paths(raw):
    return [p.decode('utf-8', 'surrogateescape') for p in raw.split(NUL) if p]


def status(repo=ROOT):
    """(code, path) for everything uncommitted here: tracked files changed, files git would track."""
    raw = _out(repo, 'status', '--porcelain=v1', '-z', '--untracked-files=all')
    out, items = [], raw.split(NUL)
    i = 0
    while i < len(items):
        item = items[i].decode('utf-8', 'surrogateescape')
        if item:
            out.append((item[:2], item[3:]))
            if item[0] in 'RC':
                i += 1                                       # the rename's old name follows
        i += 1
    return out


def line_endings_only(repo, paths):
    """The changed files whose text is the committed text saved with Windows line endings: nothing to keep in them.
    Git still lists them as changed after core.autocrlf was switched on, and refuses to overwrite them."""
    paths = [p for p in paths if os.path.isfile(os.path.join(repo, p))]
    if not paths:
        return set()
    out = _out(repo, 'cat-file', '--batch', data=b''.join(f'HEAD:{p}\n'.encode('utf-8', 'surrogateescape') for p in paths))
    same, at = set(), 0
    for path in paths:
        end = out.index(b'\n', at)
        head = out[at:end].split()
        if len(head) < 3 or head[1] != b'blob':
            at = end + 1
            continue
        size = int(head[2])
        blob = out[end + 1:end + 1 + size]
        at = end + 1 + size + 1
        with open(os.path.join(repo, path), 'rb') as fh:
            here = fh.read()
        if NUL not in here and here.replace(b'\r\n', b'\n') == blob.replace(b'\r\n', b'\n'):
            same.add(path)
    return same


def leftovers(repo=ROOT):
    """What is uncommitted here and holds work: it belongs on a branch."""
    items = status(repo)
    same = line_endings_only(repo, [p for code, p in items if code == ' M'])
    return [p for code, p in items if p not in same]


def _note(left):
    if not left:
        return ''
    return (f'\nUncommitted here ({len(left)}), on no branch: ' + ', '.join(left[:15]) + (' ...' if len(left) > 15 else '')
            + '\n  -> python scripts/rescue_wip.py lists them by the session that wrote them; --apply moves them to branches')


def _kept_untracked(repo, base, theirs):
    """Files GitHub deletes that its .gitignore ignores and that are here: path -> bytes, to put back afterwards."""
    gone = _paths(_out(repo, 'diff', '--name-only', '--no-renames', '--diff-filter=D', '-z', base, theirs))
    here = [p for p in gone if os.path.isfile(os.path.join(repo, p))]
    if not here:
        return {}
    ignore = _git(repo, 'show', f'{theirs}:.gitignore').stdout
    with tempfile.NamedTemporaryFile('wb', delete=False, suffix='.gitignore') as f:
        f.write(ignore)
    try:
        p = _git(repo, '-c', f'core.excludesFile={f.name}', 'check-ignore', '--no-index', '-z', '--stdin',
                 data=NUL.join(x.encode('utf-8', 'surrogateescape') for x in here) + NUL)
    finally:
        os.unlink(f.name)
    kept = {}
    for path in _paths(p.stdout):
        with open(os.path.join(repo, path), 'rb') as fh:
            kept[path] = fh.read()
    return kept


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
        left = leftovers(repo)
        note = _note(left)
        if base == theirs:
            return True, f'already on GitHub {branch} ({theirs[:8]})' + note
        if _git(repo, 'merge-base', '--is-ancestor', base, theirs).returncode:
            return False, f"the folder's commit {base[:8]} is not part of GitHub {branch}: there are commits here that were never pushed. Not touched"
        changed = _paths(_out(repo, 'diff', '--name-only', '--no-renames', '-z', base, theirs))
        commits = _out(repo, 'rev-list', '--count', f'{base}..{theirs}').decode().strip()
        said = f'{commits} commits, {len(changed)} files'
        kept = _kept_untracked(repo, base, theirs)
        hit = sorted((set(changed) & set(left)) - set(kept))   # git alone would quietly bring back a file deleted here
        if hit:
            return False, ('NOT brought up to GitHub main; nothing was changed. These files are uncommitted here and '
                           'changed on GitHub: ' + ', '.join(hit) + '\n  -> move them to a branch '
                           '(python scripts/rescue_wip.py --apply), then run this again.' + note)
        if dry:
            return True, f'would follow GitHub {branch} — {said}: ' + ', '.join(changed[:20]) + note

        resaved = [p for code, p in status(repo) if code == ' M' and p in set(changed) and p not in left]
        if resaved:      # only re-saved with Windows line endings: let git see the committed text it will replace
            _out(repo, 'checkout-index', '-f', '-u', '--', *resaved)
        dirty_kept = [p for p in kept if p in left]
        if dirty_kept:   # git would refuse to delete a changed file: let it see the committed one, put ours back after
            _out(repo, 'checkout-index', '-f', '-u', '--', *dirty_kept)
        moved = _git(repo, 'merge', '--ff-only', '--quiet', theirs)
        for path, data in kept.items():
            if moved.returncode == 0 or path in dirty_kept:
                os.makedirs(os.path.dirname(os.path.join(repo, path)) or repo, exist_ok=True)
                with open(os.path.join(repo, path), 'wb') as fh:
                    fh.write(data)
        if moved.returncode:
            return False, ('NOT brought up to GitHub main; git refused and nothing was changed. Files left uncommitted '
                           'here are in the way: move them to a branch (python scripts/rescue_wip.py --apply), then run '
                           'this again.\n' + moved.stderr.decode('utf-8', 'replace').strip()[-800:])
        note = _note(leftovers(repo))
        keep_note = f'; kept as local files: {", ".join(kept)}' if kept else ''
        return True, f'now on GitHub {branch} ({theirs[:8]}) — {said}{keep_note}' + note
    except Exception as exc:   # an unexpected git answer: say it, leave the folder as it is
        return False, f'could not compare the folder with GitHub: {type(exc).__name__}: {exc}'


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    args = sys.argv[1:]
    where = args[args.index('--repo') + 1] if '--repo' in args else ROOT
    ok, what = follow(where, fetch='--no-fetch' not in args, dry='--dry' in args)
    print(what)
    sys.exit(0 if ok else 1)
