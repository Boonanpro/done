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


# --- 2026-10-24: the light form. Ordinary writes are refused with a pointer to a worktree; Dan's own scripts run ------------

@pytest.mark.parametrize('command', [
    'python scripts/frontend_prod.py build',
    'python scripts/install_git_hooks.py',
    'python scripts/follow_github.py',
    'python scripts/generate_sitemap_registry.py',
    'cd frontend && node scripts/sync-artifact-sitemaps.mjs',
    'cd frontend && npm run build',
    'chmod +x .githooks/pre-commit',
])
def test_dans_own_scripts_are_not_refused(live, command):
    assert shell(command, live) is None, command


def test_the_hook_says_nothing_after_a_tool(live):
    """No second half any more: PostToolUse is not read (2026-10-24)."""
    env = {**__import__('os').environ, 'DAN_LIVE_TREE': str(live)}
    payload = {'hook_event_name': 'PostToolUse', 'tool_name': 'Bash', 'tool_input': {'command': './x'},
               'session_id': 's', 'tool_use_id': 't', 'cwd': str(live)}
    (live / 'app/api/chat_routes.py').write_text('changed by someone\n')
    out = subprocess.run([sys.executable, str(SCRIPTS / 'hook_live_tree_guard.py')], input=json.dumps(payload).encode(),
                         capture_output=True, env=env)
    assert out.stdout.strip() == b'' and (live / 'app/api/chat_routes.py').read_text() == 'changed by someone\n'
    assert git(live, 'branch', '--list', 'wip/*').stdout == ''


def test_a_codex_deletion_reaches_the_guard_through_the_bridge(live):
    """The bridge turns a deletion into a "Delete" call; the matchers that register the guard must name it
    (2026-10-23 check: the room settings in ship-checklist.md lacked it)."""
    spec2 = importlib.util.spec_from_file_location('codex_hook_bridge', SCRIPTS / 'codex_hook_bridge.py')
    bridge = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(bridge)
    patch = '*** Begin Patch\n*** Delete File: app/api/chat_routes.py\n*** End Patch'
    shaped = bridge._synthesize({'tool_name': 'apply_patch', 'tool_input': {'command': patch}, 'cwd': str(live)})
    assert [s['tool_name'] for s in shaped] == ['Delete']
    repo_settings = json.loads((SCRIPTS.parent / '.claude' / 'settings.json').read_text())
    matchers = [g['matcher'] for g in repo_settings['hooks']['PreToolUse']
                if any('hook_live_tree_guard' in h['command'] for h in g['hooks'])]
    assert matchers and all(bridge._matches(m, 'Delete') for m in matchers)
    checklist = SCRIPTS.parent / 'REPORT' / 'ship-checklist.md'
    if checklist.exists():
        import re as _re
        for m in _re.findall(r'"matcher":\s*"([^"]+)"', checklist.read_text()):
            assert bridge._matches(m, 'Delete'), m
    assert guard.check(shaped[0])
