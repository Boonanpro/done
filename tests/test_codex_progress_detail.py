import pytest
import json
import shlex
import sys
from app.agent.activity_line import activity_phrase, own_activity
from app.agent.codex_runner import _item_to_events
from app.agent.command_activity import command_activity


def test_progress_server_and_hooks_use_dan_python_without_path_lookup(tmp_path, monkeypatch):
    from app.agent import codex_runner as runner
    from app.agent import backend_parity
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

    monkeypatch.setattr(runner, '_CODEX_HOME', tmp_path)
    monkeypatch.setattr(backend_parity, 'parity_static', lambda backend: '')
    monkeypatch.setenv('DAN_CODEX_HOOKS', '1')
    config = tmp_path / 'mcp.json'
    config.write_text(json.dumps({'mcpServers': {
        'dan-tools': {'command': 'python', 'args': ['-m', 'app.mcp.server']},
        'custom': {'command': '/custom/python', 'args': []},
        'node-tool': {'command': 'node', 'args': []},
    }}))
    runner.build_codex_profile('progress-regression', str(config), '')
    profile = tomllib.loads(runner.profile_path('progress-regression').read_text())
    assert profile['mcp_servers']['dan-tools']['command'] == sys.executable
    assert profile['mcp_servers']['custom']['command'] == '/custom/python'
    assert profile['mcp_servers']['node-tool']['command'] == 'node'
    for event in ('PreToolUse', 'PostToolUse', 'Stop'):
        command = profile['hooks'][event][0]['hooks'][0]['command']
        assert sys.executable in command or shlex.quote(sys.executable) in command


@pytest.mark.parametrize('command,expected',[
    ("/bin/zsh -lc 'head -n 2 README.md && sleep 12'", '「README.md」の内容を確認しています'),
    ('rg -n "pytest" app/agent/codex_runner.py','「codex_runner.py」の該当箇所を探しています'),
    ('python -m pytest tests/test_chat.py -q','「test_chat.py」のテストを実行しています'),
    ('npm run build','画面をビルドしています'),
    ('npx tsc --noEmit','コードの型を確認しています'),
    ('git diff -- app/main.py','変更した内容を確認しています'),
    ('cat /private/account/auth.json','設定ファイルの内容を確認しています'),
])
def test_actual_command_operation_becomes_readable_activity(command,expected):
    event=_item_to_events({'type':'command_execution','id':'a','command':command})[0]
    assert activity_phrase(event['name'],event['input'])==expected


def test_does_not_guess_operation_from_words_in_a_script():
    assert command_activity('echo "npm run build"')==''
    assert command_activity('python -c "print(\'pytest\')"')==''
    assert command_activity('an-unknown-program --token SECRET')==''


def test_file_changes_identify_target_without_full_path():
    event=_item_to_events({'type':'file_change','id':'e','changes':[{'kind':'update','path':'/private/src/sidebar.tsx'}]})[0]
    assert activity_phrase(event['name'],event['input'])=='「sidebar.tsx」を編集しています'


def test_codex_progress_json_arguments_and_description_survive():
    event=_item_to_events({'type':'mcp_tool_call','id':'p','server':'dan-tools','tool':'progress',
        'arguments':'{"doing":"部屋のモデル設定を確認しています"}'})[0]
    assert own_activity(event['name'],event['input'])=='部屋のモデル設定を確認しています'
    event=_item_to_events({'type':'command_execution','id':'c','command':'cat config.json','description':'送信先の設定を確認しています'})[0]
    assert own_activity(event['name'],event['input'])=='送信先の設定を確認しています'
