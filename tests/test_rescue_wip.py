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


def test_a_file_written_while_moving_stays_in_the_folder(world, monkeypatch):
    p = rescue.plan(world, target='target')
    group = next(g for g in p['groups'] if g['session'] == 'aaaa1111')
    real = rescue._hash

    def late(repo, rel):
        if rel == 'app/a.py':
            write(world, 'app/a.py', 'committed\nwork of claude\nand one more line\n', age_minutes=0)
        return real(repo, rel)
    monkeypatch.setattr(rescue, '_hash', late)
    branch, commit, moved, kept = rescue.move(world, group)
    assert kept == ['app/a.py'] and moved == ['app/new.py']
    assert (world / 'app/a.py').read_text().endswith('and one more line\n')
    assert git(world, 'show', f'{branch}:app/a.py').stdout == 'committed\nwork of claude\n'


def test_a_branch_name_already_taken_gets_a_new_one(world):
    p = rescue.plan(world, target='target')
    group = next(g for g in p['groups'] if g['session'] == 'aaaa1111')
    git(world, 'branch', group['branch'])
    branch, *_ = rescue.move(world, group)
    assert branch == group['branch'] + '-2'
    assert git(world, 'rev-parse', group['branch']).stdout == git(world, 'rev-parse', 'main').stdout
