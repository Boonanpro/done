"""Dan's whole tool set outside the chat CLI (2026-09-24): the catalog, the help, and the two meta tools on both paths."""
import json

import pytest

from app.services import dan_tools


def test_catalog_lists_every_tool_not_given_as_a_function_and_the_skills():
    tools = [{'name': 'browser', 'description': 'ブラウザを操作する。\n二行目だけの文', 'input_schema': {'type': 'object'}},
             {'name': 'compose_message', 'description': '送信案を作る。', 'input_schema': {'type': 'object'}}]
    text = dan_tools.catalog(tools, native=['browser'])
    lines = text.splitlines()
    assert '- compose_message(): 送信案を作る。' in lines and not any(l.startswith('- browser(') for l in lines) and '二行目だけの文' not in text
    assert 'check_skill' in text   # the skills line


def test_help_returns_the_full_definition_or_says_it_does_not_exist():
    tools = [{'name': 'watch', 'description': '見張る。\n全文', 'input_schema': {'type': 'object', 'properties': {'kind': {}}}}]
    assert json.loads(dan_tools.help_text(tools, 'watch'))['parameters']['properties'] == {'kind': {}}
    assert 'error' in json.loads(dan_tools.help_text(tools, 'nothing'))


def test_the_real_definitions_include_what_chat_dan_has():
    names = {t['name'] for t in dan_tools.definitions()}
    assert {'compose_message', 'watch', 'check_skill', 'bash', 'read_file', 'browser', 'desktop'} <= names


def test_voice_backend_gets_the_catalog_and_the_meta_functions():
    from app.services import voice_responses
    config = voice_responses.delegation()['responses']
    names = [t.get('name') for t in config['tools']]
    assert 'dan_tool' in names and 'dan_tool_help' in names
    assert '- compose_message(' in config['instructions'] and '通話を始めた時の日時' in config['instructions']


@pytest.mark.asyncio
async def test_voice_dan_tool_runs_in_the_owners_tool_host(monkeypatch):
    from app.services import voice_responses, voice_tools
    seen = {}
    class FakeHost:
        async def ask(self, op, **fields): seen.update(op=op, **fields); return 'done'
    monkeypatch.setattr(voice_tools, 'host', lambda user, room: seen.update(user=user, room=room) or FakeHost())
    out = await voice_responses.run_function('dan_tool', {'name': 'watch', 'arguments': {'kind': 'x'}}, 'u', 'r', [])
    assert out == {'result': 'done'} and seen == {'user': 'u', 'room': 'r', 'op': 'call', 'name': 'watch', 'arguments': {'kind': 'x'}}
    help = await voice_responses.run_function('dan_tool_help', {'name': 'compose_message'}, 'u', 'r', [])
    assert help['help']['name'] == 'compose_message'


def test_catalog_shows_argument_names_with_required_marked():
    tools = [{'name': 'watch', 'description': '見張る。', 'input_schema': {'type': 'object', 'properties': {'action': {}, 'kind': {}}, 'required': ['action']}}]
    assert '- watch(action*, kind): 見張る。' in dan_tools.catalog(tools).splitlines()


@pytest.mark.asyncio
async def test_web_search_is_a_function_run_in_its_own_call_with_the_date(monkeypatch):
    """The hosted search tool's definition is 4,436 tokens: sent only when searching, and the search is told today's date."""
    from app.services import voice_responses
    config = voice_responses.delegation()['responses']
    assert {'type': 'web_search'} not in config['tools'] and 'web_search' in [t.get('name') for t in config['tools']]
    sent = {}
    class Response:
        status_code = 200
        def json(self): return {'output': [{'type': 'message', 'content': [{'text': '晴れ、最高31度。出どころ: 気象庁'}]}]}
    class Client:
        def __init__(self, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json, headers): sent.update(json); return Response()
    import httpx
    monkeypatch.setattr(httpx, 'AsyncClient', Client)
    out = await voice_responses.run_function('web_search', {'query': '大阪の今日の天気'}, 'u', 'r', [])
    assert out['found'].startswith('晴れ') and sent['tools'] == [{'type': 'web_search'}] and '年' in sent['instructions']
