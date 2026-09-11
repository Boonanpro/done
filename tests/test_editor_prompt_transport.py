import json
from app.agent import codex_runner as c


def test_editor_profile_keeps_tools_and_sends_current_instructions_once(tmp_path, monkeypatch):
    monkeypatch.setattr(c, '_CODEX_HOME', tmp_path)
    config=tmp_path/'mcp.json'
    config.write_text(json.dumps({'mcpServers': {'timeline': {'command':'python','args':['timeline.py']},'dan': {'command':'python','args':['dan.py']}}}))
    prompt='CURRENT_EDITOR_PURPOSE_AND_USER_PERMISSIONS'
    c.build_codex_profile('editor_test',str(config),prompt)
    profile=c.profile_path('editor_test').read_text(encoding='utf-8')
    turn=c.wrap_turn_content(prompt,'RAW_USER_REQUEST')
    assert prompt not in profile and turn.count(prompt)==1
    assert 'timeline.py' in profile and 'dan.py' in profile
    assert 'RAW_USER_REQUEST' in turn
    c.build_codex_profile('ordinary_chat',str(config),prompt)
    assert prompt in c.profile_path('ordinary_chat').read_text(encoding='utf-8')
