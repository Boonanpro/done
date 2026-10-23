"""The running folder's code cannot be written (2026-10-24): macOS's user-immutable flag on every tracked file and on
the folders that hold only code. Only the updaters (follow_github, rescue_wip) open what they change and lock again.
Also the re-runs the 2026-10-23 check found unsafe: a follow cut short, a package install that failed, a rescue run again
after a staged version changed, two package lists written at once, a venv copy that installed into the shared one."""
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


follow_github = load('follow_github')
live_lock = load('live_lock')
rescue = load('rescue_wip')

mac_only = pytest.mark.skipif(not live_lock.SUPPORTED, reason='chflags is macOS only')


def git(where, *args):
    return subprocess.run(['git', *args], cwd=str(where), capture_output=True, text=True, encoding='utf-8')


def write(where, name, text):
    p = Path(where) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


@pytest.fixture
def world(tmp_path):
    """(github, folder): a running folder cloned from a small GitHub, with code, an artifact and runtime data."""
    github, folder = tmp_path / 'github', tmp_path / 'folder'
    git(tmp_path, 'init', '-q', '-b', 'main', 'github')
    git(github, 'config', 'user.email', 't@e'); git(github, 'config', 'user.name', 't')
    write(github, '.gitignore', '/.data/\n/frontend/src/app/artifacts/*/\n*.log\n')
    for name in ('app/core.py', 'app/api/routes.py', 'frontend/src/app/page.tsx', 'frontend/package.json',
                 'frontend/src/app/artifacts/_seo/seo.tsx'):
        write(github, name, 'one\n')
    git(github, 'add', '-A'); git(github, 'add', '-f', 'frontend/src/app/artifacts/_seo/seo.tsx')
    git(github, 'commit', '-q', '-m', 'first')
    git(tmp_path, 'clone', '-q', 'github', 'folder')
    git(folder, 'config', 'user.email', 't@e'); git(folder, 'config', 'user.name', 't')
    write(folder, '.data/state.json', '{}')
    write(folder, 'core.log', 'started\n')
    yield github, folder
    live_lock.unlock(folder)                              # let pytest remove the folder


def push(github, changes, deleted=()):
    for name, text in changes.items():
        write(github, name, text)
    for name in deleted:
        (github / name).unlink()
    git(github, 'add', '-A'); git(github, 'commit', '-q', '-m', 'pushed')


def attempts(folder):
    """Every way a session might write the code; each returns True when it changed something."""
    code = folder / 'app' / 'core.py'

    def py_write():
        code.write_text('changed\n')

    def replace():
        tmp = folder / 'app' / 'core.py.tmp'
        tmp.write_text('changed\n')
        os.replace(tmp, code)

    def delete():
        code.unlink()

    def rename():
        os.rename(code, folder / 'app' / 'core2.py')

    def new_file():
        (folder / 'app' / 'api' / 'new_routes.py').write_text('x\n')

    def chmod():
        os.chmod(code, 0o777)

    def shell():
        r = subprocess.run(f'echo x >> "{code}"', shell=True, capture_output=True)
        if r.returncode:
            raise PermissionError(r.stderr)

    def sed():
        r = subprocess.run(['sed', '-i', '', 's/one/two/', str(code)], capture_output=True)
        if r.returncode:
            raise PermissionError(r.stderr)

    def git_checkout():
        r = git(folder, 'checkout', 'HEAD~0', '--', 'app/core.py')
        if r.returncode:
            raise PermissionError(r.stderr)
        code.write_text('changed\n')
    return {'write': py_write, 'replace': replace, 'delete': delete, 'rename': rename, 'new file': new_file,
            'chmod': chmod, 'shell >>': shell, 'sed -i': sed, 'git checkout + write': git_checkout}


@mac_only
def test_locked_code_cannot_be_written_by_any_means(world):
    github, folder = world
    nf, nd, bad = live_lock.lock(folder)
    assert not bad and nf == 6 and live_lock.active(folder)
    for what, act in attempts(folder).items():
        with pytest.raises((PermissionError, OSError)):
            act()
    assert (folder / 'app' / 'core.py').read_text() == 'one\n'
    assert not (folder / 'app' / 'api' / 'new_routes.py').exists()          # a folder of code only: nothing added
    changed = [l for l in git(folder, 'status', '--porcelain').stdout.splitlines() if not l.startswith('??')]
    assert changed == []                                                  # no code changed, moved or removed
    # app/ stays open for the runtime (uploads, logs); a new file can appear there, never a change to code
    assert [l for l in git(folder, 'status', '--porcelain').stdout.splitlines()] in ([], ['?? app/core.py.tmp'])


@mac_only
def test_runtime_writes_stay_possible(world):
    github, folder = world
    live_lock.lock(folder)
    write(folder, '.data/state.json', '{"a": 1}')                         # runtime data
    (folder / 'core.log').write_text('more\n')                            # logs at the top
    (folder / 'core.log').rename(folder / 'core.1.log')                   # log rotation
    write(folder, 'frontend/src/app/artifacts/shop/page.tsx', 'x\n')       # a new artifact
    write(folder, 'frontend/.next-prod-1/build.txt', 'x\n')               # a build next to the code
    assert (folder / 'frontend/src/app/artifacts/shop/page.tsx').exists()


@mac_only
def test_follow_github_opens_only_what_changes_and_locks_again(world):
    github, folder = world
    live_lock.lock(folder)
    push(github, {'app/core.py': 'two\n', 'app/api/added.py': 'new\n'}, deleted=['frontend/src/app/page.tsx'])
    ok, what = follow_github.follow(folder)
    assert ok, what
    assert (folder / 'app/core.py').read_text() == 'two\n' and (folder / 'app/api/added.py').exists()
    assert not (folder / 'frontend/src/app/page.tsx').exists()
    with pytest.raises(PermissionError):
        (folder / 'app/api/added.py').write_text('changed\n')            # the new file is locked too
    assert 'not locked now: 0' in live_lock.status(folder)


@mac_only
def test_rescue_puts_back_through_the_lock(world):
    github, folder = world
    write(folder, 'app/core.py', 'left here before the lock\n')
    live_lock.lock(folder)                                               # a changed file is locked as it is
    p = rescue.plan(folder, quiet_minutes=0, target='origin/main')
    rescue.apply(folder, p, 0)
    branch = git(folder, 'branch', '--list', 'wip/*').stdout.split()[0]
    assert git(folder, 'show', f'{branch}:app/core.py').stdout == 'left here before the lock\n'
    assert (folder / 'app/core.py').read_text() == 'one\n'
    assert 'not locked now: 0' in live_lock.status(folder)


@mac_only
def test_unlock_takes_every_flag_off(world):
    github, folder = world
    live_lock.lock(folder)
    assert live_lock.unlock(folder) > 0 and not live_lock.active(folder)
    (folder / 'app' / 'core.py').write_text('writable again\n')


# --- re-runs (2026-10-23 check, finding 5) ---------------------------------------------------------------------------------

def test_a_follow_cut_short_is_finished_by_the_next_run(world, monkeypatch):
    """Stopped after git moved and before the machine's files came back: the next run puts them back, even though the
    folder is already on main, and says so."""
    github, folder = world
    write(github, 'machine.json', 'old\n'); git(github, 'add', '-A'); git(github, 'commit', '-q', '-m', 'm')
    assert git(folder, 'pull', '-q').returncode == 0
    write(folder, 'machine.json', 'written by a machine\n')
    write(github, '.gitignore', (github / '.gitignore').read_text() + 'machine.json\n')
    git(github, 'rm', '-q', '--cached', 'machine.json'); git(github, 'add', '-A'); git(github, 'commit', '-q', '-m', 'untrack')
    real = follow_github._git

    def crash(repo, *a, **k):
        p = real(repo, *a, **k)
        if a[:1] == ('merge',):
            raise RuntimeError('power cut')
        return p
    monkeypatch.setattr(follow_github, '_git', crash)
    ok, what = follow_github.follow(folder)
    assert not ok
    monkeypatch.setattr(follow_github, '_git', real)
    ok, what = follow_github.follow(folder)
    assert ok, what
    assert (folder / 'machine.json').read_text() == 'written by a machine\n' and 'earlier run' in what
    assert not list((folder / '.git' / 'dan' / 'follow_github').glob('kept-*'))


def test_a_failed_package_install_is_retried_until_it_works(world, monkeypatch):
    github, folder = world
    push(github, {'frontend/package.json': '{"dependencies": {"x": "1"}}\n'})
    answers = iter([(False, 'network down'), (True, '0 artifact packages kept')])
    calls = []
    monkeypatch.setattr(follow_github, '_install_frontend', lambda repo: calls.append(1) or next(answers))
    ok, what = follow_github.follow(folder)
    assert not ok and 'could not be installed' in what
    ok, what = follow_github.follow(folder)                              # already on main, but packages are owed
    assert ok and 'installed' in what and len(calls) == 2
    ok, what = follow_github.follow(folder)
    assert ok and len(calls) == 2                                        # nothing owed any more


# --- rescue run again after a staged version changed (finding 4) ---------------------------------------------------------

def test_a_staged_version_changed_after_a_stop_is_saved_on_the_run_again(world, monkeypatch):
    github, folder = world
    write(folder, 'app/core.py', 'staged A\n'); git(folder, 'add', 'app/core.py')
    write(folder, 'app/core.py', 'folder version\n')
    monkeypatch.setattr(rescue, 'restore', lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        rescue.apply(folder, rescue.plan(folder, 0, 'origin/main'), 0)
    monkeypatch.undo()
    write(folder, 'app/core.py', 'staged B\n'); git(folder, 'add', 'app/core.py')     # only the staged version changes
    write(folder, 'app/core.py', 'folder version\n')
    rescue.apply(folder, rescue.plan(folder, 0, 'origin/main'), 0)
    found = set()
    for b in git(folder, 'branch', '--list', 'wip/*').stdout.split():
        for c in git(folder, 'rev-list', b, '^origin/main').stdout.split():
            found.add(git(folder, 'show', f'{c}:app/core.py').stdout)
    assert {'staged A\n', 'staged B\n', 'folder version\n'} <= found
    assert (folder / 'app/core.py').read_text() == 'one\n'


# --- two package lists written at once (finding 6) -----------------------------------------------------------------------

def test_two_artifacts_adding_a_package_at_once_keep_both(tmp_path, monkeypatch):
    npm = load('hook_autoinstall_npm')
    front = tmp_path / 'frontend'
    front.mkdir()

    def slow_npm(where, args):
        time.sleep(0.3)                                                  # both would read the old list meanwhile
        for name in args[2:]:
            (where / 'node_modules' / name).mkdir(parents=True, exist_ok=True)
            (where / 'node_modules' / name / 'package.json').write_text('{}')
        return True, ''
    monkeypatch.setattr(npm, '_npm', slow_npm)
    results = []
    ts = [threading.Thread(target=lambda n=n: results.append(npm.install_live(front, [n]))) for n in ('date-fns', 'recharts')]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert all(ok for ok, _ in results)
    assert json.loads((front / '.artifact-packages.json').read_text()) == ['date-fns', 'recharts']


# --- a worktree's own Python (finding 3) -----------------------------------------------------------------------------------

def test_a_venv_copy_points_its_scripts_at_itself(tmp_path, monkeypatch):
    work = load('work')
    src = tmp_path / 'shared-venv'
    (src / 'bin').mkdir(parents=True)
    (src / 'pyvenv.cfg').write_text('home = /usr/bin\n')
    (src / 'bin' / 'pip').write_text(f'#!{src}/bin/python\nimport pip\n')
    (src / 'bin' / 'activate').write_text(f'VIRTUAL_ENV="{src}"\n')
    (src / 'bin' / 'python').symlink_to('/usr/bin/python3')
    (src / 'bin' / 'python3').symlink_to(src / 'bin' / 'python')
    monkeypatch.setenv('DAN_VENV', str(src))
    wt = tmp_path / 'wt'
    wt.mkdir()
    dst, made = work.venv(wt)
    assert made
    assert (dst / 'bin' / 'pip').read_text().startswith(f'#!{dst}/bin/python')
    assert str(src) not in (dst / 'bin' / 'activate').read_text()
    assert os.readlink(dst / 'bin' / 'python3') == str(dst / 'bin' / 'python')
    assert (src / 'bin' / 'pip').read_text().startswith(f'#!{src}/bin/python')           # the shared one untouched
