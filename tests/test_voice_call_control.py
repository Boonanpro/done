import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.services.voice_call_control import QUESTIONS, decision, review, CallControl


def result(call='end', intent='request', confidence=.99):
    answers = {}
    for name, selected in [('call', call), ('intent', intent)]:
        answers[name] = {'choice': selected, 'confidence': confidence,
                         'probabilities': {k: confidence if k == selected else (1-confidence)/2
                                           for k in QUESTIONS[name]['criteria']}}
    return {'available': True, 'answers': answers, 'elapsed_ms': 200, 'model': 'test'}


def test_abstains_on_disagreement_uncertainty_or_unavailability():
    assert decision(result()) == 'end'
    for data in [result(intent='other'), result(call='keep'), result(confidence=.94), {'available': False}]:
        assert decision(data) == 'review'
    data = result()
    data['answers']['call']['probabilities']['end'] = .7
    assert decision(data) == 'review'


@pytest.mark.asyncio
async def test_assistant_farewell_never_replaces_latest_user_and_context_is_bounded():
    client = AsyncMock()
    client.choose.return_value = result()
    with patch('app.services.voice_call_control.Decisions') as constructor:
        constructor.return_value.__aenter__ = AsyncMock(return_value=client)
        constructor.return_value.__aexit__ = AsyncMock()
        dialogue = [{'role': 'user', 'text': str(i)} for i in range(12)]
        dialogue += [{'role': 'assistant', 'text': 'また後で'}]
        answer = await review('owner', dialogue)
        state = client.choose.call_args.args[0]
    assert state['latest_user'] == '11'
    assert len(state['recent_dialogue']) == 7
    assert 'また後で' not in str(state)
    assert answer['action'] == 'end'
    assert 'answers' not in answer


@pytest.mark.asyncio
async def test_control_route_authorization_and_concurrent_request_bound():
    from app.api import voicelog_routes as routes
    from app.services import voice_live
    body = routes.LiveCallControlRequest(session_id='control-test', dialogue=[{'role':'user','text':'切って'}])
    state = {'user_id': 'owner'}
    entered, release = asyncio.Event(), asyncio.Event()
    async def held_review(*args):
        entered.set()
        await release.wait()
        return {'action':'review'}
    with patch.dict(voice_live._sessions, {'control-test':state}), \
         patch.object(routes, '_get_user', return_value=SimpleNamespace(user_id='foreign')), \
         patch('app.services.voice_call_control.review', new_callable=AsyncMock) as classify:
        with pytest.raises(HTTPException) as exc:
            await routes.live_call_control(None, body)
        assert exc.value.status_code == 409
        classify.assert_not_called()
    with patch.dict(voice_live._sessions, {'control-test':state}), \
         patch.object(routes, '_get_user', return_value=SimpleNamespace(user_id='owner')), \
         patch('app.services.voice_call_control.review', side_effect=held_review) as classify:
        pending = asyncio.create_task(routes.live_call_control(None, body))
        await entered.wait()
        assert (await routes.live_call_control(None, body))['reason'] == 'pending'
        release.set()
        await pending
        assert not state['call_control_pending']
        assert classify.call_count == 1


@pytest.mark.asyncio
async def test_cancelled_review_releases_inflight_guard():
    from app.api import voicelog_routes as routes
    from app.services import voice_live
    state = {'user_id':'owner'}
    body = routes.LiveCallControlRequest(session_id='cancel-test', dialogue=[{'role':'user','text':'切って'}])
    with patch.dict(voice_live._sessions, {'cancel-test':state}), \
         patch.object(routes, '_get_user', return_value=SimpleNamespace(user_id='owner')), \
         patch('app.services.voice_call_control.review', side_effect=asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await routes.live_call_control(None, body)
    assert not state['call_control_pending']


@pytest.mark.asyncio
async def test_call_warmup_reuses_pool_without_classification_and_closes_it():
    client = AsyncMock()
    client.choose.side_effect = [{'available':False,'elapsed_ms':900}, result()]
    with patch('app.services.voice_call_control.Decisions', return_value=client) as constructor:
        control = CallControl('owner')
        control.warm()
        control.warm()
        await control.preparing
        client.choose.assert_not_called()
        client._credential.assert_awaited_once()
        dialogue = [{'role':'user','text':'通話を終わらせて'}]
        assert (await review('owner',dialogue,control))['action'] == 'review'
        assert (await review('owner',dialogue,control))['action'] == 'end'
        constructor.assert_called_once()
        assert client.unavailable is False
        control.close()
        await asyncio.sleep(0)
        client.__aexit__.assert_awaited_once()
        assert (await control.choose({}))['available'] is False


@pytest.mark.asyncio
async def test_cancelling_a_request_does_not_cancel_shared_credential_preparation():
    ready = asyncio.Event()
    client = AsyncMock()
    client._credential.side_effect = lambda: None
    async def prepare():
        await ready.wait()
    client._credential.side_effect = prepare
    client.choose.return_value = result()
    with patch('app.services.voice_call_control.Decisions',return_value=client):
        control = CallControl('owner')
        request = asyncio.create_task(control.choose({}))
        await asyncio.sleep(0)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):await request
        assert not control.preparing.cancelled()
        ready.set()
        assert (await control.choose({}))['available'] is True
        control.close()
        await asyncio.sleep(0)
