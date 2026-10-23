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
        # gh 2.89: after merging on GitHub it switches this checkout to main, which another worktree (the running
        # folder) has checked out, and fails
        r = subprocess.run(['git', 'checkout', 'main'], capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stderr)
            sys.exit(1)
elif args[:2] == ['pr', 'view']:
    print('MERGED')
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


def passed_tests(wt, command='python -c "print(1)"'):
    ok, tail = work.test(wt, command)
    assert ok, tail


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
    passed_tests(path)
    steps, hints = work.ship(path, 'Feature A')
    assert steps[0] == 'pushed dan/feature-a' and steps[2] == 'merged' and 'now on GitHub main' in steps[-1]
    assert (live / 'app.py').read_text() == 'one\ntwo\nthree\nfeature a\n'
    assert git(live, 'status', '--porcelain').stdout == ''
    assert hints == []


def test_two_pieces_of_work_on_one_file_meet_on_the_second_branch_not_in_the_running_folder(world, tmp_path):
    github, live, spaces = world
    a, _, _ = work.new('a')
    b, _, _ = work.new('b')
    for wt in (a, b):
        git(wt, 'config', 'user.email', 't@example.invalid'); git(wt, 'config', 'user.name', 't')
    (a / 'app.py').write_text('one\nTWO by a\nthree\n'); work.save(a); passed_tests(a)
    (b / 'app.py').write_text('one\nTWO by b\nthree\n'); work.save(b); passed_tests(b)
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
    (a / 'mine.py').write_text('mine\n'); work.save(a); passed_tests(a)
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
    (a / 'app.py').write_text('changed\n')
    with pytest.raises(work.Stop) as stop:
        work.ship(a, 'A')
    assert 'save' in str(stop.value)
    git(a, 'config', 'user.email', 't@example.invalid'); git(a, 'config', 'user.name', 't')
    git(a, 'checkout', '-q', '--', 'app.py')
    with pytest.raises(work.Stop) as stop:
        work.ship(a, 'A')
    assert 'work.py test' in str(stop.value)                               # never tested
    passed_tests(a)
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



# --- 2026-10-23: what the 2026-10-18 check found ---------------------------------------------------------------------------

def test_a_worktrees_packages_are_its_own(world):
    """npm install in a worktree must not reach the running folder (2026-10-18 check: node_modules was a link to it)."""
    github, live, spaces = world
    nm = live / 'frontend' / 'node_modules' / 'react'
    nm.mkdir(parents=True)
    (nm / 'package.json').write_text('{"version": "19"}')
    (live / 'frontend' / 'package.json').write_text('{}')
    git(live, 'add', 'frontend/package.json'); git(live, 'commit', '-q', '-m', 'frontend'); git(live, 'push', '-q')
    path, _, _ = work.new('pk')
    mine = path / 'frontend' / 'node_modules'
    assert mine.is_dir() and not mine.is_symlink() and (mine / 'react' / 'package.json').read_text() == '{"version": "19"}'
    (mine / 'react' / 'package.json').write_text('{"version": "20"}')                # an install in the worktree
    (mine / 'left-pad').mkdir()
    assert (nm / 'package.json').read_text() == '{"version": "19"}' and not (live / 'frontend/node_modules/left-pad').exists()


def test_ship_merges_without_switching_to_main(world):
    """gh pr merge --delete-branch fails in a worktree when main is checked out in the running folder (2026-10-18)."""
    github, live, spaces = world
    a, _, _ = work.new('a')
    git(a, 'config', 'user.email', 't@example.invalid'); git(a, 'config', 'user.name', 't')
    (a / 'mine.py').write_text('mine\n'); work.save(a); passed_tests(a)
    steps, _ = work.ship(a, 'A')
    assert 'merged' in steps and (live / 'mine.py').exists()
    assert 'dan/a' not in git(live, 'ls-remote', '--heads', 'origin').stdout                 # removed on GitHub


def test_main_that_breaks_the_tests_stops_ship_before_anything_leaves(world, tmp_path):
    """After taking in main the tests run again; a failure stops ship before push (2026-10-18 check: it shipped an
    untested combination)."""
    github, live, spaces = world
    a, _, _ = work.new('a')
    git(a, 'config', 'user.email', 't@example.invalid'); git(a, 'config', 'user.name', 't')
    (a / 'mine.py').write_text('from theirs import VALUE\nassert VALUE == 1\n'); work.save(a)
    (a / 'theirs.py').write_text('VALUE = 1\n'); work.save(a)
    passed_tests(a, 'python mine.py')
    git(a, 'rm', '-q', 'theirs.py'); git(a, 'commit', '-q', '-m', 'drop')        # theirs.py comes from main below
    passed_tests(a, 'python -c "print(1)"')
    work.test(a, 'python mine.py')                                             # fails now: the record says so
    other_push(github, tmp_path, 'theirs.py', 'VALUE = 2\n')
    pushed_before = git(live, 'ls-remote', '--heads', 'origin').stdout
    with pytest.raises(work.Stop) as stop:
        work.ship(a, 'A')
    assert '試験が通りませんでした' in str(stop.value)
    assert git(live, 'ls-remote', '--heads', 'origin').stdout == pushed_before          # nothing pushed


def test_main_is_tested_again_when_it_brought_something(world, tmp_path):
    github, live, spaces = world
    a, _, _ = work.new('a')
    git(a, 'config', 'user.email', 't@example.invalid'); git(a, 'config', 'user.name', 't')
    (a / 'mine.py').write_text('mine\n'); work.save(a); passed_tests(a)
    other_push(github, tmp_path, 'theirs.py', 'theirs\n')
    steps, _ = work.ship(a, 'A')
    assert steps[0].startswith('tested with main')


def test_a_follow_that_fails_makes_ship_fail_and_says_where_it_stopped(world, monkeypatch):
    github, live, spaces = world
    a, _, _ = work.new('a')
    git(a, 'config', 'user.email', 't@example.invalid'); git(a, 'config', 'user.name', 't')
    (a / 'app.py').write_text('one\ntwo\nthree\nfour\n'); work.save(a); passed_tests(a)
    (live / 'app.py').write_text('left here by hand\n')                              # follow_github will stop
    with pytest.raises(work.Stop) as stop:
        work.ship(a, 'A')
    assert 'GitHub の main には入りました' in str(stop.value) and 'app.py' in str(stop.value)
    assert 'merged' in stop.value.steps
    assert work.main(['ship', 'A', '--at', str(a)]) == 1                             # the command says it failed


def test_save_takes_work_and_leaves_notes_out(world):
    """save chooses: tracked changes and new files in the repository's folders; not a REPORT/ or another folder the
    repository does not have (2026-10-18 check: it used git add -A)."""
    github, live, spaces = world
    a, _, _ = work.new('a')
    git(a, 'config', 'user.email', 't@example.invalid'); git(a, 'config', 'user.name', 't')
    (a / 'app.py').write_text('changed\n')
    (a / 'scripts' / 'new_tool.py').write_text('x\n')
    (a / 'REPORT').mkdir(); (a / 'REPORT' / 'README.md').write_text('notes\n')
    (a / 'tmp-notes').mkdir(); (a / 'tmp-notes' / 'a.txt').write_text('scratch\n')
    work.save(a)
    committed = git(a, 'show', '--name-only', '--format=', 'HEAD').stdout.split()
    assert sorted(committed) == ['app.py', 'scripts/new_tool.py']
    assert work.changes(a) == ([], ['REPORT/README.md', 'tmp-notes/a.txt'])
    work.save(a, only=['REPORT/README.md'])
    assert 'REPORT/README.md' in git(a, 'show', '--name-only', '--format=', 'HEAD').stdout
