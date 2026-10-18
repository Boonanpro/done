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
    env = dict(**__import__('os').environ, DAN_LIVE_TREE=str(live))
    payload = {'tool_name': 'Write', 'tool_input': {'file_path': str(live / 'app/api/chat_routes.py')}, 'cwd': str(live)}
    out = subprocess.run([sys.executable, str(SCRIPTS / 'hook_live_tree_guard.py')], input=json.dumps(payload).encode(),
                         capture_output=True, env=env).stdout.decode('ascii')
    hso = json.loads(out)['hookSpecificOutput']
    assert hso['permissionDecision'] == 'deny' and 'work.py' in hso['permissionDecisionReason']
    payload['tool_input']['file_path'] = str(live / '.data/x.json')
    out = subprocess.run([sys.executable, str(SCRIPTS / 'hook_live_tree_guard.py')], input=json.dumps(payload).encode(),
                         capture_output=True, env=env).stdout
    assert out.strip() == b''
