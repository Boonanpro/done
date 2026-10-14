"""The folder Dan runs from follows GitHub through git itself (2026-10-14).

Before: the folder held everyone's uncommitted work, a plain `git pull` stopped on the first such file, so nobody pulled
and each worker kept the folder in step with GitHub by hand. Nothing noticed a fix that was on GitHub and not in the
folder; committing that file from the folder would have taken the fix out of GitHub again.

Each test builds a small "GitHub" and a folder cloned from it, changes both the way workers do, and follows."""
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
    write(folder, 'mine.py', THREE + 'my work\n')                          # someone's uncommitted work
    ok, what = follow_github.follow(folder)
    assert ok, what
    assert read(folder, 'fixed.py') == 'one\ntwo FIXED\nthree\n' and read(folder, 'new.py') == 'new\n'
    assert not (folder / 'gone.py').exists()
    assert read(folder, 'mine.py') == THREE + 'my work\n'
    assert git(folder, 'rev-parse', 'HEAD').stdout.strip() == top
    assert git(folder, 'status', '--porcelain').stdout == ' M mine.py\n'     # git now shows the uncommitted work and nothing more


def test_what_a_worker_already_put_in_the_folder_by_hand_is_recognised(world):
    """The usual flow: edit in the folder so it runs, commit from another place, push. The folder already holds it."""
    github, folder = world
    change = {'fixed.py': 'one\ntwo FIXED\nthree\n', 'new.py': 'new\n', 'app/[room]/page.tsx': 'ONE\ntwo\nthree\n'}
    for name, text in change.items():
        write(folder, name, text)
    (folder / 'gone.py').unlink()
    top = pushed(github, change, deleted=['gone.py'])
    before = state(folder)[2]
    assert git(folder, 'fetch', '-q').returncode == 0
    assert git(folder, 'merge', '--ff-only', 'origin/main').returncode != 0   # why nobody could pull
    ok, what = follow_github.follow(folder)
    assert ok, what
    assert state(folder) == (top, '', before)                               # no file written, nothing left to show


def test_uncommitted_work_on_top_of_githubs_change_is_kept_and_shown_alone(world):
    github, folder = world
    write(folder, 'shared.py', 'ONE by a\ntwo\nthree\nwork of b\n')         # a's change and b's unfinished work, one file
    pushed(github, {'shared.py': 'ONE by a\ntwo\nthree\n'})                # a commits only a's part
    ok, what = follow_github.follow(folder)
    assert ok, what
    assert read(folder, 'shared.py') == 'ONE by a\ntwo\nthree\nwork of b\n'
    assert git(folder, 'diff').stdout.count('\n+work of b') == 1 and 'ONE by a' not in [
        l[1:] for l in git(folder, 'diff').stdout.splitlines() if l.startswith(('+', '-')) and not l.startswith(('+++', '---'))]


@pytest.mark.parametrize('here, why', [
    ('one\ntwo\nthree\nwork of b\n', "lacks GitHub's change"),              # would merge cleanly: still a person's call
    ('one\ntwo MINE\nthree\n', "lacks GitHub's change"),                    # the same line changed both ways
])
def test_a_file_that_lacks_githubs_change_and_has_work_in_it_stops_everything(world, here, why):
    github, folder = world
    write(folder, 'shared.py', here)
    write(folder, 'mine.py', THREE + 'my work\n')
    pushed(github, {'shared.py': 'one\ntwo FIXED\nthree\n', 'fixed.py': 'one\ntwo FIXED\nthree\n'})
    before = state(folder)
    ok, what = follow_github.follow(folder)
    assert not ok and 'shared.py' in what and why in what and 'nothing was changed' in what
    fetched = state(folder)
    assert fetched == before                                                # not even the other, harmless file moved


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
    assert not ok and case in what and state(folder) == before


def test_windows_line_endings_in_the_folder_are_not_a_difference(world):
    github, folder = world
    git(folder, 'config', 'core.autocrlf', 'true')
    write(folder, 'fixed.py', 'one\r\ntwo FIXED\r\nthree\r\n')              # same change, saved with CRLF
    write(folder, 'shared.py', 'ONE\r\ntwo\r\nthree\r\nwork\r\n')
    top = pushed(github, {'fixed.py': 'one\ntwo FIXED\nthree\n', 'shared.py': 'ONE\ntwo\nthree\n'})
    ok, what = follow_github.follow(folder)
    assert ok, what
    assert git(folder, 'rev-parse', 'HEAD').stdout.strip() == top
    assert git(folder, 'status', '--porcelain').stdout == ' M shared.py\n'
    assert read(folder, 'shared.py') == 'ONE\r\ntwo\r\nthree\r\nwork\r\n'


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
    assert ok and '1 brought in from GitHub: fixed.py' in what and state(folder) == before


def test_github_out_of_reach_is_said_and_asked_only_once(world, monkeypatch):
    github, folder = world
    git(folder, 'remote', 'set-url', 'origin', str(folder / 'nowhere'))
    asked = []
    real = follow_github._git
    monkeypatch.setattr(follow_github, '_git', lambda repo, *a, **k: (asked.append(a) if a[0] == 'fetch' else None) or real(repo, *a, **k))
    ok, what = follow_github.follow(folder)
    assert not ok and 'could not be reached' in what and len(asked) == 1
