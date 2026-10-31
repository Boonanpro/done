from unittest.mock import AsyncMock, Mock
import uuid

import pytest

from app.services import run_stop
from app.services.cancellation import CancellationRegistry as C


@pytest.fixture(autouse=True)
def isolated_services(monkeypatch):
    # No credential loading or database connection in executor tests.
    monkeypatch.setattr('app.services.run_service.RunService.__init__', lambda self: None)
    monkeypatch.setattr('app.services.project_service.ProjectService.__init__', lambda self: None)


@pytest.mark.asyncio
async def test_durable_stop_restoration_allows_a_different_new_run(monkeypatch):
    room = str(uuid.uuid4())
    C.mark_matched_run_cancelled(room, 'old')
    lookup = AsyncMock(return_value={'id': 'new', 'room_id': room, 'metadata': {}})
    monkeypatch.setattr('app.services.run_service.RunService.get_run', lookup)
    assert await run_stop.restore_stop(room, 'new') is False
    assert C.is_run_cancelled(room, 'old')


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['stopped', 'missing', 'wrong_room', 'unavailable'])
async def test_restart_checks_durable_stop_before_preparing_model(case, monkeypatch):
    from app.agent import cli_runner, turn_dispatch
    room = str(uuid.uuid4())
    run = {'id': 'old', 'room_id': room, 'metadata': {'stop_request': {'stopped': False}}}
    if case == 'missing': run = None
    if case == 'wrong_room': run['room_id'] = 'another-room'
    lookup = AsyncMock(return_value=run)
    if case == 'unavailable': lookup.side_effect = RuntimeError('database offline')
    monkeypatch.setattr('app.services.run_service.RunService.get_run', lookup)
    monkeypatch.setattr(turn_dispatch, 'remote_required', lambda: False)
    prepare = AsyncMock(side_effect=AssertionError('must not prepare or launch a model'))
    monkeypatch.setattr(cli_runner, '_prepare_cli_inputs', prepare)
    event = C.register(room)
    C.bind_run(room, event, 'new')
    try:
        events = [ev async for ev in cli_runner._process_message_cli_with_failover(
            room, 'owner', 'retry old', run_id='old')]
        prepare.assert_not_awaited()
        assert not event.is_set(), 'restoring old stop must not close the new run gate'
        if case == 'stopped':
            assert events == [{'type': 'cancelled', 'stopped': False}]
            assert C.is_run_cancelled(room, 'old')
        else:
            assert events[0]['type'] == 'error'
            assert not C.is_run_cancelled(room, 'old')
    finally:
        C.unregister(room)


@pytest.mark.asyncio
@pytest.mark.parametrize('saved', [True, False])
async def test_stop_goes_to_exact_execution_and_never_claims_exit(monkeypatch, saved):
    from app.core.generations import identity
    room = str(uuid.uuid4())
    run = {'id': 'run', 'project_id': 'p', 'room_id': room, 'metadata': {'process_owner': identity()}}
    monkeypatch.setattr('app.services.project_service.ProjectService.get_project',
                        AsyncMock(return_value={'user_id': 'u', 'room_id': room}))
    monkeypatch.setattr('app.services.run_service.RunService.update_run', AsyncMock(return_value={'id': 'run'} if saved else None))
    session = Mock()
    session.interrupt.return_value = True
    monkeypatch.setattr('app.agent.streaming_session.get_session', lambda r: session)
    process_stop = Mock(return_value={'accepted': False})
    monkeypatch.setattr('app.agent.cli_runner.request_cli_run_stop', process_stop)
    event = C.register(room)
    C.bind_run(room, event, 'run')
    try:
        out = await run_stop.local_stop(run, 'u')
        assert out['accepted'] is True and out['stopped'] is False
        assert ('記録の保存' in out['note']) is (not saved)
        assert event.is_set()
        session.interrupt.assert_called_once_with(expected_run_id='run')
        process_stop.assert_called_once_with(room, 'run')
    finally:
        C.unregister(room)


@pytest.mark.asyncio
@pytest.mark.parametrize('wrong', ['owner', 'process', 'job'])
async def test_wrong_owner_process_and_background_job_never_touch_executor(monkeypatch, wrong):
    from app.core.generations import identity
    meta = {'process_owner': identity()}
    if wrong == 'process': meta['process_owner'] = {'pid': -1, 'created': 0}
    if wrong == 'job': meta['started_by'] = 'command_center'
    run = {'id': 'run', 'project_id': 'p', 'room_id': 'r', 'metadata': meta}
    monkeypatch.setattr('app.services.project_service.ProjectService.get_project',
                        AsyncMock(return_value={'user_id': 'other' if wrong == 'owner' else 'u', 'room_id': 'r'}))
    executor = Mock(side_effect=AssertionError('must not touch executor'))
    monkeypatch.setattr('app.agent.streaming_session.get_session', executor)
    if wrong == 'owner':
        with pytest.raises(PermissionError): await run_stop.local_stop(run, 'u')
    else:
        assert not (await run_stop.local_stop(run, 'u'))['accepted']
    executor.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('host,origin,token', [('example.com', None, True), ('127.0.0.1', 'https://other', True), ('127.0.0.1', None, False)])
async def test_stop_endpoint_requires_local_auth_before_database(monkeypatch, host, origin, token):
    from fastapi import HTTPException
    from app.core.api import command_job_routes as routes
    request = Mock()
    request.client.host = host
    request.headers = {'origin': origin, 'x-dan-browser-token': 'test'}
    monkeypatch.setattr(routes.browser_lifecycle, 'authorized', lambda _: token)
    lookup = AsyncMock(side_effect=AssertionError('auth first'))
    monkeypatch.setattr('app.services.run_service.RunService.get_run', lookup)
    with pytest.raises(HTTPException) as raised:
        await routes.stop_run(routes.StopRun(run_id='run', user_id='u'), request)
    assert raised.value.status_code == 403
    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_stop_reaches_owner_route_without_waking_other_room(monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from app.core.api import command_job_routes as routes
    from app.core import generations as G
    from app.services import command_center, voice_responses
    room = str(uuid.uuid4())
    run = {'id': 'specific-run', 'project_id': 'project', 'room_id': room,
           'metadata': {'process_owner': G.identity()}}
    project = {'id': 'project', 'room_id': room, 'user_id': 'u'}
    chat = AsyncMock()
    chat.get_room.return_value = {'id': room}
    monkeypatch.setattr(command_center, 'ChatService', lambda: chat)
    monkeypatch.setattr('app.services.project_service.ProjectService.get_project', AsyncMock(return_value=project))
    monkeypatch.setattr('app.services.run_service.RunService.get_run', AsyncMock(return_value=run))
    monkeypatch.setattr('app.services.run_service.RunService.update_run', AsyncMock())
    monkeypatch.setattr(G, 'read', lambda _: {'run_id': 'specific-run'})
    monkeypatch.setattr(G, 'owner', lambda *a: {'core': 9999})
    token = tmp_path / 'token'
    token.write_text('test-only')
    monkeypatch.setattr(routes.browser_lifecycle, '_token_path', lambda: token)
    monkeypatch.setattr(routes.browser_lifecycle, 'authorized', lambda value: value == 'test-only')
    session = Mock()
    session.interrupt.return_value = True
    monkeypatch.setattr('app.agent.streaming_session.get_session', lambda _: session)
    monkeypatch.setattr('app.agent.cli_runner.request_cli_run_stop', lambda *a: {'accepted': False})
    app = FastAPI()
    app.include_router(routes.router)
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: client(
        transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 1234)), **kw))
    event = C.register(room)
    C.bind_run(room, event, 'specific-run')
    try:
        result = await voice_responses.run_function('stop_run', {'project_id': 'project', 'run_id': 'specific-run'}, 'u', 'origin', [])
        assert result['accepted'] is True and result['stopped'] is False
        session.interrupt.assert_called_once_with(expected_run_id='specific-run')
        assert event.is_set()
        chat.send_message.assert_not_awaited()
    finally:
        C.unregister(room)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [False, True])
async def test_internal_run_stop_during_preparation_never_launches(monkeypatch, failure):
    from app.agent import cli_runner, turn_dispatch
    room = str(uuid.uuid4())
    run = {'id': 'auto', 'room_id': room, 'metadata': {}}
    create = AsyncMock(return_value=run)
    monkeypatch.setattr('app.services.run_service.RunService.create_run', create)
    monkeypatch.setattr('app.services.run_service.RunService.get_run', AsyncMock(return_value=run))
    monkeypatch.setattr(turn_dispatch, 'remote_required', lambda: False)
    monkeypatch.setattr(cli_runner, 'note_turn_input', lambda *a: None)
    successor = C.register(room)
    C.bind_run(room, successor, 'different')
    async def prepare(*args):
        assert C.cancel_run(room, 'auto')
        assert not successor.is_set()
        if failure:
            raise ValueError('preparation failed')
        return 'prompt', 'config'
    monkeypatch.setattr(cli_runner, '_prepare_cli_inputs', prepare)
    monkeypatch.setattr(cli_runner, '_process_message_cli_body', Mock(side_effect=AssertionError('no model start')))
    async def collect():
        return [ev async for ev in cli_runner._process_message_cli_with_failover(
            room, 'owner', 'task', project_id='project')]
    try:
        if failure:
            with pytest.raises(ValueError):
                await collect()
        else:
            assert await collect() == [{'type': 'cancelled', 'stopped': False}]
        create.assert_awaited_once()
        assert (room, 'auto') not in C._run_events
        assert C.is_run_cancelled(room, 'auto')
        assert not successor.is_set()
    finally:
        C.unregister(room)


def test_run_scope_duplicate_and_stale_cleanup_do_not_replace_execution():
    import threading
    room = str(uuid.uuid4())
    event = C.register_run(room, 'run')
    with pytest.raises(RuntimeError):
        C.register_run(room, 'run')
    C.unregister_run(room, 'run', threading.Event())
    assert C.cancel_run(room, 'run')
    assert event.is_set()
    C.unregister_run(room, 'run', event)
    assert not C.cancel_run(room, 'run')


@pytest.mark.asyncio
async def test_voice_stop_stops_real_writer_and_leaves_successor_running(monkeypatch, tmp_path):
    import asyncio
    import subprocess
    import sys
    from app.agent import cli_runner as runner
    from app.core import generations as G
    from app.services import voice_responses, command_center
    room = str(uuid.uuid4())
    run = {'id': 'writer', 'project_id': 'p', 'room_id': room,
           'metadata': {'process_owner': G.identity()}}
    project = {'id': 'p', 'user_id': 'u', 'room_id': room}
    chat = AsyncMock()
    chat.get_room.return_value = {'id': room}
    monkeypatch.setattr(command_center, 'ChatService', lambda: chat)
    monkeypatch.setattr('app.services.project_service.ProjectService.get_project', AsyncMock(return_value=project))
    monkeypatch.setattr('app.services.run_service.RunService.get_run', AsyncMock(return_value=run))
    monkeypatch.setattr('app.services.run_service.RunService.update_run', AsyncMock(return_value=run))
    # Transport is covered separately; this exercises the real process handles.
    monkeypatch.setattr(run_stop, 'request_stop', run_stop.local_stop)
    monkeypatch.setattr('app.agent.streaming_session.get_session', lambda _: None)
    writer = "import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); p.write_text('started'); time.sleep(2); p.write_text('unwanted edit')"
    first = subprocess.Popen([sys.executable, '-c', writer, str(tmp_path/'first')])
    second = None
    try:
        runner.register_cli_process(room, 'writer', first)
        for _ in range(100):
            if (tmp_path/'first').exists(): break
            await asyncio.sleep(.01)
        assert (tmp_path/'first').read_text() == 'started'
        receipt = await voice_responses.run_function('stop_run', {'project_id': 'p', 'run_id': 'writer'}, 'u', 'call', [])
        assert receipt['accepted'] and not receipt['stopped']
        assert first.poll() is not None
        second = subprocess.Popen([sys.executable, '-c', writer, str(tmp_path/'second')])
        runner.register_cli_process(room, 'successor', second)
        late = await voice_responses.run_function('stop_run', {'project_id': 'p', 'run_id': 'writer'}, 'u', 'call', [])
        assert not late['accepted']
        await asyncio.to_thread(second.wait, 5)
        assert (tmp_path/'first').read_text() == 'started'
        assert (tmp_path/'second').read_text() == 'unwanted edit'
        chat.send_message.assert_not_awaited()
    finally:
        for process in (first, second):
            if process is not None:
                if process.poll() is None: process.kill(); process.wait()
                runner.unregister_cli_process(room, process)
