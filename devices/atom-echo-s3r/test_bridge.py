"""Local protocol/reconnection tests; no Atom, router, or chat access."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from voice_state import HEADER


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        cfg = Path(self.temp.name) / 'pairing.json'
        cfg.write_text(json.dumps({'key': 'a'*32, 'ip': '127.0.0.1'}))
        spec = importlib.util.spec_from_file_location('test_atom_bridge', Path(__file__).with_name('wifi_bridge.py'))
        self.bridge = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {'DAN_ATOM_CONFIG': str(cfg)}):
            spec.loader.exec_module(self.bridge)

    def tearDown(self):
        self.temp.cleanup()

    def test_direct_owner_waits_for_socket_release_and_blocks_old_clients(self):
        b = self.bridge
        async def idle(): await asyncio.Event().wait()
        class Writer:
            closed = False
            released = False
            def close(self): self.closed = True
            async def wait_closed(self):
                await asyncio.sleep(.01)
                self.released = True
        writer = Writer()
        b.writer = writer
        with patch.object(b, 'device_loop', idle), TestClient(b.app) as client:
            response = client.post('/control', json={'key':'a'*32, 'action':'audio_owner', 'mode':'phone'})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(writer.closed and writer.released)
            self.assertEqual(client.get('/status').json()['audio_owner'], 'phone')
            self.assertEqual(client.post('/control', json={'key':'a'*32, 'action':'start'}).status_code, 409)
            with client.websocket_connect('/device-relay') as phone:
                phone.send_json({'key':'a'*32})
                with self.assertRaises(WebSocketDisconnect): phone.receive_json()
            self.assertIsNone(b.relay)

    def test_direct_owner_never_claims_success_if_release_fails(self):
        b = self.bridge
        async def idle(): await asyncio.Event().wait()
        class Writer:
            def close(self): pass
            async def wait_closed(self): raise OSError('release failed')
        b.writer = Writer()
        with patch.object(b, 'device_loop', idle), TestClient(b.app) as client:
            response = client.post('/control', json={'key':'a'*32, 'action':'audio_owner', 'mode':'phone'})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(b.audio_owner.mode, 'phone')  # PC must not reconnect after a failed release.

    def test_direct_owner_keeps_active_call_untouched(self):
        b = self.bridge
        async def idle(): await asyncio.Event().wait()
        b.gate.requested = True
        with patch.object(b, 'device_loop', idle), TestClient(b.app) as client:
            response = client.post('/control', json={'key':'a'*32, 'action':'audio_owner', 'mode':'phone'})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(b.audio_owner.mode, 'pc')
            self.assertTrue(b.gate.requested)

    def test_phone_relay_requires_key_and_exclusive_lease(self):
        b=self.bridge
        async def idle(): await asyncio.Event().wait()
        with patch.object(b,'device_loop',idle),TestClient(b.app) as client:
            with client.websocket_connect('/device-relay') as bad:
                bad.send_json({'key':'b'*32})
                with self.assertRaises(WebSocketDisconnect):bad.receive_json()
            self.assertIsNone(b.relay)
            with client.websocket_connect('/device-relay') as phone:
                phone.send_json({'key':'a'*32});self.assertEqual(phone.receive_json()['type'],'ready')
                owner=b.relay
                with client.websocket_connect('/device-relay') as duplicate:
                    duplicate.send_json({'key':'a'*32})
                    with self.assertRaises(WebSocketDisconnect):duplicate.receive_json()
                self.assertIs(b.relay,owner)
                phone.send_bytes(bytes(10))
                with self.assertRaises(WebSocketDisconnect):phone.receive_bytes()
            self.assertIsNone(b.relay)

    def test_phone_connection_without_device_audio_never_revives_old_call(self):
        b=self.bridge
        async def probe():
            b.gate.requested=True  # stale intent from a powered-off device
            b.relay=object()
            task=asyncio.create_task(b.device_loop())
            try:
                await asyncio.sleep(.05)
                self.assertFalse(b.status['device_connected'])
                self.assertFalse(b.gate.connected)
                self.assertFalse(b.gate.ready)
            finally:
                task.cancel();await asyncio.gather(task,return_exceptions=True)
        asyncio.run(probe())

    def test_room_auth_and_interruption(self):
        b = self.bridge
        async def idle():
            await asyncio.Event().wait()
        with patch.object(b, 'device_loop', idle), TestClient(b.app) as client:
            for auth in [{'key': 'b'*32, 'roomId': b.ROOM}, {'key': 'a'*32, 'roomId': 'other-room'}]:
                with self.assertRaises(WebSocketDisconnect) as error:
                    with client.websocket_connect('/audio', headers={'origin': 'http://localhost:3002'}) as ws:
                        ws.send_json(auth)
                        ws.receive_json()
                self.assertEqual(error.exception.code, 1008)
                self.assertFalse(b.status['browser_connected'])
            b.status['device_connected'] = True
            with client.websocket_connect('/audio', headers={'origin': 'http://localhost:3002'}) as ws:
                ws.send_json({'key': 'a'*32, 'roomId': b.ROOM})
                self.assertTrue(ws.receive_json()['deviceConnected'])
                for _ in range(12):
                    ws.send_bytes(bytes(960))
                ws.send_json({'type': 'flush'})
                # Invalid size closes only after the queued messages were processed.
                ws.send_bytes(bytes(2))
                with self.assertRaises(WebSocketDisconnect):
                    ws.receive_bytes()
                self.assertEqual(b.status['interruptions'], 1)
                self.assertTrue(b.pending.empty())

    def test_stuck_socket_close_does_not_block_reconnect(self):
        b = self.bridge
        class Writer:
            def __init__(self): self.transport = self; self.aborted = False
            def write(self, data): pass
            async def drain(self): pass
            def close(self): pass
            async def wait_closed(self): await asyncio.Event().wait()
            def abort(self): self.aborted = True
        class Reader:
            async def readexactly(self, n): raise ConnectionResetError()
        async def test():
            w = Writer(); retried = asyncio.Event(); attempts = 0
            async def connect(*args, **kwargs):
                nonlocal attempts
                attempts += 1
                if attempts == 1: return Reader(), w
                retried.set()
                await asyncio.Event().wait()
            with patch.object(b.asyncio, 'open_connection', connect):
                task = asyncio.create_task(b.device_loop())
                try:
                    await asyncio.wait_for(retried.wait(), 4)
                    self.assertTrue(w.aborted)
                finally:
                    task.cancel()
                    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 2)
        asyncio.run(test())

    def test_protocol_sends_silence_until_ready_and_immediately_on_off(self):
        b = self.bridge
        async def test():
            incoming, returned = asyncio.Queue(), asyncio.Queue()
            class Reader:
                async def readexactly(self, n):
                    data = await incoming.get()
                    assert len(data) == n
                    return data
            class Writer:
                def __init__(self): self.frames = []
                def write(self, data): self.frames.append(data)
                async def drain(self): pass
                def close(self): pass
                async def wait_closed(self): pass
            class Browser:
                async def send_bytes(self, data): await returned.put(data)
            writer = Writer()
            async def connect(*args, **kwargs): return Reader(), writer
            b.browser = Browser()
            async def frame(flags, revision):
                incoming.put_nowait(HEADER.pack(flags, 123, revision) + b'\x10\x00'*480)
                return await asyncio.wait_for(returned.get(), 2)
            with patch.object(b.asyncio, 'open_connection', connect):
                incoming.put_nowait(b'OKF4')
                task = asyncio.create_task(b.device_loop())
                try:
                    self.assertEqual(await frame(0, 0), bytes(960))
                    self.assertEqual(writer.frames[0], b'DAN4'+b'a'*32)
                    self.assertEqual(await frame(1, 1), bytes(960))
                    b.gate.lease(123, 1, True)
                    b.pending.put_nowait(b'\x20\x00'*480)
                    await frame(1, 1)
                    self.assertEqual(HEADER.unpack(writer.frames[-1][:12]), (1, 123, 1))
                    self.assertEqual(writer.frames[-1][12:], b'\x20\x00'*480)
                    b.gate.control(False)
                    b.pending.put_nowait(b'\x20\x00'*480)
                    self.assertEqual(await frame(1, 1), bytes(960))
                    self.assertEqual(HEADER.unpack(writer.frames[-1][:12]), (2, 123, 1))
                    self.assertEqual(writer.frames[-1][12:], bytes(960))
                    self.assertTrue(b.pending.empty())
                    self.assertEqual(await frame(0, 2), bytes(960))
                    class Wake:
                        def reset(self, *args): pass
                        def feed(self, pcm, intent): self.pcm=pcm
                    b.wake=Wake();b.gate.wake_enabled=True
                    self.assertEqual(await frame(0, 2), bytes(960))
                    self.assertEqual(b.wake.pcm, b'\x10\x00'*480)
                    self.assertEqual(HEADER.unpack(writer.frames[-1][:12]), (8,123,2))
                    self.assertEqual(writer.frames[-1][12:], bytes(960))
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        asyncio.run(test())

    def test_control_auth_and_stale_session_rejected(self):
        b = self.bridge
        async def idle(): await asyncio.Event().wait()
        with patch.object(b, 'device_loop', idle), TestClient(b.app) as client:
            self.assertEqual(client.post('/control', json={'action':'stop'}).status_code, 403)
            b.gate.receive(HEADER.pack(1, 123, 1))
            self.assertEqual(client.post('/control', json={'key':'a'*32, 'action':'session', 'boot':123, 'revision':0, 'active':True}).status_code, 409)
            self.assertEqual(client.post('/control', json={'key':'a'*32, 'action':'stop'}).status_code, 200)
            self.assertFalse(b.gate.wanted)


if __name__ == '__main__': unittest.main()
