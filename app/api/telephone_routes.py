"""Signed Twilio streams for locally authorized outbound calls."""
import asyncio
import os
import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services import telephone as T

router = APIRouter(prefix='/api/v1/voice/telephone', tags=['telephone'])


@router.get('/ready')
async def ready():
    return {'version': T.VERSION}


@router.websocket('/stream/{key}')
async def stream(socket: WebSocket, key: str):
    try:
        grant = T.read(key)
        if time.time() > grant['expires'] or not T.signature_ok(T.stream_url(key), socket.headers.get('x-twilio-signature', '')):
            raise ValueError('Unauthorized stream')
        # One use, across concurrent requests and release processes.
        lock = T.path(key).with_suffix('.claimed')
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except (ValueError, KeyError, OSError):
        await socket.close(code=1008)
        return
    await socket.accept()
    bridge = T.Bridge(socket, grant)
    result = {'stream_connected': True}
    try:
        async def read_start():
            while True:
                start = await socket.receive_json()
                if start.get('event') == 'start':
                    return start
                if start.get('event') != 'connected':
                    raise ValueError('Expected stream start')
        start = await asyncio.wait_for(read_start(), 10)
        # The stream can beat the REST call's response; wait for the authorized
        # CallSid to be saved, never trust the provider-supplied ID as a grant.
        for _ in range(30):
            grant = T.read(key)
            if grant.get('call_sid'):
                break
            await asyncio.sleep(.1)
        bridge.grant = grant
        await bridge.run(start)
    except WebSocketDisconnect:
        result['disconnect'] = True
    except Exception as exc:
        result['error_type'] = type(exc).__name__
    finally:
        result.update(session_id=bridge.session_id, finalized=bridge.finalized,
            input_bytes=bridge.received, output_bytes=bridge.sent, transcript=bridge.transcript,
            ended_at=time.time())
        latest = T.read(key)
        latest['result'] = result
        T.save(key, latest)
        try:
            await socket.close()
        except RuntimeError:
            pass
