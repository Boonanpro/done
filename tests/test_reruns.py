"""Runs that stop halfway and runs that happen at once (2026-10-23/24 checks): a follow cut short, a package install that
failed, a rescue run again after a staged version changed or after a hard stop, two package lists written at once, a
venv copy that installed into the shared one. And: nothing locks the running folder (the owner chose the light form on
2026-10-24), so Dan's own scripts write where they always did."""
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
rescue = load('rescue_wip')



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


def push(github, changes, deleted=()):
    for name, text in changes.items():
        write(github, name, text)
    for name in deleted:
        (github / name).unlink()
    git(github, 'add', '-A'); git(github, 'commit', '-q', '-m', 'pushed')


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


def test_a_stop_between_making_a_branch_and_noting_it_makes_no_second_copy(world, monkeypatch):
    """Killed right after the branch was made and before the journal line (2026-10-24, a hard kill in the copy of the
    running folder left wip/20261017-unknown and wip/20261017-unknown-2 with the same files)."""
    github, folder = world
    write(folder, 'app/core.py', 'work\n')
    real = rescue._write_journal
    monkeypatch.setattr(rescue, '_write_journal', lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        rescue.apply(folder, rescue.plan(folder, 0, 'origin/main'), 0)
    monkeypatch.setattr(rescue, '_write_journal', real)
    rescue.apply(folder, rescue.plan(folder, 0, 'origin/main'), 0)
    assert len(git(folder, 'branch', '--list', 'wip/*').stdout.split()) == 1
    assert (folder / 'app/core.py').read_text() == 'one\n'
