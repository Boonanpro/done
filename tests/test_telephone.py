import asyncio
import base64
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator
from app.services import telephone as T
from app.api.telephone_routes import router


def test_signature_and_expired_grant_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(T, 'ROOT', tmp_path)
    monkeypatch.setattr(T.settings, 'TWILIO_AUTH_TOKEN', 'test-secret')
    key = 'a'*48
    url = T.stream_url(key)
    signature = RequestValidator('test-secret').compute_signature(url, {})
    assert T.signature_ok(url, signature)
    assert not T.signature_ok(url+'other', signature)
    T.save(key, {'expires': time.time()-1})
    app = FastAPI(); app.include_router(router)
    from starlette.websockets import WebSocketDisconnect
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/v1/voice/telephone/stream/'+key, headers={'x-twilio-signature': signature}):
                pytest.fail('Expired grant accepted')


@pytest.mark.asyncio
async def test_input_keeps_arriving_during_speech_and_playback_wait():
    incoming = asyncio.Queue()
    sent = []
    class Phone:
        async def receive_json(self): return await incoming.get()
        async def send_json(self, value): sent.append(value)
    class Live:
        def __init__(self): self.heard = []
        async def send(self, raw): self.heard.append(json.loads(raw))
    bridge = T.Bridge(Phone(), {})
    bridge.stream_id, bridge.live = 'stream', Live()
    for _ in range(12): bridge.output.put_nowait(b'\xff'*160)
    speaker = asyncio.create_task(bridge.to_phone())
    listener = asyncio.create_task(bridge.from_phone())
    try:
        await asyncio.sleep(.3)  # speaker is now waiting for the playback mark
        assert any(row['event'] == 'mark' for row in sent)
        payload = base64.b64encode(b'\x00'*160).decode()
        await incoming.put({'event': 'media', 'media': {'payload': payload}})
        await asyncio.sleep(.02)
        assert bridge.live.heard == [{'type':'session.input_audio.append', 'audio':payload}]
        assert bridge.received == 160
        assert len([x for x in sent if x['event']=='media']) == 10
    finally:
        listener.cancel(); speaker.cancel()
        await asyncio.gather(listener, speaker, return_exceptions=True)


@pytest.mark.asyncio
async def test_other_call_cannot_use_owner_grant():
    bridge = T.Bridge(None, {'call_sid': 'authorized'})
    with pytest.raises(ValueError, match='authorized'):
        await bridge.run({'start': {'callSid': 'another-call'}})


def check_result(result, required):
    heard = ''.join(t['text'] for t in result.get('transcript', []) if t['role']=='user')
    said = ''.join(t['text'] for t in result.get('transcript', []) if t['role']=='assistant')
    return bool(heard and all(word in said for word in required) and result.get('finalized')
        and result.get('provider_ended') and 0 <= result.get('hangup_seconds', 999) < 20 and result.get('input_bytes', 0)>0 and result.get('output_bytes',0)>0)


def test_checker_fails_known_bad_empty_or_unended_call():
    bad = {'transcript':[{'role':'user','text':'切って'},{'role':'assistant','text':'切れたよ。青です。'}],
           'finalized':True,'provider_ended':False,'hangup_seconds':5,'input_bytes':160,'output_bytes':160}
    assert not check_result(bad, ['青'])
    good = dict(bad, provider_ended=True)
    assert check_result(good, ['青'])
    assert not check_result(good, ['赤'])
    assert not check_result(dict(good, hangup_seconds=71.61), ['青'])


@pytest.mark.asyncio
async def test_primary_control_adapter_receives_events_and_sends_on_same_socket():
    class Live:
        async def send(self, raw): self.last = raw
    live = Live()
    control = T.ControlEvents(live)
    await control.events.put('{"type":"session.input_transcript.delta","delta":"切って"}')
    async with control as socket:
        assert json.loads(await socket.recv())['delta'] == '切って'
        await socket.send('{"type":"session.close"}')
    assert json.loads(live.last)['type'] == 'session.close'
