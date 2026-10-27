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
