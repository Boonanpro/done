"""The running folder refuses writes to what git tracks; artifacts, runtime files and worktrees pass (2026-10-18).

Each test builds a small running folder: a git repository with tracked code, an ignored artifacts folder, an ignored
data folder and a worktree kept inside it, and asks the hook about one tool call."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('hook_live_tree_guard', SCRIPTS / 'hook_live_tree_guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def git(where, *args):
    return subprocess.run(['git', *args], cwd=str(where), capture_output=True, text=True, encoding='utf-8')


@pytest.fixture
def live(tmp_path, monkeypatch):
    root = tmp_path / 'done'
    root.mkdir()
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'config', 'user.email', 't@example.invalid'); git(root, 'config', 'user.name', 't')
    (root / '.gitignore').write_text('/frontend/src/app/artifacts/*/\n/.data/\n**/node_modules/\n/_codex_worktrees/\n*.log\n')
    for name in ('app/api/chat_routes.py', 'frontend/src/lib/api-client.ts', 'frontend/package.json',
                 'frontend/src/app/artifacts/_seo/analytics.tsx', '.claude/skills/x/SKILL.md'):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('x\n')
    git(root, 'add', '-A'); git(root, 'add', '-f', 'frontend/src/app/artifacts/_seo/analytics.tsx')
    git(root, 'commit', '-q', '-m', 'first')
    (root / 'frontend/src/app/artifacts/shop').mkdir(parents=True)
    (root / '.data').mkdir()
    git(root, 'worktree', 'add', '-q', '-b', 'wt', str(root / '_codex_worktrees' / 'wt'))
    monkeypatch.setattr(guard, 'LIVE', root)
    return root


def edit(path, tool='Edit', cwd=None):
    return guard.check({'tool_name': tool, 'tool_input': {'file_path': str(path)}, 'cwd': cwd or 'C:/'})


def shell(command, cwd, tool='Bash'):
    return guard.check({'tool_name': tool, 'tool_input': {'command': command}, 'cwd': str(cwd)})


def test_tracked_and_new_source_files_are_refused(live):
    assert 'work.py new' in edit(live / 'app/api/chat_routes.py')
    assert edit(live / 'app/api/new_routes.py', tool='Write')          # new file git would track
    assert edit(live / '.claude/skills/x/SKILL.md', tool='MultiEdit')
    assert edit(live / 'frontend/src/app/artifacts/_seo/analytics.tsx')  # tracked though under the artifacts pattern
    assert edit('app/api/chat_routes.py', cwd=str(live))                   # relative to the session's folder
    assert edit(str(live / 'app' / 'api' / 'chat_routes.py').upper())     # Windows paths ignore case


def test_artifacts_runtime_files_and_worktrees_pass(live):
    assert edit(live / 'frontend/src/app/artifacts/shop/page.tsx', tool='Write') is None
    assert edit(live / '.data/state.json', tool='Write') is None
    assert edit(live / 'frontend/node_modules/x/index.js') is None
    assert edit(live / 'server.log') is None
    assert edit(live / '_codex_worktrees/wt/app/api/chat_routes.py') is None
    assert edit(live.parent / 'elsewhere' / 'app.py', tool='Write') is None


def test_codex_apply_patch_delete_is_refused(live):
    assert guard.check({'tool_name': 'Delete', 'tool_input': {'file_path': 'app/api/chat_routes.py'}, 'cwd': str(live)})


def test_codex_raw_apply_patch(live):
    def patch(*heads):
        return {'tool_name': 'apply_patch', 'cwd': str(live),
                'tool_input': {'command': '*** Begin Patch\n' + ''.join(f'*** {h}\n+x\n' for h in heads) + '*** End Patch'}}
    assert guard.check(patch('Update File: app/api/chat_routes.py'))
    assert guard.check(patch('Add File: .data/x.json', 'Delete File: frontend/src/lib/api-client.ts'))
    assert guard.check(patch('Add File: .data/x.json', 'Add File: frontend/src/app/artifacts/shop/page.tsx')) is None


@pytest.mark.parametrize('command', [
    'echo hi > app/api/chat_routes.py',
    'cat >> app/api/new.py <<EOF\nline > other\nEOF',
    'sed -i "s/a/b/" app/api/chat_routes.py',
    'cp /tmp/x.py app/api/chat_routes.py',
    'mv app/api/chat_routes.py app/api/old.py',
    'rm app/api/chat_routes.py',
    'printf x | tee app/api/chat_routes.py',
    'git add -A',
    'git commit -m wip',
    'git stash',
    'git restore app/api/chat_routes.py',
    'cd frontend && npm install left-pad',
])
def test_shell_writes_in_the_folder_are_refused(live, command):
    assert shell(command, live), command


def test_shell_from_elsewhere_names_the_folder(live, tmp_path):
    assert shell(f'cd {live.as_posix()} && echo x > app/api/chat_routes.py', tmp_path)
    assert shell(f'git -C {live.as_posix()} checkout -- .', tmp_path)
    assert shell(f'echo x > "{live / "app/api/chat_routes.py"}"', tmp_path)


@pytest.mark.parametrize('command', [
    'Set-Content -Path app/api/chat_routes.py -Value x',
    'Copy-Item C:/x.py app/api/chat_routes.py',
    '"x" | Out-File app/api/chat_routes.py',
    'Remove-Item app/api/chat_routes.py',
])
def test_powershell_writes_are_refused(live, command):
    assert shell(command, live, tool='PowerShell'), command


@pytest.mark.parametrize('command', [
    'git status && git diff && git log -3',
    'git worktree add D:/dan-workspace/x origin/main',
    'git fetch origin main',
    'python scripts/follow_github.py',
    'python -c "print(1 > 0)"',
    'echo hi > .data/x.json',
    'echo hi > frontend/src/app/artifacts/shop/page.tsx',
    'cmd 2>&1 | tail -5',
    'ls > /dev/null 2>&1',
    'npm install',
    'npm run build',
    'rm -rf frontend/node_modules/.cache',
    'grep -n "a > b" app/api/chat_routes.py',
    'cat app/api/chat_routes.py | head',
    'echo "s/a/b/" > .data/script.sed',
    'cd _codex_worktrees/wt && git add -A && git commit -m wip && echo x > app/api/chat_routes.py',
    'New-Item -ItemType Directory -Path app/api/newdir',
])
def test_reading_and_allowed_writes_pass(live, command):
    assert shell(command, live) is None, command


def test_hook_prints_a_codex_readable_denial(live, monkeypatch):
    env = {**__import__('os').environ, 'DAN_LIVE_TREE': str(live)}
    payload = {'tool_name': 'Write', 'tool_input': {'file_path': str(live / 'app/api/chat_routes.py')}, 'cwd': str(live)}
    out = subprocess.run([sys.executable, str(SCRIPTS / 'hook_live_tree_guard.py')], input=json.dumps(payload).encode(),
                         capture_output=True, env=env).stdout.decode('ascii')
    hso = json.loads(out)['hookSpecificOutput']
    assert hso['permissionDecision'] == 'deny' and 'work.py' in hso['permissionDecisionReason']
    payload['tool_input']['file_path'] = str(live / '.data/x.json')
    out = subprocess.run([sys.executable, str(SCRIPTS / 'hook_live_tree_guard.py')], input=json.dumps(payload).encode(),
                         capture_output=True, env=env).stdout
    assert out.strip() == b''


# --- 2026-10-23: the ways the 2026-10-18 check got past, and the Mac spellings --------------------------------------------

@pytest.mark.parametrize('command', [
    'python -c "open(\'app/api/chat_routes.py\', \'w\').write(1)"',
    'python3 -c "from pathlib import Path; Path(\'app/api/chat_routes.py\').write_text(\'x\')"',
    "node -e \"require('fs').writeFileSync('app/api/chat_routes.py', 'x')\"",
    'python - <<EOF\nopen("app/api/chat_routes.py", "w").write("x")\nEOF',
    'f=app/api/chat_routes.py; echo x > $f',
    'F=app/api/chat_routes.py && echo x > "${F}"',
    'export T=app/api; cp /etc/hosts $T/chat_routes.py',
    'cp /etc/hosts .',                                       # into the current folder, under its own name
    'cp /etc/hosts app/api/',
    'sh -c "echo x > app/api/chat_routes.py"',
    "bash -lc 'sed -i.bak s/x/y/ app/api/chat_routes.py'",
    'zsh -c "rm app/api/chat_routes.py"',
    'eval "echo x > app/api/chat_routes.py"',
    'bash <<EOF\necho x > app/api/chat_routes.py\nEOF',
    'ln -sf /etc/hosts app/api/chat_routes.py',
    'rsync -a /tmp/x/ app/api/chat_routes.py',
    'dd if=/dev/zero of=app/api/chat_routes.py count=1',
    'truncate -s 0 app/api/chat_routes.py',
    'perl -pi -e s/x/y/ app/api/chat_routes.py',
    'echo x >| app/api/chat_routes.py',
    'nohup sh -c "echo x > app/api/chat_routes.py" &',
    'rm -rf app/api',
    'echo $(echo x > app/api/chat_routes.py)',
    'cd app && cd api && echo x > chat_routes.py',
    'npm ci',
])
def test_the_ways_around_are_refused(live, command):
    assert shell(command, live), command


def test_aliases_of_the_folder_are_the_folder(live, tmp_path):
    link = tmp_path / 'alias'
    link.symlink_to(live)
    assert edit(link / 'app/api/chat_routes.py')                            # a symlink into the folder
    assert shell(f'echo x > {link}/app/api/chat_routes.py', tmp_path)
    real = Path(__import__('os').path.realpath(live))
    if str(real) != str(live):                                              # /var -> /private/var on a Mac
        assert edit(real / 'app/api/chat_routes.py')
    assert edit(str(live / 'App' / 'API' / 'Chat_Routes.py'))               # APFS ignores case


@pytest.mark.parametrize('command', [
    'git clean -nd',
    'git stash list',
    'git apply --check /tmp/x.patch',
    'cd frontend && npm install left-pad --dry-run',
    'python -c "import json; print(open(\'app/api/chat_routes.py\').read())"',
    'python -c "open(\'.data/x.json\', \'w\').write(1)"',
    "echo 'echo $HOME > app/api/chat_routes.py' > .data/note.txt",
    'cp app/api/chat_routes.py /tmp/copy.py',
])
def test_reading_and_dry_runs_pass(live, command):
    assert shell(command, live) is None, command


def test_pip_from_a_worktree_into_the_shared_python_is_refused(live):
    wt = live / '_codex_worktrees' / 'wt'
    assert 'work.py venv' in shell('pip install requests', wt)
    assert shell('python -m pip install -U google-genai', wt)
    assert shell('.venv/bin/python -m pip install requests', wt) is None
    assert shell('pip install requests', live.parent) is None                # not Dan work: not this guard's business


# --- the guarantee: whatever wrote it, a changed tracked file is moved out ---------------------------------------------------

def run_tool(live, payload, act):
    import rescue_wip  # noqa: F401
    guard.before(payload)
    act()
    return guard.after(payload)


def test_a_write_the_shell_reading_missed_is_saved_on_a_branch_and_put_back(live, monkeypatch):
    sys.path.insert(0, str(SCRIPTS))
    monkeypatch.setenv('DAN_LIVE_TREE', str(live))
    import follow_github
    monkeypatch.setattr(follow_github, 'ROOT', live)
    (live / 'app/api/other.py').write_text('someone\'s old work\n')            # already here before: left alone
    payload = {'tool_name': 'Bash', 'tool_input': {'command': './some_program'}, 'session_id': 'cafe1234-0000',
               'tool_use_id': 't1', 'cwd': str(live)}

    def program_writes():
        (live / 'app/api/chat_routes.py').write_text('written by a program\n')
        (live / 'app/api/brand_new.py').write_text('new\n')
    said = run_tool(live, payload, program_writes)
    assert said and 'wip/' in said and 'chat_routes.py' in said and 'brand_new.py' in said
    branch = next(b for b in git(live, 'branch', '--list', 'wip/*').stdout.split() if b.endswith('cafe1234'))
    assert git(live, 'show', f'{branch}:app/api/chat_routes.py').stdout == 'written by a program\n'
    assert git(live, 'show', f'{branch}:app/api/brand_new.py').stdout == 'new\n'
    assert (live / 'app/api/chat_routes.py').read_text() == 'x\n' and not (live / 'app/api/brand_new.py').exists()
    assert (live / 'app/api/other.py').read_text() == 'someone\'s old work\n'
    # a second slip in the same session goes on the same branch, after the first
    said = run_tool(live, dict(payload, tool_use_id='t2'), lambda: (live / 'frontend/package.json').write_text('{}\n'))
    assert said and branch in said
    assert git(live, 'show', f'{branch}:app/api/chat_routes.py').stdout == 'written by a program\n'
    assert git(live, 'show', f'{branch}:frontend/package.json').stdout == '{}\n'


def test_nothing_changed_nothing_said(live, monkeypatch):
    monkeypatch.setenv('DAN_LIVE_TREE', str(live))
    payload = {'tool_name': 'Bash', 'tool_input': {'command': 'ls'}, 'session_id': 's', 'tool_use_id': 't3'}
    assert run_tool(live, payload, lambda: (live / '.data' / 'x.json').write_text('{}')) is None
    assert git(live, 'branch', '--list', 'wip/*').stdout == ''


def test_the_hook_reports_after_the_tool_in_both_formats(live, monkeypatch):
    env = {**__import__('os').environ, 'DAN_LIVE_TREE': str(live)}
    payload = {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_input': {'command': './x'},
               'session_id': 'beef0000', 'tool_use_id': 't9', 'cwd': str(live)}
    run = lambda p: subprocess.run([sys.executable, str(SCRIPTS / 'hook_live_tree_guard.py')],
                                   input=json.dumps(p).encode(), capture_output=True, env=env)
    assert run(payload).stdout.strip() == b''
    (live / 'app/api/chat_routes.py').write_text('slipped\n')
    out = json.loads(run(dict(payload, hook_event_name='PostToolUse')).stdout)
    assert out['decision'] == 'block' and 'wip/' in out['reason']
    assert out['hookSpecificOutput']['additionalContext'] == out['reason']
    assert (live / 'app/api/chat_routes.py').read_text() == 'x\n'
