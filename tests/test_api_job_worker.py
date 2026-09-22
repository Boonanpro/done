"""The API job worker: one Responses turn per model call, tools called in-process, steering fed as messages, result saved."""
import json
from types import SimpleNamespace as NS

import pytest

from app.services import api_job_worker as W
from app.services import command_job_state as state


@pytest.fixture
def job(tmp_path, monkeypatch):
    monkeypatch.setattr(state, 'ROOT', tmp_path)
    s = state.create('11111111-1111-1111-1111-111111111111', user_id='u', room_id='r', origin_room_id='o', origin_project_id='p',
                     task='smart-ex のトップを開いて題名を読んで', report_message_id='m', queue_owner='core', engine='api', instructions='作業の指示')
    state.change(s['id'], lambda st: st.update(state='running'))
    return s['id']


def response(*items):
    return NS(id='resp_1', output=list(items))


@pytest.mark.asyncio
async def test_tool_calls_run_here_and_the_final_words_are_the_result(job, monkeypatch):
    turns = [response(NS(type='function_call', call_id='c1', name='browser', arguments=json.dumps({'action': 'open_target', 'url': 'https://smart-ex.jp/'})),
                      NS(type='message', content=[NS(text='トップを開きます')])),
             response(NS(type='message', content=[NS(text='題名は「スマートEX」です。')]))]
    sent, called = [], []
    async def call_model(self, items, instructions, tools, previous): sent.append(items); return turns.pop(0)
    async def call_tool(name, args): called.append((name, args)); return [NS(type='text', text='URL: https://smart-ex.jp/ タイトル: スマートEX')]
    async def list_tools(): return [NS(name='browser', description='ブラウザ', inputSchema={'type': 'object', 'properties': {'action': {'type': 'string'}}})]
    monkeypatch.setattr(W.Worker, 'call_model', call_model)
    monkeypatch.setattr('app.mcp_server.call_tool', call_tool)
    monkeypatch.setattr('app.mcp_server.list_tools', list_tools)
    await W.Worker(job).run()
    s = state.read(job)
    assert called == [('browser', {'action': 'open_target', 'url': 'https://smart-ex.jp/'})]
    assert sent[1] == [{'type': 'function_call_output', 'call_id': 'c1', 'output': 'URL: https://smart-ex.jp/ タイトル: スマートEX'}]
    assert s['state'] == 'completed' and s['result'] == '題名は「スマートEX」です。'
    kinds = [e for e in s['events'] if e['kind'] != 'diagnostic']
    assert [e['kind'] for e in kinds][-2:] == ['progress', 'result'] and 'トップを開きます' in kinds[-2]['text']


@pytest.mark.asyncio
async def test_steering_arrives_as_a_message_and_is_marked_applied(job, monkeypatch):
    turns = [response(NS(type='function_call', call_id='c1', name='browser', arguments='{}')),
             response(NS(type='message', content=[NS(text='完了')]))]
    sent = []
    async def call_model(self, items, instructions, tools, previous):
        sent.append(items)
        if len(sent) == 1:   # the owner speaks while the first step runs
            def add(st): st['revision'] += 1; st['inputs'].append({'revision': st['revision'], 'text': '品川じゃなくて東京で'})
            state.change(job, add)
        return turns.pop(0)
    async def call_tool(name, args): return [NS(type='text', text='ok')]
    async def list_tools(): return []
    monkeypatch.setattr(W.Worker, 'call_model', call_model)
    monkeypatch.setattr('app.mcp_server.call_tool', call_tool)
    monkeypatch.setattr('app.mcp_server.list_tools', list_tools)
    await W.Worker(job).run()
    s = state.read(job)
    assert any(i.get('role') == 'user' and '東京' in i['content'] for i in sent[1]) and s['applied_revision'] == s['revision'] == 1
    assert s['state'] == 'completed'


def test_mcp_tools_become_function_tools():
    tools = W.openai_tools([NS(name='browser', description='d', inputSchema={'type': 'object', 'properties': {}})])
    assert tools[0] == {'type': 'web_search'} and tools[1]['type'] == 'function' and tools[1]['name'] == 'browser'
