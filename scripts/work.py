"""One way to work on Dan: each piece of work in its own worktree and branch, one road to the running folder.

    python ~/done/scripts/work.py new <name> [--from <branch>]   a worktree ~/dan-workspace/<name> on branch dan/<name>
    python ~/done/scripts/work.py save [what] [--only PATH...]   commit this worktree's changes (often: git keeps them)
    python ~/done/scripts/work.py test [-- COMMAND...]           save, run the tests (remembered), note what passed
    python ~/done/scripts/work.py try [stop]                     run this worktree: API on 8001, screens on 3002
    python ~/done/scripts/work.py venv                           this worktree's own Python (.venv), for pip install
    python ~/done/scripts/work.py ship "<title>" [--body TEXT] [--no-follow]   take in main, test again, push, PR, merge,
                                                                 follow_github
    python ~/done/scripts/work.py list                           every branch of work, where it is, how far from main

Why (2026-10-17/18): sessions wrote unfinished work straight into the running folder (~/done, D:\\done on Windows).
Shipping one change ran into seven files of other sessions' half-done work, and a dashboard rebuild would have
published all of it. Now the running folder is written only by follow_github (scripts/hook_live_tree_guard.py refuses
other writes and moves out what slips through), so no piece of work can overwrite, publish or lose another's. Clashes
with other work show up in `ship`, on your own branch, where you settle them before anything reaches the running folder.

Each worktree has its own packages: frontend/node_modules is a copy-on-write clone of the running folder's (APFS: a few
seconds, no extra space), and `venv` makes a clone of the shared Python. Installing in a worktree never reaches the
running Dan or another worktree.

`ship` pushes only what was tested: after taking in main it runs the remembered test again when main brought anything
new, and stops on a failure before anything leaves the machine. It says plainly when GitHub has the change but the
running folder could not follow (exit 1).

`save`, `test`, `try` and `ship` act on the worktree you are in (or --at <path>). GitHub is used at a human pace:
`ship` asks each thing once and stops at the first refusal; collect related work into one ship.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from follow_github import live_root  # noqa: E402

LIVE = live_root()
WORKSPACE = Path(os.environ.get('DAN_WORKTREES') or ('D:/dan-workspace' if os.name == 'nt' else Path.home() / 'dan-workspace'))
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
GH = os.environ.get('DAN_GH') or 'gh'
TRY_PORTS = {'api': 8001, 'screens': 3002}


class Stop(Exception):
    """A step that cannot go on; the message says what to do. `steps` are what was already done."""

    def __init__(self, message, steps=()):
        super().__init__(message)
        self.steps = list(steps)


def git(where, *args, check=True):
    p = subprocess.run(['git', '-c', 'core.quotepath=off', *args], cwd=str(where), capture_output=True, text=True,
                       encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
    if check and p.returncode:
        raise Stop(f"git {' '.join(args[:2])}: {(p.stderr or p.stdout).strip()[-600:]}")
    return p


def _same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def here(at=None):
    """The worktree to act on: --at, else the one the current folder is in. Never the running folder."""
    top = git(at or os.getcwd(), 'rev-parse', '--show-toplevel', check=False).stdout.strip()
    if not top:
        raise Stop('ここは git の作業場所ではありません。作業場所の中で動かすか --at <path> を付けてください。')
    if _same(top, LIVE):
        raise Stop(f'{LIVE} は動いているダンです。ここでは作業しません。'
                   f'`python {LIVE.as_posix()}/scripts/work.py new <名前>` で作業場所を作ってください。')
    return Path(top)


def branch_of(wt):
    b = git(wt, 'symbolic-ref', '--short', 'HEAD', check=False).stdout.strip()
    if not b or b == 'main':
        raise Stop(f'{wt} は {b or "分岐の無い状態"} です。work.py new で作った分岐（dan/...）の中で動かしてください。')
    return b


# --- new / save / list -----------------------------------------------------------------------------------------------------

def new(name, start=None):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name):
        raise Stop('名前は英数字と - . _ で付けてください（例: chat-shape-answer）。')
    path, branch = WORKSPACE / name, f'dan/{name}'
    if path.exists():
        raise Stop(f'{path} はもうあります。続きならそこで作業してください。')
    if start is None:
        git(LIVE, 'fetch', '--quiet', 'origin', 'main')
        start = 'origin/main'
    git(LIVE, 'worktree', 'add', '-b', branch, str(path), start)
    _own_node_modules(path)
    return path, branch, start


def _clone_tree(src, dst):
    """A copy that costs nothing until one side changes: APFS clonefile on a Mac, reflink where Linux has it.
    Windows has no such copy; there the packages are installed fresh (npm ci) when asked."""
    if sys.platform == 'darwin':
        cmd = ['cp', '-cR', str(src), str(dst)]
    elif os.name != 'nt':
        cmd = ['cp', '-a', '--reflink=auto', str(src), str(dst)]
    else:
        return False
    return subprocess.run(cmd, capture_output=True).returncode == 0


def _own_node_modules(wt):
    """The worktree's frontend gets its own node_modules, cloned from the running folder's. (Until 2026-10-23 it was a
    link to the running folder's, so `npm install` in a worktree changed the running Dan's packages.)"""
    src, dst = LIVE / 'frontend' / 'node_modules', wt / 'frontend' / 'node_modules'
    if not src.is_dir() or os.path.lexists(dst) or not dst.parent.is_dir():
        return False
    return _clone_tree(src, dst)


def venv(wt):
    """This worktree's own Python: a clone of the shared one in <worktree>/.venv. pip install there stays there."""
    dst = wt / '.venv'
    if dst.exists():
        return dst, False
    src = Path(os.environ.get('DAN_VENV') or sys.prefix)
    if src == Path(sys.base_prefix) or not (src / 'pyvenv.cfg').exists():
        raise Stop(f'{src} は venv ではないので写せません。DAN_VENV=<venv の場所> を付けてください。')
    if not _clone_tree(src, dst):
        raise Stop(f'{src} を {dst} へ写せませんでした。`python -m venv {dst}` で作り、requirements.txt を入れてください。')
    return dst, True


def _python(wt):
    own = wt / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    return str(own) if own.exists() else sys.executable


def _top_dirs(wt):
    return {line for line in git(wt, 'ls-tree', '--name-only', '-d', 'HEAD').stdout.splitlines() if line}


def changes(wt):
    """(to_save, left_out): changes to tracked files and new files are work, except new files in a top folder the
    repository does not have (notes, a REPORT/, scratch), which are left out unless named with --only."""
    tops = _top_dirs(wt)
    tracked = [l[3:] for l in git(wt, 'status', '--porcelain=v1', '--untracked-files=no', '--no-renames').stdout.splitlines()]
    new = [p for p in git(wt, 'ls-files', '--others', '--exclude-standard').stdout.splitlines() if p]
    take = [p for p in new if '/' not in p or p.split('/', 1)[0] in tops]
    return tracked + take, [p for p in new if p not in take]


def save(wt, what=None, only=None):
    """Commit this worktree's work. Returns the short commit, or None when there is nothing new."""
    if only:
        git(wt, 'add', '--', *only)
    else:
        git(wt, 'add', '-u')
        take = changes(wt)[0]
        new = [p for p in take if git(wt, 'ls-files', '--error-unmatch', '--', p, check=False).returncode]
        if new:
            git(wt, 'add', '--', *new)
    if not git(wt, 'diff', '--cached', '--quiet', check=False).returncode:
        return None
    git(wt, 'commit', '-q', '-m', f"wip: {what or datetime.now().strftime('%Y-%m-%d %H:%M')}")
    return git(wt, 'rev-parse', '--short', 'HEAD').stdout.strip()


# --- test ----------------------------------------------------------------------------------------------------------------

def _test_file(wt):
    return Path(git(wt, 'rev-parse', '--absolute-git-dir').stdout.strip()) / 'dan-test.json'


def _tree(wt):
    return git(wt, 'rev-parse', 'HEAD^{tree}').stdout.strip()


def test(wt, command=None):
    """Save, then run the tests (the command given, else the one this worktree used last). Remembers what passed.
    Returns (passed, output tail)."""
    save(wt, 'before test')
    f = _test_file(wt)
    if not command:
        try:
            command = json.loads(f.read_text(encoding='utf-8'))['command']
        except (OSError, ValueError, KeyError):
            raise Stop('どの試験を流すかを1度だけ教えてください: `work.py test -- python -m pytest -q tests/test_x.py`（次からは覚えています）')
    env = {**os.environ, 'PATH': str(Path(_python(wt)).parent) + os.pathsep + os.environ.get('PATH', '')}
    p = subprocess.run(command, cwd=str(wt), shell=True, capture_output=True, text=True, encoding='utf-8',
                       errors='replace', env=env, creationflags=NO_WINDOW)
    tail = (p.stdout + p.stderr).strip()[-1500:]
    f.write_text(json.dumps({'command': command, 'tree': _tree(wt) if p.returncode == 0 else None,
                             'at': datetime.now().isoformat(timespec='seconds')}), encoding='utf-8')
    return p.returncode == 0, tail


def _tested(wt):
    try:
        return json.loads(_test_file(wt).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def listing():
    wts, cur = {}, {}
    for line in git(LIVE, 'worktree', 'list', '--porcelain').stdout.splitlines():
        if line.startswith('worktree '):
            cur = {'path': line[9:]}
        elif line.startswith('branch '):
            wts[line[7:].replace('refs/heads/', '')] = cur['path']
    rows = []
    refs = git(LIVE, 'for-each-ref', '--sort=-committerdate', '--format=%(refname:short)|%(committerdate:short)|%(subject)',
               'refs/heads/dan/', 'refs/heads/wip/').stdout.splitlines()
    for line in refs:
        name, day, subject = line.split('|', 2)
        counts = git(LIVE, 'rev-list', '--left-right', '--count', f'origin/main...{name}', check=False).stdout.split()
        behind, ahead = (counts + ['?', '?'])[:2]
        rows.append((name, day, ahead, behind, wts.get(name, ''), subject[:60]))
    return rows


# --- try ----------------------------------------------------------------------------------------------------------------------

def _env_file(path):
    env = {}
    try:
        for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
            m = re.match(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$', line)
            if m and not line.lstrip().startswith('#'):
                env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def _port_open(port):
    import socket
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0


def try_up(wt):
    """API (app.sandbox) from this worktree on 8001 and the screens (next dev) on 3002, talking to 8001.
    The secrets are read from the running folder's .env files into the processes; nothing is copied."""
    state = wt / '.data' / 'try'
    state.mkdir(parents=True, exist_ok=True)
    started = {}
    flags = NO_WINDOW | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    own = {'start_new_session': os.name != 'nt'}            # try stop ends the whole group
    for what, port in TRY_PORTS.items():
        if _port_open(port):
            raise Stop(f'{port} 番はもう使われています（別の作業が試しているかもしれません）。'
                       f'自分が立てた物なら `work.py try stop`、違うなら終わるのを待ってください。')
    env = {**os.environ, **_env_file(LIVE / '.env'), 'PYTHONIOENCODING': 'utf-8'}
    log = open(state / 'api.log', 'w', encoding='utf-8')
    api = subprocess.Popen([_python(wt), '-m', 'uvicorn', 'app.sandbox.main:app', '--host', '127.0.0.1',
                            '--port', str(TRY_PORTS['api'])], cwd=str(wt), env=env, stdout=log,
                           stderr=subprocess.STDOUT, creationflags=flags, **own)
    started['api'] = api.pid
    fenv = {**os.environ, **_env_file(LIVE / 'frontend' / '.env.local'),
            'BACKEND_URL': f"http://127.0.0.1:{TRY_PORTS['api']}", 'NEXT_DIST_DIR': '.next-preview'}
    log = open(state / 'screens.log', 'w', encoding='utf-8')
    subprocess.run([_python(wt), str(wt / 'scripts' / 'wire_artifact_tailwind_sources.py')], stdout=log,
                   stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    if not (wt / 'frontend' / 'node_modules').is_dir():
        _own_node_modules(wt)
    # webpack: the same bundler as the owner's preview (3001)
    nxt = wt / 'frontend' / 'node_modules' / '.bin' / ('next.cmd' if os.name == 'nt' else 'next')
    web = subprocess.Popen([str(nxt), 'dev', '--webpack', '--port', str(TRY_PORTS['screens'])],
                           cwd=str(wt / 'frontend'), env=fenv, stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
                           **own)
    started['screens'] = web.pid
    (state / 'pids.json').write_text(json.dumps(started), encoding='utf-8')
    return started, state


def try_stop(wt):
    """Ends exactly the processes `try` started here (and their children)."""
    f = wt / '.data' / 'try' / 'pids.json'
    if not f.exists():
        return []
    ended = []
    for what, pid in json.loads(f.read_text(encoding='utf-8')).items():
        if os.name == 'nt':
            r = subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, creationflags=NO_WINDOW)
            ok = r.returncode == 0
        else:
            try:
                os.killpg(pid, signal.SIGTERM)
                ok = True
            except OSError:
                ok = False
        if ok:
            ended.append(what)
    f.unlink()
    return ended


# --- ship ---------------------------------------------------------------------------------------------------------------------

def ship(wt, title, body=None, follow=True):
    """Take in main, test what will be pushed, push, PR, merge, then bring the running folder up to main.
    Each outside request once. Returns (steps, restart hints); raises Stop when anything is not done."""
    branch = branch_of(wt)
    if changes(wt)[0]:
        raise Stop('保存していない変更があります。`work.py save` してから ship してください。')
    if not _tested(wt).get('command'):
        raise Stop('まだ試していません。`work.py test -- <試験のコマンド>` で試してから ship してください。')
    git(wt, 'fetch', '--quiet', 'origin', 'main')
    merged = git(wt, 'merge', '--no-edit', '-q', 'origin/main', check=False)
    if merged.returncode:
        clashes = git(wt, 'diff', '--name-only', '--diff-filter=U').stdout.split()
        raise Stop('最新の main とぶつかりました。ここ（自分の分岐）で直してください: ' + ', '.join(clashes) +
                   '\n直したら `work.py save "main を取り込み"` → `work.py test` → もう一度 `work.py ship`。'
                   '\nやめるなら `git merge --abort`（この作業場所の中だけが元に戻る）。')
    if int(git(wt, 'rev-list', '--count', 'origin/main..HEAD').stdout.strip() or 0) == 0:
        raise Stop('main に入っていない変更がありません。')
    steps = []
    if _tested(wt).get('tree') != _tree(wt):     # main brought something new, or the last test failed: test this tree
        ok, tail = test(wt)
        if not ok:
            raise Stop('main を取り込んだ後の試験が通りませんでした。何も外へ出していません（取り込みはこの作業場所の'
                       '分岐の中だけ）。直して `work.py save` → `work.py test` → もう一度 ship。\n' + tail[-800:])
        steps.append('tested with main: ' + (tail.splitlines() or [''])[-1][:120])
    p = git(wt, 'push', '-q', '-u', 'origin', branch, check=False)
    if p.returncode:
        raise Stop('push できませんでした（もう一度は試しません）: ' + p.stderr.strip()[-400:])
    steps.append(f'pushed {branch}')
    if body is None:
        body = git(wt, 'log', '--format=- %s', 'origin/main..HEAD').stdout.strip()
    body += '\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)'
    p = _gh(wt, 'pr', 'create', '--base', 'main', '--head', branch, '--title', title, '--body', body)
    if p.returncode:
        raise Stop('PR を作れませんでした（もう一度は試しません）: ' + (p.stderr or p.stdout).strip()[-400:])
    url = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ''
    steps.append(f'PR {url}')
    # No --delete-branch: gh would then switch this worktree to main, which the running folder has checked out, and
    # fail after the merge (gh 2.89, 2026-10-18 check). The branch on GitHub is removed with one push below.
    p = _gh(wt, 'pr', 'merge', url or branch, '--merge')
    if p.returncode:
        state = _gh(wt, 'pr', 'view', url or branch, '--json', 'state', '-q', '.state')
        if state.stdout.strip() != 'MERGED':
            raise Stop('マージできませんでした（PR は残っています。もう一度は試しません）: ' + (p.stderr or p.stdout).strip()[-400:])
    steps.append('merged')
    gone = git(wt, 'push', '-q', 'origin', '--delete', branch, check=False)
    steps.append(f'deleted {branch} on GitHub' if gone.returncode == 0 else f'{branch} left on GitHub (delete it by hand)')
    changed = git(wt, 'diff', '--name-only', 'origin/main...HEAD').stdout.split()
    if follow:
        f = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'follow_github.py'), '--repo', str(LIVE)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
        said = (f.stdout.strip() or f.stderr.strip())
        if f.returncode:
            raise Stop('GitHub の main には入りましたが、動いているダン（' + str(LIVE) + '）にはまだ入っていません:\n'
                       + said[-1200:] + '\n直したら `python ' + (LIVE / 'scripts' / 'follow_github.py').as_posix() + '`。',
                       steps=steps)
        steps.append(f'follow_github: {said}')
    return steps, _restart_hint(changed)


def _gh(wt, *args):
    return subprocess.run([GH, *args], cwd=str(wt), capture_output=True, text=True, encoding='utf-8', errors='replace',
                          creationflags=NO_WINDOW)


def _restart_hint(changed):
    """What has to be restarted for the shipped files to run (restarting has its own rules: AGENTS.md)."""
    hints = []
    if any(p.startswith('frontend/') for p in changed):
        hints.append('画面: python scripts/frontend_prod.py restart')
    if any(p.startswith(('app/', 'main.py', 'requirements')) for p in changed):
        hints.append('本体: python scripts/restart_dan_core.py --when-idle --then "<入れ替え後に確かめること>"')
    return hints


# --- the command ----------------------------------------------------------------------------------------------------------------

def main(argv):
    sys.stdout.reconfigure(encoding='utf-8')
    at = argv[argv.index('--at') + 1] if '--at' in argv else None
    args = [a for i, a in enumerate(argv) if a != '--at' and (i == 0 or argv[i - 1] != '--at')]
    cmd = args[0] if args else 'help'
    try:
        if cmd == 'new' and len(args) > 1:
            start = args[args.index('--from') + 1] if '--from' in args else None
            path, branch, start = new(args[1], start)
            print(f'作業場所: {path}\n分岐: {branch}（{start} から）\n'
                  f'そこで直す → `python {LIVE.as_posix()}/scripts/work.py save` → test → try → ship')
        elif cmd == 'save':
            wt = here(at)
            branch_of(wt)
            only = args[args.index('--only') + 1:] if '--only' in args else None
            words = args[1:args.index('--only')] if '--only' in args else args[1:]
            left = changes(wt)[1]
            sha = save(wt, ' '.join(words) or None, only)
            print(f'保存しました: {sha}' if sha else '保存する変更はありません。')
            if left and not only:
                print('保存しなかった新しいファイル（リポジトリに無いフォルダの中の物）: ' + ', '.join(left[:10])
                      + '\n  入れるなら `work.py save --only <パス>`')
        elif cmd == 'test':
            wt = here(at)
            branch_of(wt)
            rest = args[args.index('--') + 1:] if '--' in args else []
            command = (rest[0] if len(rest) == 1 else shlex.join(rest)) if rest else None
            ok, tail = test(wt, command)
            print(tail)
            print('試験が通りました。ship できます。' if ok else '試験が通りませんでした。')
            return 0 if ok else 1
        elif cmd == 'venv':
            wt = here(at)
            path, made = venv(wt)
            print(f'{"作りました" if made else "もうあります"}: {path}\n入れる時は `{path}/bin/python -m pip install ...`'
                  '（work.py try と test はこの Python を使います）')
        elif cmd == 'try':
            wt = here(at)
            if args[1:2] == ['stop']:
                ended = try_stop(wt)
                print('止めました: ' + ', '.join(ended) if ended else 'この作業場所で try した物は動いていません。')
            else:
                started, state = try_up(wt)
                print(f"API: http://127.0.0.1:{TRY_PORTS['api']}  (app.sandbox, この作業場所のコード)\n"
                      f"画面: http://localhost:{TRY_PORTS['screens']}  (next dev、API は 8001 へ。チャットは本物の Core 9000 のまま)\n"
                      f"記録: {state / 'api.log'}, screens.log（立ち上がりに約80秒）\n終わったら `work.py try stop`")
        elif cmd == 'ship' and len(args) > 1:
            wt = here(at)
            body = args[args.index('--body') + 1] if '--body' in args else None
            try:
                steps, hints = ship(wt, args[1], body, follow='--no-follow' not in args)
            except Stop as e:
                if e.steps:
                    print('\n'.join(e.steps))
                raise
            print('\n'.join(steps))
            if hints:
                print('入れ替えが要るもの:\n  ' + '\n  '.join(hints))
        elif cmd == 'list':
            for name, day, ahead, behind, path, subject in listing():
                print(f'{name:45} {day}  +{ahead:<3} -{behind:<4} {path or "(作業場所なし)":50} {subject}')
        else:
            print(__doc__)
            return 0 if cmd == 'help' else 2
    except Stop as e:
        print(str(e))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
