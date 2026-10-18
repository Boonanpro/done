"""One way to work on Dan: each piece of work in its own worktree and branch, one road to the running folder.

    python D:/done/scripts/work.py new <name> [--from <branch>]   a worktree D:\\dan-workspace\\<name> on branch dan/<name>
    python D:/done/scripts/work.py save [what]                     commit everything in this worktree (often: git keeps it)
    python D:/done/scripts/work.py try [stop]                      run this worktree: API on 8001, screens on 3002
    python D:/done/scripts/work.py ship "<title>" [--body TEXT] [--no-follow]   take in main, push, PR, merge, follow_github
    python D:/done/scripts/work.py list                            every branch of work, where it is, how far from main

Why (2026-10-17/18): sessions wrote unfinished work straight into the running folder (D:\\done). Shipping one change
ran into seven files of other sessions' half-done work, and a dashboard rebuild would have published all of it. Now
the running folder is written only by follow_github (scripts/hook_live_tree_guard.py refuses other writes), so no
piece of work can overwrite, publish or lose another's. Clashes with other work show up in `ship`, on your own branch,
where you settle them before anything reaches the running folder.

`save`, `try` and `ship` act on the worktree you are in (or --at <path>). GitHub is used at a human pace: `ship` asks
each thing once and stops at the first refusal; collect related work into one ship.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

LIVE = Path(os.environ.get('DAN_LIVE_TREE') or Path(__file__).resolve().parents[1])
WORKSPACE = Path(os.environ.get('DAN_WORKTREES') or 'D:/dan-workspace')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
GH = os.environ.get('DAN_GH') or 'gh'
TRY_PORTS = {'api': 8001, 'screens': 3002}


class Stop(Exception):
    """A step that cannot go on; the message says what to do."""


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
    _link_node_modules(path)
    return path, branch, start


def _link_node_modules(wt):
    """The worktree's frontend uses the running folder's installed packages (a junction: nothing is copied)."""
    src, dst = LIVE / 'frontend' / 'node_modules', wt / 'frontend' / 'node_modules'
    if not src.is_dir() or dst.exists() or not dst.parent.is_dir():
        return
    if os.name == 'nt':
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(dst), str(src)], capture_output=True, creationflags=NO_WINDOW)
    else:
        dst.symlink_to(src, target_is_directory=True)


def save(wt, what=None):
    git(wt, 'add', '-A')
    if not git(wt, 'diff', '--cached', '--quiet', check=False).returncode:
        return None
    git(wt, 'commit', '-q', '-m', f"wip: {what or datetime.now().strftime('%Y-%m-%d %H:%M')}")
    return git(wt, 'rev-parse', '--short', 'HEAD').stdout.strip()


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
    for what, port in TRY_PORTS.items():
        if _port_open(port):
            raise Stop(f'{port} 番はもう使われています（別の作業が試しているかもしれません）。'
                       f'自分が立てた物なら `work.py try stop`、違うなら終わるのを待ってください。')
    env = {**os.environ, **_env_file(LIVE / '.env'), 'PYTHONIOENCODING': 'utf-8'}
    log = open(state / 'api.log', 'w', encoding='utf-8')
    api = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.sandbox.main:app', '--host', '127.0.0.1',
                            '--port', str(TRY_PORTS['api'])], cwd=str(wt), env=env, stdout=log,
                           stderr=subprocess.STDOUT, creationflags=flags)
    started['api'] = api.pid
    fenv = {**os.environ, **_env_file(LIVE / 'frontend' / '.env.local'),
            'BACKEND_URL': f"http://127.0.0.1:{TRY_PORTS['api']}", 'NEXT_DIST_DIR': '.next-preview'}
    log = open(state / 'screens.log', 'w', encoding='utf-8')
    subprocess.run([sys.executable, str(wt / 'scripts' / 'wire_artifact_tailwind_sources.py')], stdout=log,
                   stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    # webpack: Turbopack refuses node_modules that is a junction to another folder
    nxt = wt / 'frontend' / 'node_modules' / '.bin' / ('next.cmd' if os.name == 'nt' else 'next')
    web = subprocess.Popen([str(nxt), 'dev', '--webpack', '--port', str(TRY_PORTS['screens'])],
                           cwd=str(wt / 'frontend'), env=fenv, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
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
    """Take in main, push, PR, merge, then bring the running folder up to main. Each outside request once."""
    branch = branch_of(wt)
    if git(wt, 'status', '--porcelain').stdout.strip():
        raise Stop('保存していない変更があります。`work.py save` してから ship してください。')
    git(wt, 'fetch', '--quiet', 'origin', 'main')
    merged = git(wt, 'merge', '--no-edit', '-q', 'origin/main', check=False)
    if merged.returncode:
        clashes = git(wt, 'diff', '--name-only', '--diff-filter=U').stdout.split()
        raise Stop('最新の main とぶつかりました。ここ（自分の分岐）で直してください: ' + ', '.join(clashes) +
                   '\n直したら `work.py save "main を取り込み"` → 試す → もう一度 `work.py ship`。'
                   '\nやめるなら `git merge --abort`（この作業場所の中だけが元に戻る）。')
    if int(git(wt, 'rev-list', '--count', 'origin/main..HEAD').stdout.strip() or 0) == 0:
        raise Stop('main に入っていない変更がありません。')
    steps = []
    p = git(wt, 'push', '-q', '-u', 'origin', branch, check=False)
    if p.returncode:
        raise Stop('push できませんでした（もう一度は試しません）: ' + p.stderr.strip()[-400:])
    steps.append(f'pushed {branch}')
    if body is None:
        body = git(wt, 'log', '--format=- %s', 'origin/main..HEAD').stdout.strip()
    body += '\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)'
    p = subprocess.run([GH, 'pr', 'create', '--base', 'main', '--head', branch, '--title', title, '--body', body],
                       cwd=str(wt), capture_output=True, text=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
    if p.returncode:
        raise Stop('PR を作れませんでした（もう一度は試しません）: ' + (p.stderr or p.stdout).strip()[-400:])
    url = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ''
    steps.append(f'PR {url}')
    p = subprocess.run([GH, 'pr', 'merge', url or branch, '--merge', '--delete-branch'], cwd=str(wt), capture_output=True,
                       text=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
    if p.returncode:
        raise Stop('マージできませんでした（PR は残っています。もう一度は試しません）: ' + (p.stderr or p.stdout).strip()[-400:])
    steps.append('merged')
    changed = git(wt, 'diff', '--name-only', 'origin/main...HEAD').stdout.split()
    if follow:
        f = subprocess.run([sys.executable, str(LIVE / 'scripts' / 'follow_github.py'), '--repo', str(LIVE)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
        steps.append(f'follow_github: {f.stdout.strip() or f.stderr.strip()}')
    return steps, _restart_hint(changed)


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
                  f'そこで直す → `python {LIVE.as_posix()}/scripts/work.py save` → try → ship')
        elif cmd == 'save':
            wt = here(at)
            branch_of(wt)
            sha = save(wt, ' '.join(args[1:]) or None)
            print(f'保存しました: {sha}' if sha else '保存する変更はありません。')
        elif cmd == 'try':
            wt = here(at)
            if args[1:2] == ['stop']:
                ended = try_stop(wt)
                print('止めました: ' + ', '.join(ended) if ended else 'このworktreeで try した物は動いていません。')
            else:
                started, state = try_up(wt)
                print(f"API: http://127.0.0.1:{TRY_PORTS['api']}  (app.sandbox, この作業場所のコード)\n"
                      f"画面: http://localhost:{TRY_PORTS['screens']}  (next dev、API は 8001 へ。チャットは本物の Core 9000 のまま)\n"
                      f"記録: {state}\\api.log, screens.log（立ち上がりに約80秒）\n終わったら `work.py try stop`")
        elif cmd == 'ship' and len(args) > 1:
            wt = here(at)
            body = args[args.index('--body') + 1] if '--body' in args else None
            steps, hints = ship(wt, args[1], body, follow='--no-follow' not in args)
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
