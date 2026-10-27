"""Small stable HTTP/WebSocket entrance. In-flight streams keep their target.

Ports 9100 (Core) and 8100 (Sandbox) allow installation beside legacy Dan without
terminating its calls, jobs or browser. Internal browser/event service remains at
9000; release workers never run the shared pollers or own browser processes.
"""
import asyncio
import json
import re
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, WebSocket
from starlette.responses import StreamingResponse, JSONResponse
from app.core import generations as G

HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade', 'host'}
SERVICE_PATHS = ('/internal/', '/api/v1/chat/internal/', '/api/v1/chat/feed')


@asynccontextmanager
async def lifespan(app):
    async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10), trust_env=False) as client:
        app.state.client = client
        yield


app = FastAPI(lifespan=lifespan)


def destination(scope, path, payload=None):
    role = 'sandbox' if scope['server'][1] == 8100 else 'core'
    if role == 'core' and any(path.startswith(p) for p in SERVICE_PATHS):
        return 9000
    payload = payload if isinstance(payload, dict) else {}
    room = payload.get('room_id') or payload.get('session_id')
    match = re.search(r'/dan/sessions/([^/]+)', path)
    if match: room = match.group(1)
    session = payload.get('session_id') if '/live/backend/' in path else None
    if '/stage/' in path:
        room = path.rsplit('/', 1)[-1]
    if session and not G.owner('call', session):
        # Sessions established before the gateway still belong to legacy 8000.
        return 8000
    return G.target(role, room, session)


@app.api_route('/{path:path}', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD'])
async def proxy(request: Request, path: str):
    path = '/' + path
    if path == '/_gateway/health':
        return {'ready': True, 'active': G.read('active')}
    body = None
    payload = dict(request.query_params)
    # Only small conversation/control JSON needs affinity. File uploads stream.
    if request.method == 'POST' and (path.startswith('/api/v1/chat/dan/') or '/live/' in path):
        body = await request.body()
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            pass
    room = (payload or {}).get('session_id') or (payload or {}).get('room_id')
    match = re.search(r'/dan/sessions/([^/]+)', path)
    if match: room = match.group(1)
    reservation = None
    legacy = await asyncio.to_thread(G.legacy_room_alive, room) if '/chat/dan/' in path else False
    if not legacy and path == '/api/v1/chat/dan/messages/stream':
        reservation = await asyncio.to_thread(G.reserve_room, room)
    port = 9000 if legacy else (reservation[0]['core'] if reservation else destination(request.scope, path, payload))
    url = f'http://127.0.0.1:{port}{path}'
    if request.url.query:
        url += '?' + request.url.query
    headers = [(k, v) for k, v in request.headers.items() if k.lower() not in HOP]
    client = request.app.state.client
    req = client.build_request(request.method, url, headers=headers,
                               content=body if body is not None else request.stream())
    try:
        response = await client.send(req, stream=True)
    except httpx.HTTPError:
        if reservation: G.release_room(room, reservation[1])
        # Never retry a write: the destination may have accepted it.
        return JSONResponse({'detail': '接続先に応答がありません。操作の受付状況を確認してください。'}, status_code=502)
    async def contents():
        try:
            async for chunk in response.aiter_raw():
                yield chunk
        finally:
            await response.aclose()
            if reservation: G.release_room(room, reservation[1])
    result = StreamingResponse(contents(), status_code=response.status_code)
    result.raw_headers = [(k, v) for k, v in response.headers.raw if k.decode().lower() not in HOP]
    return result


@app.websocket('/{path:path}')
async def websocket_proxy(socket: WebSocket, path: str):
    import websockets
    port = destination(socket.scope, '/' + path)
    suffix = ('?' + socket.url.query) if socket.url.query else ''
    headers = [(k, v) for k, v in socket.headers.items()
               if k.lower() not in HOP and not k.lower().startswith('sec-websocket-')]
    try:
        async with websockets.connect(f'ws://127.0.0.1:{port}/{path}{suffix}', additional_headers=headers,
                                       subprotocols=socket.scope.get('subprotocols') or None, max_size=None, proxy=None) as upstream:
            await socket.accept(subprotocol=upstream.subprotocol)
            async def to_upstream():
                while True:
                    item = await socket.receive()
                    if item['type'] == 'websocket.disconnect':
                        return
                    await upstream.send(item.get('text') if item.get('text') is not None else item['bytes'])
            async def to_client():
                async for item in upstream:
                    if isinstance(item, bytes): await socket.send_bytes(item)
                    else: await socket.send_text(item)
            tasks = [asyncio.create_task(to_upstream()), asyncio.create_task(to_client())]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks: task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    except Exception:
        if socket.application_state.name != 'DISCONNECTED':
            await socket.close(code=1011)
