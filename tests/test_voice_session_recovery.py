import json
from unittest.mock import AsyncMock

import pytest
from app.services import voice_live as live, voice_session_store as store
from tests.test_voice_intake import input_for, answer


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DB', tmp_path/'sessions.sqlite3')
    monkeypatch.setattr(live, '_sessions', {})
    monkeypatch.setattr('app.services.voice_intake.list_owned', lambda *_: [])
    live.register('pending-test', 'owner', 'instructions', [], room_id='room')
    live.bind_session('pending-test', 'session')
    yield
    for state in live._sessions.values():
        state['agent'].close()


@pytest.mark.asyncio
async def test_restart_restores_owner_and_pending_result_without_reexecution(isolated_store):
    agent = live._sessions['session']['agent']
    agent.judge.choose = AsyncMock(return_value=answer('work'))
    result = await live.respond('session', 'owner', input_for('予約内容を確認して'))
    call = result['output'][0]
    live._sessions.clear()  # Simulate process memory loss after the client executed a tool.
    assert live.get_session('session', 'intruder') is None
    recovered = live.get_session('session', 'owner')
    assert recovered['room_id'] == 'room'
    recovered['agent'].judge.choose = AsyncMock(side_effect=AssertionError('must not classify or replay'))
    output = [{'type':'function_call_output', 'call_id':call['call_id'], 'output':'{"accepted":true}'}]
    response = await live.respond('session', 'owner', output)
    assert all(item['type']=='message' for item in response['output'])
    live._sessions.clear()
    with pytest.raises(ValueError, match='処理済み'):
        await live.respond('session', 'owner', output)


@pytest.mark.asyncio
async def test_restart_allows_hangup_and_closed_session_cannot_return(isolated_store):
    live._sessions.clear()
    agent = live.get_session('session', 'owner')['agent']
    agent.judge.choose = AsyncMock(return_value=answer('end'))
    result = await live.respond('session', 'owner', input_for('電話を切って'))
    assert result['output'][0]['name'] == 'enter_voice_standby'
    live.close('session', 'owner')
    assert live.get_session('session', 'owner') is None


def test_expired_session_is_not_restored(isolated_store):
    live._sessions.clear()
    with store.connect() as db:
        db.execute('UPDATE sessions SET expires=0')
    assert live.get_session('session', 'owner') is None
