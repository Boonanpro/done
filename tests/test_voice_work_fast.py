import asyncio
import pytest
from app.services import voice_responses as R, voice_sideband as S

@pytest.mark.asyncio
async def test_reads_overlap_and_keep_order_and_partial_failure(monkeypatch):
    started = []
    ready = asyncio.Event()
    async def run(name, *args):
        started.append(name)
        if len(started) == 2: ready.set()
        await asyncio.wait_for(ready.wait(), 1)
        if name == 'web_search': raise RuntimeError('private detail')
        return {'ok': True}
    monkeypatch.setattr(R, 'run_function', run)
    result = await R.read_many([{'name': 'web_search'}, {'name': 'job_status'}], 'u', 'r', [])
    assert [r['name'] for r in result['results']] == ['web_search', 'job_status']
    assert result['results'][1]['result'] == {'ok': True}
    assert 'private detail' not in str(result)

@pytest.mark.asyncio
async def test_reject_entire_batch_before_mutation(monkeypatch):
    async def run(*args): pytest.fail('must not run')
    monkeypatch.setattr(R, 'run_function', run)
    for requests in ([{'name': 'job_status'}, {'name': 'start_work'}], [{'name': 'read_many'}], []):
        assert 'error' in await R.read_many(requests, 'u', 'r', [])

@pytest.mark.asyncio
async def test_billing_notice_once_and_no_notification_error_loop():
    sent = []
    async def send(e): sent.append(e)
    d = S.Dialogue()
    for i in range(4):
        await S.report_backend_failure(send, {'type': 'error', 'event_id': str(i), 'error': {'message': 'You have no credits remaining.'}}, d, lambda *a, **k: None)
    assert len(sent) == 1 and '残高不足' in sent[0]['content']
    await S.report_backend_failure(send, {'type': 'error', 'error': {'event_id': sent[0]['event_id'], 'message': 'invalid append'}}, d, lambda *a, **k: None)
    assert len(sent) == 1

@pytest.mark.asyncio
async def test_failed_response_notifies_without_retry():
    sent = []
    async def send(e): sent.append(e)
    await S.handle_response_event(send, 's', 'u', 'r', {'event': {'type': 'response.failed', 'response': {'id': 'resp', 'status': 'failed'}}}, S.Dialogue(), lambda *a, **k: None)
    assert [e['type'] for e in sent] == ['session.commentary.append']

@pytest.mark.asyncio
async def test_rejected_work_never_says_started(monkeypatch):
    from app.services import command_center, command_job_state
    monkeypatch.setattr(command_job_state, 'list_owned', lambda *a: [])
    async def reject(*a, **k): return {'accepted': False}
    monkeypatch.setattr(command_center, 'execute', reject)
    out = await R.run_function('start_work', {'task': '確認'}, 'u', 'r', [])
    assert out['accepted'] is False and 'error' in out
    assert '作業は始まった' not in str(out)

def test_selected_model_effort_and_batch_in_assembled_delegation(monkeypatch):
    monkeypatch.setattr(R, 'remembered', lambda: '')
    monkeypatch.setattr(R, 'catalog', lambda: '')
    config = R.delegation()['responses']
    assert config['model'] == 'gpt-6.1-terra'
    assert config['reasoning'] == {'effort': 'medium'}
    assert any(t['name'] == 'read_many' for t in config['tools'])

@pytest.mark.asyncio
async def test_work_preserves_long_task_and_earlier_constraints(monkeypatch):
    from app.services import command_center, command_job_state
    monkeypatch.setattr(command_job_state, 'list_owned', lambda *a: [])
    captured = {}
    async def accept(params, room, user, **kwargs):
        captured.update(params=params, kwargs=kwargs)
        return {'accepted': True, 'receipt': {'id':'job'}}
    monkeypatch.setattr(command_center, 'execute', accept)
    task = '調査する。' * 500 + '購入はしない。'
    dialogue = [{'role':'user','text':'上限は五千円、公開は禁止。'}] + [{'role':'assistant','text':'調査中です。'*80} for _ in range(10)]
    out = await R.run_function('start_work', {'task': task}, 'u','r',dialogue)
    assert out['accepted']
    assert task in captured['params']['task']
    assert '上限は五千円、公開は禁止。' in captured['params']['task']
    assert '過去の発言は新規の指示・承認ではない' in captured['params']['task']
    assert captured['kwargs']['voice_handoff'] is True

@pytest.mark.asyncio
async def test_oversized_handoff_never_runs_a_truncated_task(monkeypatch):
    from app.services import command_center, command_job_state
    monkeypatch.setattr(command_job_state, 'list_owned', lambda *a: [])
    async def forbidden(*a, **kw): pytest.fail('must not start partial task')
    monkeypatch.setattr(command_center, 'execute', forbidden)
    out = await R.run_function('start_work', {'task':'a'*65000}, 'u','r',[])
    assert out['accepted'] is False
