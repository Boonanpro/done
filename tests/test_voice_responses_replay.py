"""replay_operation never holds the delegation: it returns at once, the replay runs behind, and its result (or the
fallback job) arrives later. A delegation in flight silences the speech model, so a 44-second function was a 44-second hole."""
import asyncio
import json

import pytest

from app.services import voice_responses as R


@pytest.mark.asyncio
async def test_replay_returns_at_once_and_speaks_the_result_later(monkeypatch):
    flow = {'id': 'f1', 'host': 'x.example', 'name': '便を調べる', 'steps': [], 'slots': {}}
    spoken, started = [], asyncio.Event()
    async def run(f, values):
        started.set(); await asyncio.sleep(.05); return {'replayed': True, 'elapsed_ms': 50}
    async def read(action, params): return {'content': [{'type': 'text', 'text': 'URL: x タイトル: y 本文: のぞみ10号 10:30発'}]}
    async def speak(text): spoken.append(text)
    monkeypatch.setattr('app.services.browser_flows.all_flows', lambda: [flow])
    monkeypatch.setattr('app.services.browser_flows.run', run)
    monkeypatch.setattr('app.agent.v2.tools._execute_browser_tool', read)
    t0 = asyncio.get_event_loop().time()
    out = await R.run_function('replay_operation', {'id': 'f1', 'values': {}, 'task': '便を調べて'}, 'u', 'r', [], speak=speak)
    assert out['started'] and asyncio.get_event_loop().time()-t0 < .04 and spoken == []
    await asyncio.sleep(.15)
    assert started.is_set() and len(spoken) == 1 and 'のぞみ10号' in spoken[0]


@pytest.mark.asyncio
async def test_failed_replay_becomes_a_normal_job_without_a_word(monkeypatch):
    flow = {'id': 'f1', 'host': 'x.example', 'name': '便を調べる', 'steps': [], 'slots': {}}
    spoken, jobs = [], []
    async def run(f, values): return {'replayed': False, 'reason': 'unexpected_screen', 'elapsed_ms': 5}
    async def execute(params, room_id, user_id): jobs.append(params); return {'accepted': True}
    async def speak(text): spoken.append(text)
    monkeypatch.setattr('app.services.browser_flows.all_flows', lambda: [flow])
    monkeypatch.setattr('app.services.browser_flows.run', run)
    monkeypatch.setattr('app.services.command_center.execute', execute)
    out = await R.run_function('replay_operation', {'id': 'f1', 'values': {}, 'task': '24日の便を調べて'}, 'u', 'r', [], speak=speak)
    assert out['started']
    await asyncio.sleep(.05)
    assert spoken == [] and len(jobs) == 1 and jobs[0]['action'] == 'work' and '24日の便を調べて' in jobs[0]['task']
