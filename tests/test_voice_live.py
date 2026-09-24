"""The phone voice session: Live 1 with the Responses delegation, the room's history, the local clock, and the per-call
registry (the old answering backend was retired on 2026-09-23)."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import voice_live as live


class LiveSessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        live._sessions.clear()
        self.addCleanup(live._sessions.clear)
        import tempfile
        from pathlib import Path
        from app.services import voice_sideband
        log = patch.object(voice_sideband, 'LOG', Path(tempfile.mkdtemp()) / 'sideband.jsonl')   # not the real call log (the restart guard reads it)
        log.start(); self.addCleanup(log.stop)

    def test_history_order_roles_and_budget(self):
        from app.services.voice_history import room_history
        rows = room_history([
            {'created_at': '2', 'sender_type': 'ai', 'content': '🎙 予約は11Eです。'},
            {'created_at': '1', 'sender_type': 'human', 'content': '窓側を希望'},
        ])
        self.assertEqual([r['role'] for r in rows], ['user', 'assistant'])
        restored = live.session_config(rows)['input'][0]['content'][0]['text']
        self.assertLess(restored.index('窓側を希望'), restored.index('予約は11E'))
        large = room_history([{'created_at': '3', 'sender_type': 'ai', 'content': 'あ'*10000+'末尾の決定'}])
        self.assertIn('末尾の決定', str(large))
        self.assertLess(sum(len(r['content'][0]['text'].encode())+40 for r in large), 7400)

    async def test_session_is_created_with_the_room_history_and_the_server_owns_it(self):
        from app.api import voicelog_routes as routes
        response = MagicMock(status_code=201)
        response.json.return_value = {'session': {'id': 'live-new'}, 'transport': {'sdp': 'answer'}}

        async def post(*args, **kwargs):
            self.assertTrue(any(k.startswith('pending-') for k in live._sessions))   # prepared before the network call
            self.assertIn('14号車', str(kwargs['json']['session']['input']))
            return response
        client = AsyncMock(); client.post.side_effect = post
        client.__aenter__.return_value = client
        with patch.object(routes, '_get_user', return_value=SimpleNamespace(user_id='owner')), \
             patch.object(routes.settings, 'OPENAI_API_KEY', 'test'), \
             patch.object(routes.ChatService, 'get_room', new_callable=AsyncMock, return_value={'id': 'r'}), \
             patch.object(routes.ChatService, 'get_messages', new_callable=AsyncMock, return_value=[{'sender_type': 'ai', 'content': '14号車', 'created_at': '1'}]), \
             patch.object(routes.httpx, 'AsyncClient', return_value=client), \
             patch('app.services.voice_sideband.attach', return_value=True) as attach:
            result = await routes.create_live_session(None, routes.LiveSessionRequest(sdp='offer', room_id='r'))
            self.assertEqual(result['session']['id'], 'live-new')
            self.assertTrue(result['server_delegation'])
            self.assertTrue(attach.call_args.kwargs['own'])
            self.assertIn('live-new', live._sessions)
            self.assertFalse(any(k.startswith('pending-') for k in live._sessions))
            response.status_code = 502
            from fastapi import HTTPException
            with self.assertRaises(HTTPException):
                await routes.create_live_session(None, routes.LiveSessionRequest(sdp='offer', room_id='r'))
            self.assertFalse(any(k.startswith('pending-') for k in live._sessions))

    def test_live_one_with_the_responses_delegation(self):
        config = live.session_config()
        self.assertEqual(config['model'], 'gpt-live-1')
        self.assertEqual(config['delegation']['type'], 'responses')
        tools = config['delegation']['responses']['tools']
        self.assertIn('web_search', [t.get('name') for t in tools])
        self.assertIn('get_saved_information', [t.get('name') for t in tools])
        self.assertIn('本人の承認が必要', config['instructions'])

    def test_local_date_crosses_utc_midnight(self):
        from datetime import datetime, timezone
        instant = datetime(2026, 9, 17, 15, 49, tzinfo=timezone.utc)
        with patch.object(live, 'datetime') as clock:
            clock.now.side_effect = lambda zone: instant.astimezone(zone)
            tokyo = live.session_config(timezone='Asia/Tokyo')['instructions']
            la = live.session_config(timezone='America/Los_Angeles')['instructions']
            fallback = live.session_config(timezone='invalid')['instructions']
        self.assertIn('2026-09-18T00:49:00+09:00（金曜日、Asia/Tokyo）', tokyo)
        self.assertIn('2026-09-17T08:49:00-07:00（木曜日、America/Los_Angeles）', la)
        self.assertEqual(tokyo, fallback)

    def test_registry_belongs_to_its_owner_and_closes(self):
        live.register('s', 'owner', room_id='r')
        self.assertIsNotNone(live.get_session('s', 'owner'))
        self.assertIsNone(live.get_session('s', 'someone-else'))
        with self.assertRaises(ValueError):
            live.close('s', 'someone-else')
        live.close('s', 'owner')
        self.assertIsNone(live.get_session('s', 'owner'))
