"""The API job worker: one model step at a time, tools called in-process, steering fed as messages, result saved."""
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


class Fake:
    def __init__(self, steps, on_step=None):
        self.steps, self.on_step, self.seen = steps, on_step, []
    def start(self, instructions, tools, messages): self.seen.append(('start', messages))
    def tool_results(self, results): self.seen.append(('results', results))
    def user(self, text): self.seen.append(('user', text))
    async def step(self):
        if self.on_step: self.on_step(len(self.seen))
        return self.steps.pop(0)


def usage(): return {'input': 10, 'cached': 5, 'output': 3}


@pytest.fixture
def tools(monkeypatch):
    called = []
    async def call_tool(name, args): called.append((name, args)); return [type('T', (), {'type': 'text', 'text': 'URL: https://smart-ex.jp/ タイトル: スマートEX'})()]
    async def list_tools(): return []
    monkeypatch.setattr('app.mcp_server.call_tool', call_tool)
    monkeypatch.setattr('app.mcp_server.list_tools', list_tools)
    return called


@pytest.mark.asyncio
async def test_tool_calls_run_here_and_the_final_words_are_the_result(job, tools, monkeypatch):
    fake = Fake([{'text': 'トップを開きます', 'calls': [{'id': 'c1', 'name': 'browser', 'args': {'action': 'open_target'}}], 'usage': usage()},
                 {'text': '題名は「スマートEX」です。', 'calls': [], 'usage': usage()}])
    monkeypatch.setattr('app.services.api_job_providers.make', lambda model: fake)
    await W.Worker(job).run()
    s = state.read(job)
    assert tools == [('browser', {'action': 'open_target'})]
    assert fake.seen[1] == ('results', [{'id': 'c1', 'output': 'URL: https://smart-ex.jp/ タイトル: スマートEX', 'images': []}])
    assert s['state'] == 'completed' and s['result'] == '題名は「スマートEX」です。'
    assert s['usage']['steps'] == 2 and s['usage']['input'] == 20 and s['usage']['cached'] == 10
    kinds = [e for e in s['events'] if e['kind'] != 'diagnostic']
    assert [e['kind'] for e in kinds][-2:] == ['progress', 'result']


@pytest.mark.asyncio
async def test_steering_arrives_as_a_message_and_is_marked_applied(job, tools, monkeypatch):
    def steer(n):
        if n == 1:
            def add(st): st['revision'] += 1; st['inputs'].append({'revision': st['revision'], 'text': '品川じゃなくて東京で'})
            state.change(job, add)
    fake = Fake([{'text': '', 'calls': [{'id': 'c1', 'name': 'browser', 'args': {}}], 'usage': usage()},
                 {'text': '完了', 'calls': [], 'usage': usage()}], on_step=steer)
    monkeypatch.setattr('app.services.api_job_providers.make', lambda model: fake)
    await W.Worker(job).run()
    s = state.read(job)
    assert ('user', '追加の指示: 品川じゃなくて東京で') in fake.seen and s['applied_revision'] == s['revision'] == 1 and s['state'] == 'completed'


def test_provider_is_chosen_by_the_model_name():
    from app.services.api_job_providers import kind_of
    assert kind_of('gpt-6-astra') == 'openai' and kind_of('claude-opus-5-5') == 'anthropic' and kind_of('deepseek-v4-pro') == 'chat'
