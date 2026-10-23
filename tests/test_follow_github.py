"""The folder Dan runs from follows GitHub through git's own fast-forward (2026-10-14, simplified 2026-10-18).

Nobody writes the folder's tracked files any more (scripts/hook_live_tree_guard.py); work lives on branches. What is
left uncommitted here only matters when GitHub changes the same file: then git refuses and nothing changes.

Each test builds a small "GitHub" and a folder cloned from it, changes both, and follows."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('follow_github', Path(__file__).resolve().parents[1] / 'scripts' / 'follow_github.py')
follow_github = importlib.util.module_from_spec(spec)
spec.loader.exec_module(follow_github)

THREE = 'one\ntwo\nthree\n'


def git(where, *args):
    return subprocess.run(['git', *args], cwd=str(where), capture_output=True, text=True, encoding='utf-8')


def write(where, name, text):
    path = Path(where) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode('utf-8'))


def read(where, name):
    return (Path(where) / name).read_bytes().decode('utf-8')


@pytest.fixture
def world(tmp_path):
    """(github, folder): the folder is a clone, both on the same first commit."""
    github, folder = tmp_path / 'github', tmp_path / 'folder'
    git(tmp_path, 'init', '-q', '-b', 'main', 'github')
    for repo in (github,):
        git(repo, 'config', 'user.email', 't@example.invalid'); git(repo, 'config', 'user.name', 't')
        git(repo, 'config', 'core.autocrlf', 'false')
    for name in ('fixed.py', 'mine.py', 'shared.py', 'gone.py', 'app/[room]/page.tsx'):
        write(github, name, THREE)
    git(github, 'add', '-A'); git(github, 'commit', '-q', '-m', 'first')
    git(tmp_path, 'clone', '-q', '-c', 'core.autocrlf=false', 'github', 'folder')   # as stored; one test turns CRLF on itself
    git(folder, 'config', 'user.email', 't@example.invalid'); git(folder, 'config', 'user.name', 't')
    git(folder, 'config', 'core.autocrlf', 'false')
    return github, folder


def pushed(github, changes, deleted=()):
    """A commit lands on GitHub (from some other place than the folder)."""
    for name, text in changes.items():
        write(github, name, text)
    for name in deleted:
        (github / name).unlink()
    git(github, 'add', '-A'); git(github, 'commit', '-q', '-m', 'pushed')
    return git(github, 'rev-parse', 'HEAD').stdout.strip()


def state(folder):
    return (git(folder, 'rev-parse', 'HEAD').stdout.strip(), git(folder, 'status', '--porcelain').stdout,
            {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob('*') if p.is_file() and '.git' not in p.parts})


def test_a_fix_that_is_only_on_github_arrives_and_uncommitted_work_stays(world):
    github, folder = world
    top = pushed(github, {'fixed.py': 'one\ntwo FIXED\nthree\n', 'new.py': 'new\n'}, deleted=['gone.py'])
    write(folder, 'mine.py', THREE + 'my work\n')                          # a file left uncommitted here
    ok, what = follow_github.follow(folder)
    assert ok, what
    assert read(folder, 'fixed.py') == 'one\ntwo FIXED\nthree\n' and read(folder, 'new.py') == 'new\n'
    assert not (folder / 'gone.py').exists()
    assert read(folder, 'mine.py') == THREE + 'my work\n'
    assert git(folder, 'rev-parse', 'HEAD').stdout.strip() == top
    assert git(folder, 'status', '--porcelain').stdout == ' M mine.py\n'
    assert 'Uncommitted here (1)' in what and 'mine.py' in what and 'rescue_wip' in what


@pytest.mark.parametrize('here', [
    'one\ntwo FIXED\nthree\n',                 # the same change copied in by hand
    'one\ntwo FIXED\nthree\nwork of b\n',      # GitHub's change with unfinished work on top
    'one\ntwo\nthree\nwork of b\n',            # unfinished work that lacks GitHub's change
    'one\ntwo MINE\nthree\n',                  # the same line changed both ways
])
def test_a_file_changed_here_and_on_github_stops_everything(world, here):
    github, folder = world
    write(folder, 'shared.py', here)
    write(folder, 'mine.py', THREE + 'my work\n')
    pushed(github, {'shared.py': 'one\ntwo FIXED\nthree\n', 'fixed.py': 'one\ntwo FIXED\nthree\n'})
    before = state(folder)
    ok, what = follow_github.follow(folder)
    assert not ok and 'shared.py' in what and 'nothing was changed' in what and 'rescue_wip' in what
    assert state(folder) == before                                          # not even the other, harmless file moved
    ok, dry = follow_github.follow(folder, fetch=False, dry=True)
    assert not ok and 'shared.py' in dry


def test_a_file_new_on_github_that_sits_here_with_other_content_stops(world):
    github, folder = world
    write(folder, 'new.py', 'an older copy\n')
    pushed(github, {'new.py': 'new\n'})
    before = state(folder)
    ok, what = follow_github.follow(folder)
    assert not ok and 'new.py' in what and state(folder) == before


@pytest.mark.parametrize('case', ['deleted here, changed on GitHub', 'changed here, deleted on GitHub'])
def test_a_delete_on_one_side_and_a_change_on_the_other_stops(world, case):
    github, folder = world
    if case.startswith('deleted here'):
        (folder / 'fixed.py').unlink()
        pushed(github, {'fixed.py': 'one\ntwo FIXED\nthree\n'})
    else:
        write(folder, 'fixed.py', THREE + 'my work\n')
        pushed(github, {}, deleted=['fixed.py'])
    before = state(folder)
    ok, what = follow_github.follow(folder)
    assert not ok and 'fixed.py' in what and state(folder) == before


def test_a_file_github_stops_tracking_and_ignores_stays_here(world):
    """A file a machine writes (settings.local.json, a generated list) leaves git without leaving the folder."""
    github, folder = world
    write(folder, 'mine.py', THREE + 'written by a machine\n')             # changed here
    write(github, '.gitignore', 'mine.py\ngone.py\n')
    git(github, 'rm', '-q', '--cached', 'mine.py', 'gone.py')
    git(github, 'add', '.gitignore'); git(github, 'commit', '-q', '-m', 'stop tracking machine files')
    ok, what = follow_github.follow(folder)
    assert ok, what
    assert read(folder, 'mine.py') == THREE + 'written by a machine\n' and read(folder, 'gone.py') == THREE
    assert git(folder, 'status', '--porcelain').stdout == ''
    assert 'kept as local files' in what


def test_a_file_github_deletes_and_does_not_ignore_goes(world):
    github, folder = world
    pushed(github, {}, deleted=['gone.py'])
    ok, what = follow_github.follow(folder)
    assert ok and not (folder / 'gone.py').exists()


def test_windows_line_endings_in_the_folder_are_not_a_difference(world):
    github, folder = world
    git(folder, 'config', 'core.autocrlf', 'true')
    write(folder, 'fixed.py', 'one\r\ntwo\r\nthree\r\n')                    # unchanged, saved with CRLF
    write(folder, 'shared.py', 'one\r\ntwo\r\nthree\r\nwork\r\n')
    top = pushed(github, {'fixed.py': 'one\ntwo FIXED\nthree\n'})
    ok, what = follow_github.follow(folder)
    assert ok, what
    assert git(folder, 'rev-parse', 'HEAD').stdout.strip() == top
    assert git(folder, 'status', '--porcelain').stdout == ' M shared.py\n'
    assert read(folder, 'shared.py') == 'one\r\ntwo\r\nthree\r\nwork\r\n'
    assert 'FIXED' in read(folder, 'fixed.py')


def test_nothing_to_do_and_things_it_will_not_touch(world):
    github, folder = world
    assert follow_github.follow(folder) == (True, follow_github.follow(folder)[1]) and 'already on GitHub' in follow_github.follow(folder)[1]
    write(folder, 'local.py', 'x\n'); git(folder, 'add', 'local.py'); git(folder, 'commit', '-q', '-m', 'never pushed')
    pushed(github, {'fixed.py': 'one\ntwo FIXED\nthree\n'})
    ok, what = follow_github.follow(folder)
    assert not ok and 'never pushed' in what
    git(folder, 'checkout', '-q', '-b', 'side')
    ok, what = follow_github.follow(folder)
    assert not ok and "'side'" in what


def test_looking_first_changes_nothing(world):
    github, folder = world
    pushed(github, {'fixed.py': 'one\ntwo FIXED\nthree\n'})
    git(folder, 'fetch', '-q')
    before = state(folder)
    ok, what = follow_github.follow(folder, dry=True)
    assert ok and 'would follow' in what and 'fixed.py' in what and state(folder) == before


def test_github_out_of_reach_is_said_and_asked_only_once(world, monkeypatch):
    github, folder = world
    git(folder, 'remote', 'set-url', 'origin', str(folder / 'nowhere'))
    asked = []
    real = follow_github._git
    monkeypatch.setattr(follow_github, '_git', lambda repo, *a, **k: (asked.append(a) if a[0] == 'fetch' else None) or real(repo, *a, **k))
    ok, what = follow_github.follow(folder)
    assert not ok and 'could not be reached' in what and len(asked) == 1


def test_files_kept_as_local_are_on_disk_while_git_moves(world, monkeypatch):
    """A stop right after git's move does not lose a machine's file (2026-10-18 check: it was kept only in memory)."""
    github, folder = world
    write(folder, 'mine.py', THREE + 'written by a machine\n')
    write(github, '.gitignore', 'mine.py\n')
    git(github, 'rm', '-q', '--cached', 'mine.py')
    git(github, 'add', '.gitignore'); git(github, 'commit', '-q', '-m', 'stop tracking')
    real = follow_github._git

    def crash_after_merge(repo, *a, **k):
        p = real(repo, *a, **k)
        if a[:1] == ('merge',):
            raise RuntimeError('power cut')
        return p
    monkeypatch.setattr(follow_github, '_git', crash_after_merge)
    ok, what = follow_github.follow(folder)
    assert not ok and 'power cut' in what
    copies = list((folder / '.git' / 'dan' / 'follow_github').glob('kept-*/mine.py'))
    assert copies and copies[0].read_text() == THREE + 'written by a machine\n'


def test_a_local_ignored_file_github_starts_tracking_is_set_aside_not_overwritten(world):
    """Git overwrites an ignored file without a word; the local copy is kept and named (2026-10-18 check)."""
    github, folder = world
    write(folder, '.git/info/exclude', 'local.cfg\n')
    write(folder, 'local.cfg', 'my local settings\n')
    pushed(github, {'local.cfg': 'settings from github\n'})
    ok, what = follow_github.follow(folder)
    assert ok, what
    assert read(folder, 'local.cfg') == 'settings from github\n'
    aside = list((folder / '.git' / 'dan' / 'follow_github').glob('replaced-*/local.cfg'))
    assert aside and aside[0].read_text() == 'my local settings\n'
    assert 'local.cfg' in what and 'replaced' in what


def test_a_rename_left_here_names_both_names(world):
    github, folder = world
    git(folder, 'mv', 'gone.py', 'renamed.py')
    names = [p for _, p in follow_github.status(folder)]
    assert 'gone.py' in names and 'renamed.py' in names
