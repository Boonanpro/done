"""Dan's Claude tool host and hooks start by the interpreter's path, not by `python` on PATH.

2026-10-31〜11-06: Cores started from a Codex turn had no `python` on PATH, so dan-tools never connected in any
Claude room (no parallel work, browser or progress) and the hooks never ran."""
import json
import os
import sys


def test_mcp_config_uses_interpreter_path():
    from app.agent.cli_runner import _build_mcp_config
    cfg = json.loads(open(_build_mcp_config('test-room-python-path', 'u')).read())
    assert cfg['mcpServers']['dan-tools']['command'] == sys.executable


def test_hooks_use_interpreter_path():
    from app.services.work_locks import hook_settings
    for group in json.loads(hook_settings())['hooks']['PreToolUse']:
        for hook in group['hooks']:
            assert hook['command'].startswith(f'"{sys.executable}"'.replace('\\', '/'))


def test_core_env_puts_dan_python_first(monkeypatch):
    from app.core import generations
    monkeypatch.setenv('PATH', '/usr/bin:/bin')
    path = generations.core_env()['PATH'].split(os.pathsep)
    assert path[0] == os.path.dirname(sys.executable)
    assert '/usr/bin' in path
