"""A late stop or late run creation must not target the next request in a room."""
import uuid
from unittest.mock import Mock
import threading
import pytest

from app.services.cancellation import CancellationRegistry as C


def test_old_stop_cannot_cancel_replacement_even_if_old_cleanup_arrives_later():
    room = str(uuid.uuid4())
    try:
        first = C.register(room)
        assert C.bind_run(room, first, 'first')
        second = C.register(room)
        assert C.bind_run(room, second, 'second')
        assert not C.cancel_run(room, 'first')
        C.unregister_if_match(room, first)
        assert not second.is_set()
        assert C.cancel_run(room, 'second')
        assert second.is_set()
        assert not first.is_set()
    finally:
        C.unregister(room)


def test_process_stop_uses_captured_object_if_next_run_starts_during_stop(monkeypatch):
    from app.agent import cli_runner as runner
    room = str(uuid.uuid4())
    first, second = Mock(), Mock()
    first.poll.return_value = 0
    killed = []
    def terminate(process):
        # Recreate the precise race: new work registers between lookup and kill.
        runner.register_cli_process(room, 'second', second)
        killed.append(process)
    monkeypatch.setattr(runner, '_terminate_process', terminate)
    try:
        runner.register_cli_process(room, 'first', first)
        result = runner.request_cli_run_stop(room, 'first')
        assert killed == [first]
        assert result == {'accepted': True, 'process_exited': True, 'stopped': False}
        runner.unregister_cli_process(room, first)
        assert runner._active_processes[room] is second
        assert runner.request_cli_run_stop(room, 'first')['accepted'] is False
        assert runner.request_cli_run_stop(room, '')['accepted'] is False
        assert killed == [first]
    finally:
        runner.unregister_cli_process(room, second)


def test_delayed_database_creation_cannot_rebind_new_registration():
    room = str(uuid.uuid4())
    try:
        first = C.register(room)
        second = C.register(room)
        assert not C.bind_run(room, first, 'old-db-result')
        assert not C.cancel_run(room, 'old-db-result')
        assert not second.is_set()
        assert C.bind_run(room, second, 'new')
        assert not C.bind_run(room, second, 'other')
        assert not C.cancel_run(room, '')
        C.unregister_if_match(room, second)
        assert not C.cancel_run(room, 'new')
    finally:
        C.unregister(room)


def test_streaming_stop_matches_run_before_sending_or_starting_nudger(monkeypatch):
    from app.agent.streaming_session import StreamingSession
    session = StreamingSession.__new__(StreamingSession)
    session._lock = threading.Lock()
    session._run_id = 'new'
    session.room_id = str(uuid.uuid4())
    session._turn = object()
    session.clear_pending = Mock()
    session.is_turn_active = lambda: True
    session._send_interrupt = Mock()
    nudger = Mock()
    monkeypatch.setattr('app.agent.streaming_session.threading.Thread', nudger)
    assert not session.interrupt(expected_run_id='old')
    assert not session.interrupt(expected_run_id='')
    session._send_interrupt.assert_not_called()
    nudger.assert_not_called()
    assert session.interrupt(expected_run_id='new')
    session._send_interrupt.assert_called_once()
    nudger.return_value.start.assert_called_once()


def test_cancelled_run_cannot_restart_after_new_registration(monkeypatch):
    from app.agent import cli_runner, codex_runner
    from app.agent.streaming_session import StreamingSession
    from app.services.cancellation import CancelledError
    room = str(uuid.uuid4())
    event = C.register(room)
    C.bind_run(room, event, 'cancelled-run')
    assert C.cancel_run(room, 'cancelled-run')
    replacement = C.register(room)
    C.bind_run(room, replacement, 'new-run')
    popen = Mock(side_effect=AssertionError('must not launch a stopped run'))
    monkeypatch.setattr(cli_runner.subprocess, 'Popen', popen)
    try:
        for run in (cli_runner._run_cli_process, codex_runner.run_codex_process):
            with pytest.raises(CancelledError):
                run([], 'work', {}, room, Mock(), run_id='cancelled-run')
        session = StreamingSession.__new__(StreamingSession)
        session.room_id = room
        session.start = Mock(side_effect=AssertionError('must not start'))
        result = session.run_turn('retry', Mock(), run_id='cancelled-run')
        assert result['subtype'] == 'cancelled_before_start'
        assert not replacement.is_set()
        assert not C.is_run_cancelled(room, 'new-run')
        popen.assert_not_called()
    finally:
        C.unregister(room)


def test_stop_between_followup_drain_and_send_does_not_start_another_turn(monkeypatch):
    from app.agent.streaming_session import StreamingSession
    room = str(uuid.uuid4())
    session = StreamingSession(room, lambda: [], {}, '.')
    monkeypatch.setattr(session, 'is_alive', lambda: True)
    sent = []
    def send(content):
        sent.append(content)
        session._turn.result = {'type': 'result', 'result': 'partial'}
        session._turn.done.set()
    def drain():
        # The first cancellation check has passed; the stop now wins before
        # the queued turn acquires the session lock to send its input.
        C.mark_matched_run_cancelled(room, 'run')
        return 'queued before stop'
    monkeypatch.setattr(session, '_send_user', send)
    monkeypatch.setattr(session, '_drain_pending', drain)
    result = session.run_turn('original', Mock(), run_id='run')
    assert result['result'] == 'partial'
    assert sent == ['original']
    assert session._run_id is None
    assert session._turn is None


@pytest.mark.asyncio
async def test_oneshot_display_loop_cannot_translate_old_stop_into_room_kill(monkeypatch):
    import inspect
    import time
    from app.agent import cli_runner as runner, streaming_session
    room = str(uuid.uuid4())
    original = C.register(room)
    C.bind_run(room, original, 'old')
    replacement = None
    def start():
        nonlocal replacement
        C.cancel_run(room, 'old')
        replacement = C.register(room)
        C.bind_run(room, replacement, 'new')
    thread = Mock()
    thread.start.side_effect = start
    monkeypatch.setattr(runner.threading, 'Thread', Mock(return_value=thread))
    async def inline(func, *args, **kwargs):
        return func(*args, **kwargs)
    monkeypatch.setattr(runner.asyncio, 'to_thread', inline)
    monkeypatch.setattr(streaming_session, 'streaming_enabled', lambda: False)
    monkeypatch.setattr(streaming_session, 'get_session', lambda *a: None)
    scoped, broad = Mock(return_value={'accepted': False}), Mock()
    monkeypatch.setattr(runner, 'request_cli_run_stop', scoped)
    monkeypatch.setattr(runner, 'kill_cli_process', broad)
    # Keep this entirely inside the async iterator, without even a thread or
    # process launch. Replacement occurs exactly at the old worker's launch.
    args = {name: None for name in inspect.signature(runner._process_message_cli_body).parameters}
    args.update(room_id=room, user_id='owner', content='hello', run_id='old',
                skip_save=True, system_prompt='', setup_start=time.perf_counter(),
                backend='codex', cli_model='test')
    try:
        events = [event async for event in runner._process_message_cli_body(**args)]
        scoped.assert_called_once_with(room, 'old')
        broad.assert_not_called()
        assert replacement is not None and not replacement.is_set()
        assert events == [{'type': 'cancelled', 'stopped': False}]
    finally:
        C.unregister(room)
