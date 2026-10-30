from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace

import pytest
from app.agent import cli_runner as cr, provider_failover as pf


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(pf, '_blocked', {})
    monkeypatch.setattr(cr, '_room_model_cache', {})


def test_only_provider_rejections_trigger_handoff():
    assert pf.exhausted({'result': "You've hit your weekly limit · resets Nov 1 at 3pm"})
    assert pf.exhausted({'is_error': True, 'errors': ['rate_limit_exceeded']})
    assert not pf.exhausted({'text': 'The user has a weekly limit reached error.'})
    assert not pf.exhausted({'is_error': True, 'errors': ['Permission denied']})
    assert not pf.exhausted({'is_error': True, 'errors': ['context window exceeded']})


def test_saved_gpt_survives_stale_catalog_and_cross_process_switch(monkeypatch):
    from app.services import supabase_client
    model = ['gpt-6.1-sol']
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.side_effect = (
        lambda: SimpleNamespace(data=[{'metadata': {'model': model[0]}}]))
    monkeypatch.setattr(supabase_client, 'get_supabase_client', lambda: SimpleNamespace(client=db))
    monkeypatch.setattr(cr, '_ALLOWED_CLI_MODELS', {'opus'})
    monkeypatch.setattr(cr._model_catalog, 'current', lambda s: s or '')
    assert cr.resolve_room_backend('room') == ('gpt-6.1-sol', 'codex')
    model[0] = 'gpt-6-astra'
    assert cr.resolve_room_backend('room') == ('gpt-6-astra', 'codex')


def test_quota_sink_preserves_work_without_ending_run(monkeypatch):
    save = MagicMock()
    monkeypatch.setattr(cr, '_save_ai_message_sync', save)
    emit = MagicMock()
    assert cr._defer_quota_result({'is_error': True, 'result': "You've hit your weekly limit",
        'final_text_parts': ['File was written.', "You've hit your weekly limit"],
        'turn_blocks': [{'type': 'tool', 'name': 'Write'}]}, 'room', 'project', 'run', False, emit)
    assert save.call_args.kwargs['ends_turn'] is False
    assert save.call_args.args[1] == 'File was written.'
    assert emit.call_args.args[0]['quota_exhausted'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('initial', ['opus', 'gpt-6.1-sol'])
@pytest.mark.parametrize('both', [False, True])
async def test_bounded_bidirectional_handoff(monkeypatch, initial, both):
    from app.services.cancellation import CancellationRegistry
    from app.agent import streaming_session
    monkeypatch.setattr(cr, '_prepare_cli_inputs', AsyncMock(return_value=('system', 'mcp.json')))
    monkeypatch.setattr(cr, 'note_turn_input', lambda *a: None)
    monkeypatch.setattr(cr, '_load_session', lambda *a: 'old-session')
    monkeypatch.setattr(cr, '_clear_cli_session', lambda *a: None)
    monkeypatch.setattr(cr, '_ALLOWED_CLI_MODELS', {'opus', 'gpt-6.1-sol'})
    monkeypatch.setattr(cr._model_catalog, 'current', lambda s: s)
    monkeypatch.setattr(pf, 'alternative', lambda backend: 'opus' if backend == 'codex' else 'gpt-6.1-sol')
    monkeypatch.setattr(cr.turn_flow, 'claim_new_turn', lambda *a: None)
    monkeypatch.setattr(streaming_session, 'get_session', lambda *a: None)
    monkeypatch.setattr(CancellationRegistry, 'is_cancelled', lambda *a: False)
    monkeypatch.setattr(cr, '_save_ai_message_sync', MagicMock(return_value=True))
    monkeypatch.setattr(cr, '_update_run_sync', MagicMock())
    calls = []
    async def body(*args):
        calls.append(args)
        if len(calls) == 1 or both:
            yield {'type': 'result', 'is_error': True, 'quota_exhausted': True, 'partial_text': 'already wrote file'}
        else:
            yield {'type': 'result', 'text': 'continued', 'is_error': False}
    monkeypatch.setattr(cr, '_process_message_cli_body', body)
    events = [e async for e in cr.process_message_cli('room', 'user', 'finish task', model_override=initial)]
    assert len(calls) == 2
    assert calls[0][12] != calls[1][12]  # backend
    assert calls[1][13] is None  # no foreign CLI session resume
    assert 'already wrote file' in calls[1][2]
    results = [e for e in events if e['type'] == 'result']
    assert len(results) == 1 and results[0]['is_error'] is both


def test_cooldown_returns_to_preference(monkeypatch):
    monkeypatch.setattr(pf, 'alternative', lambda _: 'gpt-6-astra')
    pf.mark_exhausted('claude')
    assert pf.preferred('opus') == 'gpt-6-astra'
    monkeypatch.setattr(pf.time, 'time', lambda: 10**12)
    assert pf.preferred('opus') == 'opus'


@pytest.mark.asyncio
async def test_browser_disconnect_does_not_cancel_handoff(monkeypatch):
    import asyncio
    proceed, completed = asyncio.Event(), asyncio.Event()
    async def implementation(*args, **kwargs):
        yield {'type': 'reasoning', 'text': 'switching'}
        await proceed.wait()
        completed.set()
        yield {'type': 'result', 'text': 'done'}
    monkeypatch.setattr(cr, '_process_message_cli_with_failover', implementation)
    stream = cr.process_message_cli('room', 'user', 'task')
    await anext(stream)
    await stream.aclose()
    proceed.set()
    await asyncio.wait_for(completed.wait(), timeout=1)
