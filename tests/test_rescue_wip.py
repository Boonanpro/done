"""Uncommitted work in the running folder moves to one branch per session, and nothing is lost (2026-10-18).

Each test builds a running folder with work left in it and the sessions' records (a Claude transcript, a Codex
session) of who wrote what, then plans and moves."""
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('rescue_wip', SCRIPTS / 'rescue_wip.py')
rescue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rescue)


def git(where, *args):
    return subprocess.run(['git', *args], cwd=str(where), capture_output=True, text=True, encoding='utf-8')


def write(where, name, text, age_minutes=120):
    p = Path(where) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode('utf-8'))
    t = time.time() - age_minutes * 60
    os.utime(p, (t, t))


@pytest.fixture
def world(tmp_path, monkeypatch):
    live = tmp_path / 'done'
    live.mkdir()
    git(live, 'init', '-q', '-b', 'main')
    git(live, 'config', 'user.email', 't@example.invalid'); git(live, 'config', 'user.name', 't')
    git(live, 'config', 'core.autocrlf', 'false')
    for name in ('app/a.py', 'app/b.py', 'app/c.py', 'web/page.tsx', 'machine.json', 'old.py'):
        write(live, name, 'committed\n')
    write(live, '.gitignore', '/.data/\n')
    git(live, 'add', '-A'); git(live, 'commit', '-q', '-m', 'first')
    git(live, 'branch', 'target')
    write(live, '.gitignore', '/.data/\nmachine.json\n')                     # the change that is about to ship
    git(live, 'add', '.gitignore'); git(live, 'commit', '-q', '-m', 'ignore');
    git(live, 'branch', '-f', 'target', 'HEAD'); git(live, 'reset', '-q', '--hard', 'HEAD~1')

    # work left in the folder
    write(live, 'app/a.py', 'committed\nwork of claude\n')
    write(live, 'app/new.py', 'new by claude\n')
    write(live, 'web/page.tsx', 'committed\nwork of codex\n')
    write(live, 'app/b.py', 'committed\nby a shell\n')
    (live / 'old.py').unlink()
    write(live, 'machine.json', '{"local": true}\n')
    write(live, 'app/c.py', 'committed\nstill being written\n', age_minutes=1)

    records = tmp_path / 'records'
    claude = records / 'claude' / 'proj'
    claude.mkdir(parents=True)
    lines = [
        {'type': 'user', 'sessionId': 'aaaa1111', 'cwd': str(live), 'timestamp': '2026-10-10T00:00:00Z',
         'message': {'content': '<runtime_system_context>x</runtime_system_context><latest_user_message>音声の途切れを直して</latest_user_message>'}},
        {'type': 'assistant', 'sessionId': 'aaaa1111', 'cwd': str(live), 'timestamp': '2026-10-10T00:01:00Z',
         'message': {'content': [{'type': 'tool_use', 'name': 'Edit', 'input': {'file_path': str(live / 'app' / 'a.py')}}]}},
        {'type': 'assistant', 'sessionId': 'aaaa1111', 'cwd': str(live), 'timestamp': '2026-10-10T00:02:00Z',
         'message': {'content': [{'type': 'tool_use', 'name': 'Write', 'input': {'file_path': 'app/new.py'}}]}},
        {'type': 'assistant', 'sessionId': 'aaaa1111', 'cwd': str(live), 'timestamp': '2026-10-10T00:03:00Z',
         'message': {'content': [{'type': 'tool_use', 'name': 'Read', 'input': {'file_path': str(live / 'app' / 'b.py')}}]}},
    ]
    (claude / 'aaaa1111.jsonl').write_text('\n'.join(json.dumps(x) for x in lines) + '\n', encoding='utf-8')
    codex = records / 'codex'
    codex.mkdir()
    patch = '*** Begin Patch\n*** Update File: web/page.tsx\n@@\n-x\n+y\n*** Delete File: old.py\n*** End Patch'
    lines = [
        {'type': 'session_meta', 'payload': {'id': 'bbbb2222', 'cwd': str(live)}},
        {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                                              'content': [{'type': 'input_text', 'text': '画面のちらつきを直して'}]}},
        {'type': 'response_item', 'timestamp': '2026-10-11T00:00:00Z',
         'payload': {'type': 'custom_tool_call', 'name': 'apply_patch', 'input': patch}},
    ]
    (codex / 'rollout-bbbb2222.jsonl').write_text('\n'.join(json.dumps(x) for x in lines) + '\n', encoding='utf-8')
    monkeypatch.setattr(rescue, 'TRANSCRIPTS', [records / 'claude', codex])
    return live


def snapshot(live):
    return {p.relative_to(live).as_posix(): p.read_bytes() for p in live.rglob('*') if p.is_file() and '.git' not in p.parts}


def test_the_plan_groups_by_session_and_changes_nothing(world):
    before = snapshot(world), git(world, 'status', '--porcelain').stdout
    p = rescue.plan(world, target='target')
    groups = {g['session'] or g['branch']: g for g in p['groups']}
    claude, codex = groups['aaaa1111'], groups['bbbb2222']
    assert sorted(f['path'] for f in claude['files']) == ['app/a.py', 'app/new.py']
    assert claude['label'] == '音声の途切れを直して' and claude['branch'].endswith('-aaaa1111')
    assert sorted(f['path'] for f in codex['files']) == ['old.py', 'web/page.tsx'] and codex['label'] == '画面のちらつきを直して'
    unknown = [g for g in p['groups'] if not g['session']]
    assert sorted(f['path'] for g in unknown for f in g['files']) == ['app/b.py', 'app/c.py']
    assert [g['busy'] for g in unknown if any(f['path'] == 'app/c.py' for f in g['files'])] == [True]
    assert p['local'] == ['machine.json']
    assert (snapshot(world), git(world, 'status', '--porcelain').stdout) == before


def test_apply_moves_each_group_to_its_branch_and_reads_it_back(world, capsys):
    before = snapshot(world)
    assert rescue.main(['--repo', str(world), '--target', 'target', '--apply']) == 0
    branches = git(world, 'branch', '--list', 'wip/*').stdout.split()
    claude = next(b for b in branches if b.endswith('aaaa1111'))
    codex = next(b for b in branches if b.endswith('bbbb2222'))
    assert git(world, 'show', f'{claude}:app/a.py').stdout == 'committed\nwork of claude\n'
    assert git(world, 'show', f'{claude}:app/new.py').stdout == 'new by claude\n'
    assert git(world, 'show', f'{claude}:web/page.tsx').stdout == 'committed\n'          # only its own files
    assert git(world, 'show', f'{codex}:web/page.tsx').stdout == 'committed\nwork of codex\n'
    assert git(world, 'cat-file', '-e', f'{codex}:old.py').returncode != 0                 # the deletion is kept too
    assert '音声の途切れを直して' in git(world, 'log', '-1', '--format=%B', claude).stdout
    # the folder is back to the committed files, except what is still being written and the local machine file
    status = git(world, 'status', '--porcelain').stdout.splitlines()
    assert sorted(status) == [' M app/c.py', ' M machine.json']
    assert (world / 'old.py').read_text() == 'committed\n' and not (world / 'app/new.py').exists()
    assert (world / 'machine.json').read_bytes() == before['machine.json']
    every = {}
    for b in branches:
        for path in ('app/a.py', 'app/new.py', 'app/b.py', 'web/page.tsx'):
            got = git(world, 'show', f'{b}:{path}').stdout
            if got and got != 'committed\n':
                every[path] = got.encode()
    for path, data in every.items():
        assert before[path] == data                                                       # every piece of work is on a branch
    assert set(every) == {'app/a.py', 'app/new.py', 'app/b.py', 'web/page.tsx'}
    assert 'skipped' in capsys.readouterr().out


def _move(world, group):
    branch, commit, saved = rescue.save(world, group)
    where = rescue.keep_dir(world)
    result = {rel: rescue.restore(world, rel, blob, where) for rel, blob in saved.items()}
    return branch, commit, result, where


def test_a_file_written_while_moving_stays_in_the_folder(world, monkeypatch):
    """Written after it was saved and before it was put back: the new text stays in the folder, untouched."""
    p = rescue.plan(world, target='target')
    group = next(g for g in p['groups'] if g['session'] == 'aaaa1111')
    branch, commit, saved = rescue.save(world, group)
    write(world, 'app/a.py', 'committed\nwork of claude\nand one more line\n', age_minutes=0)
    where = rescue.keep_dir(world)
    assert rescue.restore(world, 'app/a.py', saved['app/a.py'], where) == 'changed'
    assert rescue.restore(world, 'app/new.py', saved['app/new.py'], where) == 'restored'
    assert (world / 'app/a.py').read_text().endswith('and one more line\n')
    assert git(world, 'show', f'{branch}:app/a.py').stdout == 'committed\nwork of claude\n'
    assert (where / 'app/new.py').read_text() == 'new by claude\n'                       # the folder's copy is kept too


def test_a_write_in_the_instant_of_putting_back_is_not_lost(world, monkeypatch):
    """The check and the put-back are one move: a write that lands between them goes to a kept file, not to nowhere.
    (2026-10-18 check: a write between the last comparison and checkout-index was overwritten.)"""
    p = rescue.plan(world, target='target')
    group = next(g for g in p['groups'] if g['session'] == 'aaaa1111')
    branch, commit, saved = rescue.save(world, group)
    real = rescue._hash_path
    late = 'committed\nwork of claude\nwritten in the instant\n'

    def racing(repo, rel, path):
        if rel == 'app/a.py':                     # the writer still holds the file: its write lands in the moved copy
            Path(path).write_text(late)
        return real(repo, rel, path)
    monkeypatch.setattr(rescue, '_hash_path', racing)
    where = rescue.keep_dir(world)
    assert rescue.restore(world, 'app/a.py', saved['app/a.py'], where) == 'changed'
    assert (world / 'app/a.py').read_text() == late                                     # given back, nothing lost


def test_a_file_recreated_after_its_deletion_was_saved_stays(world):
    p = rescue.plan(world, target='target')
    group = next(g for g in p['groups'] if g['session'] == 'bbbb2222')
    branch, commit, saved = rescue.save(world, group)
    assert saved['old.py'] is None
    write(world, 'old.py', 'written again\n', age_minutes=0)
    assert rescue.restore(world, 'old.py', None, rescue.keep_dir(world)) == 'changed'
    assert (world / 'old.py').read_text() == 'written again\n'


def test_line_ending_only_files_are_checked_before_put_back(world):
    git(world, 'config', 'core.autocrlf', 'true')
    write(world, 'app/c.py', 'committed\r\n')
    p = rescue.plan(world, target='target')
    assert 'app/c.py' in p['eol_only']
    write(world, 'app/c.py', 'committed\r\nreal work after the plan\r\n')               # written after the plan
    rescue.apply(world, p, 30)
    assert (world / 'app/c.py').read_bytes() == b'committed\r\nreal work after the plan\r\n'
    write(world, 'app/c.py', 'committed\r\n')
    rescue.apply(world, rescue.plan(world, target='target'), 30)
    assert 'app/c.py' not in git(world, 'status', '--porcelain').stdout                   # still only line endings: back


def test_staged_work_is_kept_as_well_as_the_folders_version(world):
    """`git add` then more editing: both versions are on the branch (2026-10-18 check: the staged one was lost)."""
    write(world, 'app/a.py', 'committed\nstaged version\n')
    git(world, 'add', 'app/a.py')
    write(world, 'app/a.py', 'committed\nstaged version\nthen edited more\n')
    p = rescue.plan(world, target='target')
    group = next(g for g in p['groups'] if any(f['path'] == 'app/a.py' for f in g['files']))
    branch, commit, saved = rescue.save(world, group)
    assert git(world, 'show', f'{branch}:app/a.py').stdout.endswith('then edited more\n')
    assert git(world, 'show', f'{branch}~1:app/a.py').stdout == 'committed\nstaged version\n'
    assert git(world, 'show', f'{branch}~2:app/a.py').stdout == 'committed\n'
    rescue.restore(world, 'app/a.py', saved['app/a.py'], rescue.keep_dir(world))
    assert 'app/a.py' not in git(world, 'status', '--porcelain').stdout                  # index and file both back


def test_a_rename_and_a_staged_new_file_are_moved_whole(world):
    """`git mv` and `git add` of a new file (2026-10-18 check: both stopped halfway)."""
    git(world, 'mv', 'app/b.py', 'app/b2.py')
    write(world, 'app/staged_new.py', 'brand new\n')
    git(world, 'add', 'app/staged_new.py')
    assert rescue.main(['--repo', str(world), '--target', 'target', '--apply', '--quiet-minutes', '0']) == 0
    branches = git(world, 'branch', '--list', 'wip/*').stdout.split()
    files = {}
    for b in branches:
        for line in git(world, 'diff', '--name-status', '--no-renames', f'main...{b}').stdout.splitlines():
            code, path = line.split('\t')
            files.setdefault(path, set()).add(code)
    assert 'A' in files['app/b2.py'] and 'D' in files['app/b.py'] and 'A' in files['app/staged_new.py']
    status = git(world, 'status', '--porcelain').stdout.splitlines()
    assert status == [' M machine.json']
    assert (world / 'app/b.py').read_text() == 'committed\n' and not (world / 'app/b2.py').exists()


def test_a_run_cut_short_is_finished_by_running_again_without_copies(world, monkeypatch):
    """Everything is saved before anything is put back; a stop in between leaves all work on branches, and the next
    run only puts files back (2026-10-18 check: groups were saved and put back one after another)."""
    real = rescue.restore
    calls = []

    def stop_after_one(*a, **k):
        if calls:
            raise KeyboardInterrupt
        calls.append(a)
        return real(*a, **k)
    monkeypatch.setattr(rescue, 'restore', stop_after_one)
    with pytest.raises(KeyboardInterrupt):
        rescue.main(['--repo', str(world), '--target', 'target', '--apply', '--quiet-minutes', '0'])
    branches = git(world, 'branch', '--list', 'wip/*').stdout.split()
    on_branches = {path for b in branches for path in
                   git(world, 'diff', '--name-only', '--no-renames', f'main...{b}').stdout.split()}
    assert {'app/a.py', 'app/new.py', 'app/b.py', 'app/c.py', 'web/page.tsx', 'old.py'} <= on_branches
    monkeypatch.setattr(rescue, 'restore', real)
    assert rescue.main(['--repo', str(world), '--target', 'target', '--apply', '--quiet-minutes', '0']) == 0
    assert git(world, 'branch', '--list', 'wip/*').stdout.split() == branches              # no second copies
    assert git(world, 'status', '--porcelain').stdout.splitlines() == [' M machine.json']


def test_a_branch_name_already_taken_gets_a_new_one(world):
    p = rescue.plan(world, target='target')
    group = next(g for g in p['groups'] if g['session'] == 'aaaa1111')
    git(world, 'branch', group['branch'])
    branch, *_ = rescue.save(world, group)
    assert branch == group['branch'] + '-2'
    assert git(world, 'rev-parse', group['branch']).stdout == git(world, 'rev-parse', 'main').stdout


def test_files_in_a_folder_the_target_ignores_stay_as_local_files(world, tmp_path):
    """A folder pattern (/runtime/) in the target's .gitignore covers the files in it (git check-ignore --no-index
    sees it only when asked about the folder; 2026-10-23, 982 runtime files were listed as work)."""
    side = tmp_path / 'side'
    git(world, 'worktree', 'add', '-q', str(side), 'target')
    (side / '.gitignore').write_text((side / '.gitignore').read_text() + '/runtime/\n')
    git(side, 'commit', '-q', '-am', 'ignore runtime')
    write(world, 'runtime/log/a.jsonl', 'runtime\n')
    p = rescue.plan(world, target='target')
    assert 'runtime/log/a.jsonl' in p['local']
    assert all(f['path'] != 'runtime/log/a.jsonl' for g in p['groups'] for f in g['files'])


def test_a_link_standing_where_a_committed_folder_was_is_moved_first(world, tmp_path):
    """A folder git tracks replaced by a link to somewhere else: the link is saved and moved aside before the folder's
    files come back (2026-10-23: scripts/yoshikawa_proposal/remotion/public/frames in the running folder)."""
    import shutil
    shutil.rmtree(world / 'web')
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    (world / 'web').symlink_to(elsewhere)
    assert rescue.main(['--repo', str(world), '--target', 'target', '--apply', '--quiet-minutes', '0']) == 0
    assert (world / 'web').is_dir() and not (world / 'web').is_symlink()
    assert (world / 'web' / 'page.tsx').read_text() == 'committed\n'
    branches = git(world, 'branch', '--list', 'wip/*').stdout.split()
    links = [b for b in branches if git(world, 'ls-tree', b, '--', 'web').stdout.startswith('120000')]
    assert links                                                                        # the link itself is kept
    assert git(world, 'status', '--porcelain').stdout.splitlines() == [' M machine.json']
    assert sorted(git(world, 'ls-files', 'web').stdout.split()) == ['web/page.tsx']   # nothing made of the two names


def test_files_that_hold_the_targets_text_and_skipped_prefixes_stay(world, tmp_path):
    """A fix already on the target is left for follow_github; --skip leaves runtime data at an odd place alone
    (the lifelog folder named like a Windows share path, 2026-10-24)."""
    side = tmp_path / 'side2'
    git(world, 'worktree', 'add', '-q', str(side), 'target')
    (side / 'app' / 'a.py').write_text('committed\nwork of claude\n')
    git(side, 'commit', '-q', '-am', 'the fix lands on the target')
    write(world, '\\\\nas\\share\\lifelog/2026-10-24/a.ogg', 'audio')
    p = rescue.plan(world, 0, 'target', skip=['\\\\nas'])
    moved = {f['path'] for g in p['groups'] for f in g['files']}
    assert 'app/a.py' in p['same'] and 'app/a.py' not in moved
    assert any(x.startswith('\\\\nas') for x in p['skipped']) and not any(x.startswith('\\\\nas') for x in moved)
