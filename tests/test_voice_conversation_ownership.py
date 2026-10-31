"""Offline checks: a changed requirement is accepted before a worker applies it.
No calls, jobs, external messages or model requests are started here.
"""
from unittest.mock import AsyncMock
import pytest
from app.services import voice_responses, voice_live

@pytest.mark.asyncio
@pytest.mark.parametrize('applied', [3, 4])
async def test_added_condition_reports_actual_worker_revision(monkeypatch, applied):
    monkeypatch.setattr('app.services.command_job_state.list_owned', lambda *a: [{'id': 'job', 'state': 'running'}])
    execute = AsyncMock(return_value={'job': {'id': 'job', 'state': 'running', 'revision': 4, 'applied_revision': applied}})
    monkeypatch.setattr('app.services.command_center.execute', execute)
    result = await voice_responses.run_function('steer_job', {'instruction': '募集人数の数字はそのままで'}, 'owner', 'room', [])
    assert result['accepted'] is True
    assert result['delivered'] is (applied == 4)
    assert execute.call_args.args[0]['task'] == '募集人数の数字はそのままで'

@pytest.mark.asyncio
async def test_ambiguous_control_receipt_is_not_success(monkeypatch):
    monkeypatch.setattr('app.services.command_job_state.list_owned', lambda *a: [{'id': 'job', 'state': 'running'}])
    monkeypatch.setattr('app.services.command_center.execute', AsyncMock(return_value={'error': 'not accepted'}))
    result = await voice_responses.run_function('steer_job', {'instruction': '冒頭を短くして'}, 'owner', 'room', [])
    assert result['accepted'] is False
    assert result['delivered'] is False

def test_assembled_session_has_consistent_conversation_policy(monkeypatch):
    monkeypatch.setattr('app.services.dan_core.shared', lambda *a: '共通の指示')
    session = voice_live.session_config(room_id='room', user_id='owner')
    speech = session['instructions']
    backend = session['delegation']['responses']['instructions']
    assert '理解した目的に短く応答する' in speech
    assert '「頼みました」「作業に回しました」まで' not in speech
    assert '返事を空にする' not in backend
    assert 'search/read/status' in backend
    assert '共通の指示' in backend
