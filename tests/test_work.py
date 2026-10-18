"""One road for work: a worktree per piece of work, clashes settled on its own branch, the running folder only follows
(2026-10-18). Each test builds a small "GitHub" (a bare repository), a running folder cloned from it, and a fake `gh`."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('work', SCRIPTS / 'work.py')
work = importlib.util.module_from_spec(spec)
spec.loader.exec_module(work)

FAKE_GH = r'''
import subprocess, sys
args = sys.argv[1:]
if args[:2] == ['pr', 'create']:
    print('https://github.invalid/pr/1')
elif args[:2] == ['pr', 'merge']:
    subprocess.run(['git', 'push', '-q', 'origin', 'HEAD:main'], check=True)
    if '--delete-branch' in args:
        b = subprocess.run(['git', 'symbolic-ref', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
        subprocess.run(['git', 'push', '-q', 'origin', '--delete', b], check=True)
'''


def git(where, *args):
    return subprocess.run(['git', *args], cwd=str(where), capture_output=True, text=True, encoding='utf-8')


@pytest.fixture
def world(tmp_path, monkeypatch):
    seed, github, live, spaces = tmp_path / 'seed', tmp_path / 'github.git', tmp_path / 'done', tmp_path / 'spaces'
    git(tmp_path, 'init', '-q', '-b', 'main', 'seed')
    for repo in (seed,):
        git(repo, 'config', 'user.email', 't@example.invalid'); git(repo, 'config', 'user.name', 't')
    (seed / 'scripts').mkdir()
    (seed / 'scripts' / 'follow_github.py').write_bytes((SCRIPTS / 'follow_github.py').read_bytes())
    (seed / 'app.py').write_text('one\ntwo\nthree\n')
    git(seed, 'add', '-A'); git(seed, 'commit', '-q', '-m', 'first')
    git(tmp_path, 'clone', '-q', '--bare', 'seed', 'github.git')
    git(tmp_path, 'clone', '-q', '-c', 'core.autocrlf=false', 'github.git', 'done')
    for repo in (live,):
        git(repo, 'config', 'user.email', 't@example.invalid'); git(repo, 'config', 'user.name', 't')
        git(repo, 'config', 'core.autocrlf', 'false')
    spaces.mkdir()
    gh = tmp_path / 'gh.py'
    gh.write_text(FAKE_GH)
    gh_cmd = tmp_path / ('gh.bat' if sys.platform == 'win32' else 'gh.sh')
    gh_cmd.write_text(f'@"{sys.executable}" "{gh}" %*\n' if sys.platform == 'win32' else f'#!/bin/sh\n"{sys.executable}" "{gh}" "$@"\n')
    gh_cmd.chmod(0o755)
    monkeypatch.setattr(work, 'LIVE', live)
    monkeypatch.setattr(work, 'WORKSPACE', spaces)
    monkeypatch.setattr(work, 'GH', str(gh_cmd))
    return github, live, spaces


def other_push(github, tmp_path, name, text):
    """Someone else's work lands on GitHub main."""
    other = tmp_path / 'other'
    if not other.exists():
        git(tmp_path, 'clone', '-q', str(github), 'other')
        git(other, 'config', 'user.email', 'o@example.invalid'); git(other, 'config', 'user.name', 'o')
    git(other, 'pull', '-q')
    (other / name).write_text(text)
    git(other, 'add', '-A'); git(other, 'commit', '-q', '-m', 'other'); git(other, 'push', '-q', 'origin', 'main')


def test_new_save_and_ship_reach_the_running_folder(world):
    github, live, spaces = world
    path, branch, _ = work.new('feature-a')
    assert path == spaces / 'feature-a' and branch == 'dan/feature-a'
    assert git(path, 'symbolic-ref', '--short', 'HEAD').stdout.strip() == 'dan/feature-a'
    (path / 'app.py').write_text('one\ntwo\nthree\nfeature a\n')
    git(path, 'config', 'user.email', 't@example.invalid'); git(path, 'config', 'user.name', 't')
    assert work.save(path, 'half done')
    assert work.save(path) is None                                         # nothing new to keep
    assert 'wip: half done' in git(path, 'log', '-1', '--format=%s').stdout
    steps, hints = work.ship(path, 'Feature A')
    assert steps[0] == 'pushed dan/feature-a' and steps[2] == 'merged' and 'now on GitHub main' in steps[3]
    assert (live / 'app.py').read_text() == 'one\ntwo\nthree\nfeature a\n'
    assert git(live, 'status', '--porcelain').stdout == ''
    assert hints == []


def test_two_pieces_of_work_on_one_file_meet_on_the_second_branch_not_in_the_running_folder(world, tmp_path):
    github, live, spaces = world
    a, _, _ = work.new('a')
    b, _, _ = work.new('b')
    for wt in (a, b):
        git(wt, 'config', 'user.email', 't@example.invalid'); git(wt, 'config', 'user.name', 't')
    (a / 'app.py').write_text('one\nTWO by a\nthree\n'); work.save(a)
    (b / 'app.py').write_text('one\nTWO by b\nthree\n'); work.save(b)
    work.ship(a, 'A')
    before = (live / 'app.py').read_text()
    with pytest.raises(work.Stop) as stop:
        work.ship(b, 'B')
    assert 'app.py' in str(stop.value) and 'ぶつかりました' in str(stop.value)
    assert (live / 'app.py').read_text() == before == 'one\nTWO by a\nthree\n'  # the running folder never saw b
    (b / 'app.py').write_text('one\nTWO by a and b\nthree\n')
    work.save(b, 'main を取り込み')
    work.ship(b, 'B')
    assert (live / 'app.py').read_text() == 'one\nTWO by a and b\nthree\n'


def test_other_work_on_main_is_taken_in_on_the_branch(world, tmp_path):
    github, live, spaces = world
    a, _, _ = work.new('a')
    git(a, 'config', 'user.email', 't@example.invalid'); git(a, 'config', 'user.name', 't')
    (a / 'mine.py').write_text('mine\n'); work.save(a)
    other_push(github, tmp_path, 'theirs.py', 'theirs\n')
    work.ship(a, 'A')
    assert (live / 'mine.py').exists() and (live / 'theirs.py').exists()


def test_refusals(world):
    github, live, spaces = world
    with pytest.raises(work.Stop):
        work.here(live)                                                     # never in the running folder
    a, _, _ = work.new('a')
    with pytest.raises(work.Stop):
        work.new('a')
    with pytest.raises(work.Stop):
        work.new('bad name')
    (a / 'loose.py').write_text('x\n')
    with pytest.raises(work.Stop) as stop:
        work.ship(a, 'A')
    assert 'save' in str(stop.value)
    git(a, 'config', 'user.email', 't@example.invalid'); git(a, 'config', 'user.name', 't')
    git(a, 'clean', '-fdq')
    with pytest.raises(work.Stop) as stop:
        work.ship(a, 'A')
    assert '変更がありません' in str(stop.value)


def test_continue_from_a_rescued_branch_and_list(world):
    github, live, spaces = world
    git(live, 'branch', 'wip/20261010-aaaa1111')
    path, branch, start = work.new('voice', 'wip/20261010-aaaa1111')
    assert start == 'wip/20261010-aaaa1111'
    names = [r[0] for r in work.listing()]
    assert 'dan/voice' in names and 'wip/20261010-aaaa1111' in names
    row = next(r for r in work.listing() if r[0] == 'dan/voice')
    assert Path(row[4]).resolve() == path.resolve()


def test_restart_hints():
    assert work._restart_hint(['frontend/src/x.tsx'])[0].startswith('画面')
    assert work._restart_hint(['app/core/main.py'])[0].startswith('本体')
    assert work._restart_hint(['scripts/x.py', 'docs/a.md']) == []
