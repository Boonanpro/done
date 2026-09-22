"""Pairing boundary tests; never reads a real browser profile or starts voice."""
import asyncio
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


class HeadlessTests(unittest.TestCase):
    def test_off_cancels_stalled_startup(self):
        spec = importlib.util.spec_from_file_location('test_headless_startup', Path(__file__).with_name('headless_voice.py'))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        async def test():
            class Worker:
                cancelled = False
                async def goto(self, *args, **kwargs):
                    try:await asyncio.Event().wait()
                    finally:self.cancelled=True
            worker=Worker()
            with patch.object(m, 'device_status', new_callable=AsyncMock, return_value={'device_connected':True,'requested':False,'boot':123,'revision':2}):
                self.assertFalse(await asyncio.wait_for(m.load_worker(worker,(123,1)),1))
                self.assertTrue(worker.cancelled)
        asyncio.run(test())

    def test_pairing_requires_device_key_origin_and_room_access(self):
        spec = importlib.util.spec_from_file_location('test_headless_module', Path(__file__).with_name('headless_voice.py'))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        async def idle(): await asyncio.Event().wait()
        with tempfile.TemporaryDirectory() as tmp:
            m.PAIR = Path(tmp) / 'pair.json'
            m.AUTH = Path(tmp) / 'auth.json'
            m.VOICE_CONFIG = Path(tmp) / 'provider.json'
            m.PAIR.write_text(json.dumps({'key': 'a'*32}))
            with patch.object(m, 'browser_loop', idle), TestClient(m.app) as client:
                body = {'key': 'a'*32, 'token': 'test-session-token'}
                self.assertEqual(client.post('/pair', json={**body, 'key': 'b'*32}).status_code, 403)
                self.assertEqual(client.post('/pair', json=body, headers={'origin': 'https://unrelated.example'}).status_code, 403)
                with patch.object(m, 'device_command', new_callable=AsyncMock) as device, patch.object(m.httpx, 'AsyncClient') as http:
                    get = http.return_value.__aenter__.return_value.get = AsyncMock()
                    get.return_value.status_code = 401
                    self.assertEqual(client.post('/pair', json=body).status_code, 401)
                    self.assertFalse(m.AUTH.exists())
                    get.return_value.status_code = 200
                    self.assertEqual(client.post('/pair', json=body).status_code, 200)
                    self.assertEqual(json.loads(m.AUTH.read_text())['token'], body['token'])
                    device.assert_awaited_once_with('start')
                    self.assertIn(m.ROOM, get.call_args.args[0])
                self.assertNotIn('token', client.get('/status').text)
                with patch.object(m, 'device_status', new_callable=AsyncMock, return_value={'requested':True}):
                    self.assertEqual(client.post('/command', json={'key':'a'*32,'action':'provider','provider':'gemini'}).status_code,409)
                    self.assertFalse(m.VOICE_CONFIG.exists())
                with patch.object(m, 'device_status', new_callable=AsyncMock, return_value={'requested':False}):
                    self.assertEqual(client.post('/command', json={'key':'a'*32,'action':'provider','provider':'gemini'}).status_code,200)
                    self.assertEqual(json.loads(m.VOICE_CONFIG.read_text())['provider'],'gemini')
                self.assertEqual(client.post('/command', json={'key': 'a'*32, 'action': 'say', 'text': 'test'}).status_code, 409)
                with patch.object(m, 'device_command', new_callable=AsyncMock) as device:
                    self.assertEqual(client.post('/command', json={'key': 'a'*32, 'action': 'stop'}).status_code, 200)
                    device.assert_awaited_once_with('stop')
                    device.reset_mock()
                    self.assertEqual(client.post('/command', json={'key': 'a'*32, 'action': 'reconnect'}).status_code, 200)
                    device.assert_not_awaited()


if __name__ == '__main__': unittest.main()
