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
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
NUL = bytes([0])


def live_root(start=None) -> Path:
    """The folder Dan runs from: DAN_LIVE_TREE, else the main checkout of the repository this script is in.
    From a worktree (/Users/mikihonda/dan-workspace/<name>) that is still the running folder, not the worktree."""
    if os.environ.get('DAN_LIVE_TREE'):
        return Path(os.environ['DAN_LIVE_TREE'])
    top = Path(start or Path(__file__).resolve().parents[1])
    dot = top / '.git'
    if dot.is_file():                                # a worktree: "gitdir: <main>/.git/worktrees/<name>"
        try:
            line = dot.read_text(encoding='utf-8').strip()
            if line.startswith('gitdir:'):
                common = Path(line[7:].strip()).resolve().parent.parent
                if common.name == '.git':
                    return common.parent
        except OSError:
            pass
    return top


ROOT = live_root()


def dan_dir(repo) -> Path:
    """Where these tools keep their lock, journal and the copies they set aside: inside the folder's .git, which git
    never shows as a change and no .gitignore has to mention."""
    g = Path(repo) / '.git'
    if not g.is_dir():
        g = Path(_git(repo, 'rev-parse', '--path-format=absolute', '--git-common-dir').stdout.decode().strip())
    d = g / 'dan'
    d.mkdir(parents=True, exist_ok=True)
    return d


@contextlib.contextmanager
def tree_lock(repo, wait=60.0):
    """Only one of follow_github / rescue_wip / the guard's sweep changes the running folder at a time.
    Yields True when held, False when another holder kept it for `wait` seconds."""
    fh = open(dan_dir(repo) / 'tree.lock', 'a+')
    got = False
    try:
        try:
            import fcntl
        except ImportError:                          # Windows: msvcrt locks a byte range
            import msvcrt
            end = time.time() + wait
            while True:
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    got = True
                    break
                except OSError:
                    if time.time() >= end:
                        break
                    time.sleep(0.2)
            yield got
            if got:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            return
        end = time.time() + wait
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = True
                break
            except OSError:
                if time.time() >= end:
                    break
                time.sleep(0.2)
        yield got
    finally:
        fh.close()                                   # closing releases the lock


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


def status(repo=ROOT, renames=False):
    """(code, path) for everything uncommitted here: tracked files changed, files git would track.
    A rename (`git mv`) is two entries: ('R ', new name) and ('D ', old name) — both hold part of the work.
    With renames=True each entry is (code, path, old name or None)."""
    raw = _out(repo, 'status', '--porcelain=v1', '-z', '--untracked-files=all', '--no-renames')
    out, items = [], raw.split(NUL)
    i = 0
    while i < len(items):
        item = items[i].decode('utf-8', 'surrogateescape')
        if item:
            orig = None
            if item[0] in 'RC' and i + 1 < len(items):      # --no-renames still leaves copies/renames of some gits
                orig = items[i + 1].decode('utf-8', 'surrogateescape')
                i += 1
            out.append((item[:2], item[3:], orig))
            if orig and item[0] == 'R':
                out.append(('D ', orig, None))
        i += 1
    return out if renames else [(c, p) for c, p, _ in out]


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


def ignored_by(repo, theirs, paths):
    """Those of paths that the .gitignore of commit `theirs` ignores, itself or by one of its folders
    (git check-ignore --no-index sees a folder pattern like /.data/ only when asked about the folder)."""
    if not paths:
        return set()
    asked = set()
    for p in paths:
        asked.add(p)
        parts = p.split('/')
        asked.update('/'.join(parts[:k]) + '/' for k in range(1, len(parts)))
    # Asked in an empty repository holding only the commit's .gitignore files: this folder's own .git/info/exclude
    # and the machine's global excludes are not GitHub's rules (a copied Windows exclude file once ignored everything).
    with tempfile.TemporaryDirectory() as tmp:
        _git(tmp, 'init', '-q')
        names = _paths(_out(repo, 'ls-tree', '-r', '-z', '--name-only', theirs))
        for name in (n for n in names if n == '.gitignore' or n.endswith('/.gitignore')):
            dst = os.path.join(tmp, name)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'wb') as fh:
                fh.write(_out(repo, 'cat-file', 'blob', f'{theirs}:{name}'))
        p = _git(tmp, '-c', 'core.excludesFile=', 'check-ignore', '--no-index', '-z', '--stdin',
                 data=NUL.join(x.encode('utf-8', 'surrogateescape') for x in sorted(asked)) + NUL)
    hit = set(_paths(p.stdout))
    out = set()
    for path in paths:
        parts = path.split('/')
        if path in hit or any('/'.join(parts[:k]) + '/' in hit for k in range(1, len(parts))):
            out.add(path)
    return out


_ignored_by = ignored_by


def _kept_untracked(repo, base, theirs):
    """Files GitHub deletes that its .gitignore ignores and that are here: they stay here as local files."""
    gone = _paths(_out(repo, 'diff', '--name-only', '--no-renames', '--diff-filter=D', '-z', base, theirs))
    here = [p for p in gone if os.path.isfile(os.path.join(repo, p))]
    return sorted(_ignored_by(repo, theirs, here))


def _displaced(repo, base, theirs):
    """Local files git ignores here that GitHub starts tracking with other content. Git would overwrite them without
    a word (an ignored file counts as expendable); they are copied aside first."""
    added = _paths(_out(repo, 'diff', '--name-only', '--no-renames', '--diff-filter=A', '-z', base, theirs))
    out = []
    for rel in added:
        full = os.path.join(repo, rel)
        if not os.path.isfile(full) or _git(repo, 'ls-files', '--error-unmatch', '--', rel).returncode == 0:
            continue
        mine = _git(repo, 'hash-object', '--path', rel, '--', full).stdout.decode().strip()
        if mine != _git(repo, 'rev-parse', f'{theirs}:{rel}').stdout.decode().strip():
            out.append(rel)
    return out


def _copy_aside(repo, paths, kind):
    """Copy files to .git/dan/follow_github/<kind>-<time>/ (on disk, so a crash halfway loses nothing)."""
    if not paths:
        return None
    where = dan_dir(repo) / 'follow_github' / f"{kind}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
    for rel in paths:
        dst = where / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(os.path.join(repo, rel), dst)
    return where


def follow(repo=ROOT, target='origin/main', fetch=True, dry=False, packages=True):
    """(True, what happened) when the folder is on the target; (False, why) when stopped with nothing changed,
    or when the folder moved but the frontend's packages could not be installed (said so)."""
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
        with tree_lock(repo) as held:
            if not held:
                return False, 'another tool (rescue_wip or the guard) is changing the folder right now: not touched; run again'
            return _follow_locked(repo, target, branch, dry, packages)
    except Exception as exc:   # an unexpected git answer: say it, leave the folder as it is
        return False, f'could not compare the folder with GitHub: {type(exc).__name__}: {exc}'


def _follow_locked(repo, target, branch, dry, packages):
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
    displaced = _displaced(repo, base, theirs)
    if dry:
        extra = f'; would set aside local files GitHub now tracks: {", ".join(displaced)}' if displaced else ''
        return True, f'would follow GitHub {branch} — {said}: ' + ', '.join(changed[:20]) + extra + note

    resaved = [p for code, p in status(repo) if code == ' M' and p in set(changed) and p not in left]
    if resaved:      # only re-saved with Windows line endings: let git see the committed text it will replace
        _out(repo, 'checkout-index', '-f', '-u', '--', *resaved)
    aside = _copy_aside(repo, displaced, 'replaced')
    keep = _copy_aside(repo, kept, 'kept')            # on disk before git deletes them; put back below
    dirty_kept = [p for p in kept if p in left]
    if dirty_kept:   # git would refuse to delete a changed file: let it see the committed one, put ours back after
        _out(repo, 'checkout-index', '-f', '-u', '--', *dirty_kept)
    moved = _git(repo, 'merge', '--ff-only', '--quiet', theirs)
    for rel in kept:
        if moved.returncode == 0 or rel in dirty_kept:
            dst = os.path.join(repo, rel)
            os.makedirs(os.path.dirname(dst) or repo, exist_ok=True)
            shutil.copy2(keep / rel, dst)
    if keep:
        shutil.rmtree(keep, ignore_errors=True)       # every kept file is back in place
    if moved.returncode:
        return False, ('NOT brought up to GitHub main; git refused and nothing was changed. Files left uncommitted '
                       'here are in the way: move them to a branch (python scripts/rescue_wip.py --apply), then run '
                       'this again.\n' + moved.stderr.decode('utf-8', 'replace').strip()[-800:])
    note = _note(leftovers(repo))
    keep_note = f'; kept as local files: {", ".join(kept)}' if kept else ''
    if aside:
        keep_note += (f'; local files GitHub now tracks were replaced by GitHub\'s version, the local copies are in '
                      f'{aside}: {", ".join(displaced)}')
    done = f'now on GitHub {branch} ({theirs[:8]}) — {said}{keep_note}' + note
    if packages and {'frontend/package.json', 'frontend/package-lock.json'} & set(changed):
        ok, why = _install_frontend(repo)
        if not ok:
            return False, done + '\nBUT the frontend packages could not be installed (the screens may not build): ' + why
        done += '\nfrontend packages installed (' + why + ')'
    return True, done


def _install_frontend(repo):
    """package.json changed on GitHub: install it into the folder's node_modules, with the artifacts' own packages."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hook_autoinstall_npm import install_live   # noqa: E402
    return install_live(Path(repo) / 'frontend')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    args = sys.argv[1:]
    where = args[args.index('--repo') + 1] if '--repo' in args else ROOT
    ok, what = follow(where, fetch='--no-fetch' not in args, dry='--dry' in args)
    print(what)
    sys.exit(0 if ok else 1)
