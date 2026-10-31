import asyncio
import json
import pytest
from app.services import voice_sideband as S
from app.services.voice_turn_intake import TurnIntake


@pytest.mark.asyncio
@pytest.mark.parametrize('tail', ['直して', '直して。うん', '直して。何をお願いしたか覚えてる？',
                                 '直して。参加費は無料にして', '直して。いや、変更しないで'])
async def test_complete_request_reaches_next_round_without_executing_stale_call(monkeypatch, tail):
    calls = []
    async def run(*args, **kw):
        calls.append(args)
        return {'accepted': True}
    monkeypatch.setattr('app.services.voice_responses.run_function', run)
    d = S.Dialogue(); d.intake = TurnIntake(0); d.intake.work_hint = True
    d.intake.heard('この案内文を半分くらいの長さに', 12400)
    d.intake.begin('early', 12400)
    d.intake.heard(tail, 12800)
    pending = {}; sent = []
    async def send(event): sent.append(event)
    async def event(body):
        await S.handle_response_event(send, 's', 'u', 'r', {'delegation_id': 'early', 'event': body},
                                      d, lambda *a, **kw: None, pending)
    await event({'type': 'response.output_item.done', 'item': {
        'type': 'function_call', 'name': 'start_work', 'call_id': 'c', 'arguments': '{}'}})
    await event({'type': 'response.completed'})
    assert not calls
    result = json.loads(sent[0]['item']['output'])
    assert result['accepted'] is False
    assert ''.join(result['latest_conversation']['caller_fragments_in_order']) == 'この案内文を半分くらいの長さに' + tail
    assert d.intake.delegations['early'] == 2
    assert not d.intake.owners  # delivery requests reasoning, never authorizes a call
    assert [e['type'] for e in sent] == ['response.item.create', 'response.create']
    # The model must choose its next operation from these words, including withdrawal.
    d.intake.heard('そのままにして', 14000)
    assert d.intake.reject('early') == 'newer_or_unassociated_speech'


@pytest.mark.asyncio
async def test_new_round_can_start_once_with_reconsidered_arguments(monkeypatch):
    calls = []
    async def run(name, args, *a, **kw):
        calls.append(args)
        return {'accepted': True}
    monkeypatch.setattr('app.services.voice_responses.run_function', run)
    d = S.Dialogue(); d.intake = TurnIntake(0); d.intake.work_hint = True
    d.intake.heard('参加費を', 1000); d.intake.begin('early', 1000)
    d.intake.heard('無料に変えて', 2000)
    d.intake.refreshed('early', 2)
    d.intake.begin('other', 2000)
    results = await asyncio.gather(*(S.execute_call({
        'name': 'start_work', 'call_id': key, 'arguments': json.dumps({'task': '参加費を無料に変える'})},
        'u', 'r', d, lambda *a, **kw: None, key) for key in ('early', 'other')))
    assert calls == [{'task': '参加費を無料に変える'}]
    assert sum(json.loads(out['output']).get('accepted') is True for out in results) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('failure,new_speech', [(True, False), (False, True)])
async def test_send_failure_or_new_speech_cannot_promote_unseen_revision(failure, new_speech):
    d = S.Dialogue(); d.intake = TurnIntake(0)
    d.intake.heard('送って', 1000); d.intake.begin('early', 1000)
    d.intake.heard('いや下書きだけ', 2000)
    async def result():
        return {'type': 'function_call_output', 'call_id': 'c', 'name': 'send_message_on_stage',
                'output': json.dumps({'accepted': False, 'reason': 'newer_or_unassociated_speech'})}
    pending = {'early': [asyncio.create_task(result())]}
    async def send(event):
        if event['type'] == 'response.item.create':
            if new_speech: d.intake.heard('全部やめて', 3000)
            if failure: raise OSError('uncertain delivery')
    coro = S.handle_response_event(send, 's', 'u', 'r', {'delegation_id': 'early',
        'event': {'type': 'response.completed'}}, d, lambda *a, **kw: None, pending)
    if failure:
        with pytest.raises(OSError): await coro
        assert d.intake.delegations['early'] == 1
    else:
        await coro
        assert d.intake.delegations['early'] == 2
    assert d.intake.reject('early') == 'newer_or_unassociated_speech'


@pytest.mark.asyncio
@pytest.mark.parametrize('name,accepted', [('start_work', True), ('steer_job', True), ('steer_job', False), ('job_status', True)])
async def test_acceptance_receives_speech_that_arrived_during_execution(name, accepted):
    d = S.Dialogue()
    d.add('user', '参加費を無料にして')
    async def result():
        d.add('assistant', 'うん、そうします。')
        d.add('user', '今どうなった？')
        return {'type': 'function_call_output', 'call_id': 'c', 'name': name,
                'output': json.dumps({'accepted': accepted, 'delivered': False})}
    pending = {'d': [asyncio.create_task(result())]}
    sent = []
    async def send(event): sent.append(event)
    await S.handle_response_event(send, 's', 'u', 'r', {'delegation_id': 'd',
        'event': {'type': 'response.completed'}}, d, lambda *a, **kw: None, pending)
    payload = json.loads(sent[0]['item']['output'])
    assert payload['accepted'] is accepted and payload['delivered'] is False
    if accepted and name in ('start_work', 'steer_job'):
        assert payload['conversation_at_result'][-2:] == [
            {'role': 'assistant', 'text': 'うん、そうします。'},
            {'role': 'user', 'text': '今どうなった？'}]
    else:
        assert 'conversation_at_result' not in payload
    assert [e['type'] for e in sent] == ['response.item.create', 'response.create']
