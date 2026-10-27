import os
import pytest
from app.core import generations as G, gateway


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr(G, 'ROOT', tmp_path)
    monkeypatch.setenv('DAN_GENERATION', 'old')
    old = {'id': 'old', 'core': 9201, 'sandbox': 8201, 'owner': G.identity()}
    new = {'id': 'new', 'core': 9202, 'sandbox': 8202, 'owner': G.identity()}
    G.write('release-old', old); G.write('release-new', new)
    G.write('active', old)
    return old, new


def test_update_preserves_call_and_turn_but_new_room_uses_new_release(registry):
    old, new = registry
    G.track('room', 'ongoing')
    G.track('call', 'call-1')
    G.write('active', new)
    assert G.target('core', 'ongoing') == old['core']
    assert G.target('sandbox', session_id='call-1') == old['sandbox']
    assert G.target('core', 'new-room') == new['core']
    G.track('room', 'ongoing', False)
    assert G.target('core', 'ongoing') == new['core']


def test_close_pending_call_does_not_remove_live_room_owner(registry):
    from app.services import voice_live as v
    v.register('pending-one', 'u', 'room')
    v.register('call-one', 'u', 'room')
    v._drop('pending-one')
    assert G.owner('voice-room', 'room')['id'] == 'old'
    v._drop('call-one')
    assert G.owner('voice-room', 'room') is None


def test_gateway_routes_cancel_and_stage_to_original_owner(registry):
    old, new = registry
    G.track('room', 'r'); G.track('voice-room', 'v'); G.track('call', 'c')
    G.write('active', new)
    assert gateway.destination({'server': ('localhost', 9100)}, '/api/v1/chat/dan/cancel', {'session_id': 'r'}) == old['core']
    assert gateway.destination({'server': ('localhost', 8100)}, '/api/v1/voicelog/stage/v') == old['sandbox']
    assert gateway.destination({'server': ('localhost', 8100)}, '/api/v1/voicelog/live/backend/close', {'session_id': 'c'}) == old['sandbox']
    assert gateway.destination({'server': ('localhost', 9100)}, '/api/v1/chat/feed') == 9000


def test_dead_process_identity_cannot_hold_room(registry, monkeypatch):
    old, new = registry
    G.track('room', 'r')
    saved = G.read(G.key('room', 'r')); saved['owner']['created'] -= 1
    G.write(G.key('room', 'r'), saved); G.write('active', new)
    assert G.target('core', 'r') == new['core']


def test_failed_candidate_does_not_change_active(registry, monkeypatch):
    from scripts import core_release as release
    old, new = registry
    monkeypatch.setattr(release, 'healthy', lambda _: False)
    with pytest.raises(RuntimeError): release.activate('new')
    assert G.read('active') == old


def test_activation_checks_both_servers_and_keeps_rollback(registry, monkeypatch):
    from scripts import core_release as release
    old, new = registry
    seen = []
    monkeypatch.setattr(release, 'healthy', lambda p: seen.append(p) or True)
    release.activate('new')
    assert seen == [new['core'], new['sandbox']]
    assert G.read('previous') == old
    assert G.read('active') == new


def test_reservation_closes_gap_before_run_creation(registry, monkeypatch):
    old, new = registry
    selected, token = G.reserve_room('r')
    G.write('active', new)
    assert G.reserve_room('r')[0] == old
    G.run_changed({'id': 'run-1', 'room_id': 'r', 'state': 'running', 'metadata': {'process_owner': G.identity()}})
    G.release_room('r', token)
    assert G.target('core', 'r') == old['core']
    G.run_changed({'id': 'run-1', 'room_id': 'r', 'state': 'completed', 'metadata': {'process_owner': G.identity()}})
    assert G.target('core', 'r') == new['core']


def test_old_turn_finishing_cannot_release_newer_turn(registry):
    G.run_changed({'id': 'new-run', 'room_id': 'r', 'state': 'running', 'metadata': {'process_owner': G.identity()}})
    G.run_changed({'id': 'old-run', 'room_id': 'r', 'state': 'completed', 'metadata': {'process_owner': G.identity()}})
    assert G.read(G.key('room', 'r'))['run_id'] == 'new-run'


@pytest.mark.asyncio
async def test_proxy_preserves_status_cookies_body_and_never_retries_write(registry, monkeypatch):
    import httpx
    seen = []
    class Bytes(httpx.AsyncByteStream):
        async def __aiter__(self): yield b'reply'
    async def handler(request):
        seen.append((request.url.port, await request.aread()))
        return httpx.Response(201, headers=[('set-cookie', 'a=1'), ('set-cookie', 'b=2')], stream=Bytes())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        gateway.app.state.client = upstream
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url='http://localhost:9100') as client:
            response = await client.post('/some-write', content=b'input')
            assert response.content == b'reply' and response.status_code == 201
            assert response.headers.get_list('set-cookie') == ['a=1', 'b=2']
            assert seen == [(9201, b'input')]
    async def refused(request):
        seen.append('failed')
        raise httpx.ReadError('connection lost after write')
    async with httpx.AsyncClient(transport=httpx.MockTransport(refused)) as upstream:
        gateway.app.state.client = upstream
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url='http://localhost:9100') as client:
            assert (await client.post('/some-write')).status_code == 502
    assert seen.count('failed') == 1


def test_retirement_waits_for_call_and_open_response(registry, monkeypatch):
    from app.core import generation_retirement as retirement
    old, new = registry
    old = {**old, 'draining': True}
    G.write('release-old', old); G.write('active', new)
    killed = []
    monkeypatch.setattr(retirement, 'quiescent', lambda _: True)
    import psutil
    monkeypatch.setattr(psutil.Process, 'terminate', lambda self: killed.append(self.pid))
    G.track('call', 'c')
    retirement.retire_once()
    assert killed == []
    G.track('call', 'c', False)
    retirement.enter(old['core'])
    try:
        retirement.retire_once()
        assert killed == []
    finally: retirement.leave(old['core'])
    retirement.retire_once()
    assert killed == [os.getpid()]
    assert G.read('release-old')['retired']
    retirement.retire_once()
    assert len(killed) == 1


@pytest.mark.asyncio
async def test_exit_notification_without_waiting_for_other_work():
    import asyncio, sys
    import psutil
    from app.core.generation_supervisor import exited
    process = await asyncio.create_subprocess_exec(sys.executable, '-c', 'import time; time.sleep(.1)')
    identity = {'pid': process.pid, 'created': psutil.Process(process.pid).create_time()}
    await asyncio.wait_for(exited(identity), timeout=3)
    await process.wait()
