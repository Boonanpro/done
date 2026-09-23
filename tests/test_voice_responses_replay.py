"""replay_operation never holds the delegation: it starts a job that replays the flow first (in the job's browser, with the
owner's id for Jev) and returns at once; the job's result is spoken when it arrives."""
import pytest

from app.services import voice_responses as R


@pytest.mark.asyncio
async def test_replay_starts_a_job_with_the_flow_and_returns_at_once(monkeypatch):
    flow = {'id': 'f1', 'host': 'x.example', 'name': '便を調べる', 'steps': [], 'slots': {}}
    jobs = []
    async def execute(params, room_id, user_id): jobs.append(params); return {'accepted': True}
    monkeypatch.setattr('app.services.browser_flows.all_flows', lambda: [flow])
    monkeypatch.setattr('app.services.command_center.execute', execute)
    out = await R.run_function('replay_operation', {'id': 'f1', 'values': {'時': '10'}, 'task': '26日の便を調べて'}, 'u', 'r', [])
    assert out['started'] and len(jobs) == 1
    assert jobs[0]['engine'] == 'api' and jobs[0]['replay'] == {'id': 'f1', 'values': {'時': '10'}} and '26日の便を調べて' in jobs[0]['task']


@pytest.mark.asyncio
async def test_an_unknown_flow_is_an_error_not_a_job(monkeypatch):
    monkeypatch.setattr('app.services.browser_flows.all_flows', lambda: [])
    out = await R.run_function('replay_operation', {'id': 'nope', 'values': {}, 'task': 'x'}, 'u', 'r', [])
    assert 'error' in out


@pytest.mark.asyncio
async def test_saved_information_that_could_not_be_checked_is_not_reported_as_missing(monkeypatch):
    async def saved_items(judge, user_id, what, dialogue): return {'available': False, 'answer': []}
    monkeypatch.setattr('app.services.voice_parts.saved_items', saved_items)
    out = await R.run_function('get_saved_information', {'what': '郵便番号'}, 'u', 'r', [])
    assert '確認できなかった' in out['note'] and '保存されていません' not in out['note']
