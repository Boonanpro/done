"""Screens are told when the core is about to restart and can ask when it is back (2026-10-13). Before this a restart
looked like a broken screen for a minute: lists spinning, a sent message lost."""
import asyncio
import sys
import types
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import chat_routes
from app.services import room_feed

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import restart_dan_core  # noqa: E402


def client(host='127.0.0.1'):
    app = FastAPI()
    app.include_router(chat_routes.router, prefix='/api/v1')
    return TestClient(app, client=(host, 50000))


def test_every_open_screen_is_told_that_the_core_is_about_to_restart():
    async def scenario():
        loop = asyncio.get_running_loop()
        queues = {user: asyncio.Queue() for user in ('owner', 'someone else')}
        for user, queue in queues.items():
            room_feed._subs[user][queue] = loop
        try:
            answer = await asyncio.to_thread(lambda: client().post('/api/v1/chat/internal/restarting').json())
            await asyncio.sleep(0)
            return answer, [queue.get_nowait() for queue in queues.values()]
        finally:
            for user in queues:
                room_feed._subs.pop(user, None)
    answer, events = asyncio.run(scenario())
    assert answer['delivered'] == 2
    assert events == [{'type': 'restarting', 'started': chat_routes._STARTED}] * 2


def test_only_this_computer_can_announce_a_restart():
    assert client('203.0.113.7').post('/api/v1/chat/internal/restarting').status_code == 403


def test_a_screen_can_ask_whether_the_core_and_the_sandbox_answer_without_signing_in(monkeypatch):
    import httpx

    class Sandbox:
        def __init__(self, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): return types.SimpleNamespace(status_code=200)

    class NoSandbox(Sandbox):
        async def get(self, url): raise httpx.ConnectError('nothing listens')

    monkeypatch.setattr(httpx, 'AsyncClient', Sandbox)
    assert client().get('/api/v1/chat/alive').json() == {'core': True, 'sandbox': True, 'started': chat_routes._STARTED}
    monkeypatch.setattr(httpx, 'AsyncClient', NoSandbox)
    assert client().get('/api/v1/chat/alive').json()['sandbox'] is False


def test_the_restart_announces_before_it_stops_anything(monkeypatch):
    order = []
    monkeypatch.setattr(restart_dan_core, 'announce', lambda: order.append('announce'))
    monkeypatch.setattr(restart_dan_core, 'listeners', lambda: order.append('look for the processes') or {})
    monkeypatch.setattr(restart_dan_core.time, 'sleep', lambda s: None)
    assert restart_dan_core.stop() is True
    assert order[0] == 'announce'


def test_a_core_that_cannot_be_told_is_still_stopped(monkeypatch):
    import urllib.request

    def refused(*a, **k):
        raise OSError('connection refused')
    monkeypatch.setattr(urllib.request, 'urlopen', refused)
    restart_dan_core.announce()
