import asyncio
from types import SimpleNamespace

import httpx
import pytest
from starlette.requests import Request, ClientDisconnect

from app.core import gateway


@pytest.mark.asyncio
@pytest.mark.parametrize('disconnect_at', ['start', 'body'])
async def test_disconnect_always_closes_upstream_and_releases_slot(monkeypatch, disconnect_at):
    class Stream(httpx.AsyncByteStream):
        closed = False
        async def __aiter__(self):
            yield b'data: ready\n\n'
            await asyncio.Event().wait()
        async def aclose(self):
            await asyncio.sleep(0)
            self.closed = True
    stream = Stream()
    entered, left = [], []
    monkeypatch.setattr(gateway, 'destination', lambda *a: 9201)
    monkeypatch.setattr(gateway.retirement, 'enter', entered.append)
    monkeypatch.setattr(gateway.retirement, 'leave', left.append)
    async def handler(request):
        return httpx.Response(200, stream=stream)
    async with gateway.upstream_client(transport=httpx.MockTransport(handler)) as upstream:
        app = SimpleNamespace(state=SimpleNamespace(client=upstream))
        scope = {'type':'http','method':'GET','path':'/events','query_string':b'',
                 'headers':[], 'server':('localhost',9100),'app':app,'asgi':{'spec_version':'2.0'}}
        async def empty_body():
            return {'type':'http.request','body':b'','more_body':False}
        request = Request(scope,empty_body)
        response = await gateway.proxy(request, 'events')
        disconnect = asyncio.Event()
        async def receive():
            await disconnect.wait()
            return {'type':'http.disconnect'}
        async def send(message):
            if message['type'] == ('http.response.start' if disconnect_at=='start' else 'http.response.body'):
                disconnect.set()
                await asyncio.Event().wait()
        await asyncio.wait_for(response(scope, receive, send), 1)
        assert stream.closed
        assert entered == left == [9201]


@pytest.mark.asyncio
async def test_body_disconnect_releases_routing_reference(monkeypatch):
    entered,left=[],[]
    monkeypatch.setattr(gateway, 'destination', lambda *a: 9201)
    monkeypatch.setattr(gateway.retirement, 'enter', entered.append)
    monkeypatch.setattr(gateway.retirement, 'leave', left.append)
    async def handler(request):
        raise ClientDisconnect()
    async with gateway.upstream_client(transport=httpx.MockTransport(handler)) as upstream:
        app=SimpleNamespace(state=SimpleNamespace(client=upstream))
        scope={'type':'http','method':'POST','path':'/upload','query_string':b'',
               'headers':[], 'server':('localhost',9100),'app':app}
        async def empty_body():
            return {'type':'http.request','body':b'','more_body':False}
        with pytest.raises(ClientDisconnect):
            await gateway.proxy(Request(scope,empty_body),'upload')
    assert entered == left == [9201]


@pytest.mark.asyncio
async def test_full_notification_pool_cannot_block_normal_requests(monkeypatch):
    feed_connected=asyncio.Event()
    async def backend(reader,writer):
        try:
            headers=await reader.readuntil(b'\r\n\r\n')
            if b'GET /api/v1/chat/feed ' in headers:
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\ndata: ready\n\n')
                await writer.drain();feed_connected.set()
                await reader.read()
            else:
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK')
                await writer.drain()
        finally:
            writer.close();await writer.wait_closed()
    server=await asyncio.start_server(backend,'127.0.0.1',0)
    port=server.sockets[0].getsockname()[1]
    monkeypatch.setattr(gateway,'destination',lambda *a:port)
    monkeypatch.setattr(gateway.retirement,'start',lambda:(lambda:None,lambda:None))
    original=gateway.upstream_client
    monkeypatch.setattr(gateway,'upstream_client',lambda **kw:original(limits=httpx.Limits(max_connections=1),**kw))
    try:
        async with gateway.lifespan(gateway.app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),base_url='http://localhost:9100') as client:
                feed=asyncio.create_task(client.get('/api/v1/chat/feed'))
                try:
                    await asyncio.wait_for(feed_connected.wait(),2)
                    result=await asyncio.wait_for(client.get('/health'),.5)
                    assert result.status_code==200 and result.text=='OK'
                finally:
                    feed.cancel();await asyncio.gather(feed,return_exceptions=True)
    finally:
        server.close();await server.wait_closed()


def test_pool_wait_is_bounded_but_model_streams_can_stay_open():
    client=gateway.upstream_client()
    assert client.timeout.pool is not None and client.timeout.pool<=10
    assert client.timeout.read is None
