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
        large = room_history([{'created_at': '3', 'sender_type': 'ai', 'content': 'あ'*20000+'末尾の決定'}])
        self.assertIn('末尾の決定', str(large))
        self.assertLess(sum(len(r['content'][0]['text'].encode())+40 for r in large), 30000)

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
        with patch.object(routes.ChatService, '__init__', return_value=None), \
             patch('app.services.dan_core.shared', return_value=''), \
             patch('app.services.voice_tools.warm'), \
             patch('app.services.room_files.listing', new_callable=AsyncMock, return_value=[]), \
             patch.object(routes, '_get_user', return_value=SimpleNamespace(user_id='owner')), \
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
        self.assertEqual(config['model'], live.MODEL)
        self.assertEqual(config['delegation']['type'], 'responses')
        tools = config['delegation']['responses']['tools']
        self.assertIn('run_in_background', [t.get('name') for t in tools])   # the plain call's lookups run beside the talk (voice_lookup)
        self.assertIn('get_saved_information', [t.get('name') for t in tools])
        with patch.dict('os.environ', {'DAN_VOICE_BACKGROUND': '0'}):
            self.assertIn('web_search', [t.get('name') for t in live.session_config()['delegation']['responses']['tools']])
        for heading in ('Backchannel policy:', 'Interruption policy:', 'Delegation policy:', 'Generate <|SpawnThinking|> when:'):
            self.assertIn(heading, config['instructions'])   # OpenAI's recommended structure (live-prompting)

    def test_plain_call_has_the_recommended_prompt_and_a_light_backend(self):
        from app.services import voice_plain
        with patch.dict('os.environ', {'DAN_VOICE_PLAIN': '1'}), \
             patch('app.services.dan_core.shared', side_effect=AssertionError('chat brief read')):
            config = live.session_config(room_id='r', user_id='u')
        self.assertTrue(config['instructions'].startswith(voice_plain.instructions()))
        self.assertNotIn('受付', config['instructions'])
        self.assertNotIn('声の裏側としてのきまり', config['delegation']['responses']['instructions'])

    def test_plain_call_says_whose_dan_it_is_and_talks_while_working(self):
        # 2026-11-03 13:35 「自己紹介して」 -> 「落ち着いて、必要なことを手早く手伝うアシスタント」; 29 s silent while working
        from app.services import voice_plain
        with patch.object(voice_plain, 'owner_names', return_value=('本田樹', 'みきさん')):
            text = voice_plain.instructions()
        self.assertTrue(text.startswith('あなたはダン。本田樹さん（呼び名はみきさん）専用の'))
        self.assertIn('チャットでみきさんと話しているダンと同じダン', text)
        self.assertIn('As verified progress arrives, give a short update', text)
        with patch.object(voice_plain, 'owner_names', return_value=('', '')):
            self.assertIn('持ち主専用', voice_plain.instructions())

    def test_plain_backend_is_fast_and_reports_progress(self):
        from app.services import voice_settings, voice_responses
        with patch.dict('os.environ', {'DAN_VOICE_PLAIN': '1'}), patch.object(voice_settings, 'PATH', voice_settings.Path('/nonexistent/voice.json')):
            settings = voice_settings.snapshot()
            with patch.dict('os.environ', {'DAN_VOICE_BACKGROUND': '0'}):
                names = [t.get('name') for t in voice_responses.tools()]
                backend = voice_responses.delegation(settings=settings)['responses']
        self.assertEqual((settings['backend_model'], settings['reasoning']), ('gpt-6-luna', 'low'))
        self.assertIn('share_progress', names); self.assertIn('think_carefully', names)
        self.assertIn('show_page_on_stage の conditions', backend['instructions'])
        with patch.dict('os.environ', {'DAN_VOICE_PLAIN': '0'}), patch.object(voice_settings, 'PATH', voice_settings.Path('/nonexistent/voice.json')):
            self.assertEqual(voice_settings.snapshot()['backend_model'], 'gpt-6.1-terra')
            self.assertNotIn('share_progress', [t.get('name') for t in voice_responses.tools()])

    def test_share_progress_is_said_into_the_call(self):
        import asyncio
        from app.services import voice_responses
        said = []
        async def speak(text): said.append(text)
        out = asyncio.run(voice_responses.run_function('share_progress', {'fact': '100kgのセットが3つ見つかった。在庫を見ている'}, 'u', 'r', [], speak=speak))
        self.assertTrue(out['said'])
        self.assertEqual(said, ['100kgのセットが3つ見つかった。在庫を見ている'])

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
