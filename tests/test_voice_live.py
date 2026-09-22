import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services import voice_live as live
from types import SimpleNamespace
import httpx


class LiveBackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        directory=TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store=patch.object(live.session_store,'DB',Path(directory.name)/'voice.sqlite3')
        store.start();self.addCleanup(store.stop)
        live._sessions.clear()
        live.register('s', 'owner', 'role', [])
        self.addCleanup(live._sessions.clear)

    async def test_stream_ownership_and_order(self):
        async def respond(*args, on_text):
            on_text('結果。')
            return {'output':[]}
        with patch.object(live._sessions['s']['agent'],'respond',side_effect=respond) as call:
            with self.assertRaises(ValueError):
                _ = [e async for e in live.stream_response('s','foreign',[])]
            call.assert_not_called()
            events=[e async for e in live.stream_response('s','owner',[])]
        self.assertEqual([e['type'] for e in events],['text_delta','completed'])

    async def test_timeout_reports_failure_and_closes_stalled_reader(self):
        import asyncio
        agent=live._sessions['s']['agent']
        async def stalled(*args,**kwargs):await asyncio.Event().wait()
        with patch.object(live,'BACKEND_TIMEOUT',.02), patch.object(agent,'respond',side_effect=stalled), patch.object(agent,'close') as close:
            events=[event async for event in live.stream_response('s','owner',[])]
        self.assertEqual(events[0]['type'],'error')
        self.assertIn('確認処理を中断',events[0]['message'])
        close.assert_called_once()

    async def test_unexpected_failure_is_not_silent_eof(self):
        with patch.object(live._sessions['s']['agent'],'respond',side_effect=KeyError('private detail')):
            events=[event async for event in live.stream_response('s','owner',[])]
        self.assertEqual(events[0]['type'],'error')
        self.assertNotIn('private detail',events[0]['message'])

    async def test_disconnected_stream_closes_worker_without_replay(self):
        import asyncio
        agent=live._sessions['s']['agent']
        async def respond(*args,on_text):
            on_text('途中。')
            await asyncio.Event().wait()
        with patch.object(agent,'respond',side_effect=respond) as call, patch.object(agent,'close') as close:
            stream=live.stream_response('s','owner',[])
            self.assertEqual((await anext(stream))['type'],'text_delta')
            await stream.aclose()
            close.assert_called_once()
            self.assertEqual(call.call_count,1)

    async def test_foreign_session_rejected_before_api_call(self):
        with patch.object(live._sessions['s']['agent'], 'respond', new_callable=AsyncMock) as client:
            with self.assertRaises(ValueError):
                await live.respond('s', 'foreign', [{'text': 'read'}], 'key')
            client.assert_not_called()

    async def test_large_history_preserved_and_continuation_bound_to_owner(self):
        data = [{'type': 'function_call_output', 'call_id': 'c', 'output': 'a' * 40000}]
        agent=live._sessions['s']['agent']
        with patch.object(agent,'respond',new_callable=AsyncMock,return_value={'output':[]}) as call:
            await live.respond('s', 'owner', data, 'key')
            self.assertEqual(call.call_args.args[0],data)
            await live.respond('s', 'owner', [{'text': 'next'}], 'key')
            self.assertIs(live._sessions['s']['agent'],agent)
            self.assertEqual(call.call_count,2)

    async def test_reconnect_seeds_each_agent_once(self):
        history = [{'role': 'assistant', 'content': '予約は14号車11E。取消していません。'}]
        for session in ('first', 'reconnected'):
            live.register(session, 'owner', 'role', [], history)
            agent = live._sessions[session]['agent']
            with patch.object(agent, 'respond', new_callable=AsyncMock, return_value={'output': []}) as call:
                await live.respond(session, 'owner', [{'role':'user','content':'さっきの予約は？'}])
                self.assertIn('14号車11E', str(call.call_args.args[0]))
                await live.respond(session, 'owner', [{'role':'user','content':'続き'}])
                self.assertNotIn('14号車11E', str(call.call_args.args[0]))
            live.close(session, 'owner')

    def test_history_order_roles_and_budget(self):
        from app.services.voice_history import room_history
        rows = room_history([
            {'created_at':'2','sender_type':'ai','content':'🎙 予約は11Eです。'},
            {'created_at':'1','sender_type':'human','content':'窓側を希望'},
        ])
        self.assertEqual([r['role'] for r in rows], ['user','assistant'])
        restored=live.session_config('', [], rows)['input'][0]['content'][0]['text']
        self.assertLess(restored.index('窓側を希望'),restored.index('予約は11E'))
        large = room_history([{'created_at':'3','sender_type':'ai','content':'あ'*10000+'末尾の決定'}])
        self.assertIn('末尾の決定', str(large))
        self.assertLess(sum(len(r['content'][0]['text'].encode())+40 for r in large), 7400)

    async def test_session_restores_history_and_prepares_before_network(self):
        from app.api import voicelog_routes as routes
        from app.services.project_service import ProjectService
        response=MagicMock(status_code=201)
        response.json.return_value={'session':{'id':'live-new'},'transport':{'sdp':'answer'}}
        async def post(*args, **kwargs):
            self.assertTrue(any(k.startswith('pending-') for k in live._sessions))
            self.assertIn('14号車', str(kwargs['json']['session']['input']))
            return response
        client=AsyncMock();client.post.side_effect=post
        client.__aenter__.return_value=client
        with patch.object(routes,'_get_user',return_value=SimpleNamespace(user_id='owner')), \
             patch.object(routes.settings,'OPENAI_API_KEY','test'), \
             patch.object(routes.ChatService,'get_room',new_callable=AsyncMock,return_value={'id':'r'}), \
             patch.object(routes.ChatService,'get_messages',new_callable=AsyncMock,return_value=[{'sender_type':'ai','content':'14号車','created_at':'1'}]), \
             patch.object(ProjectService,'get_project_by_room_id',new_callable=AsyncMock,return_value=None), \
             patch.object(routes.httpx,'AsyncClient',return_value=client), patch.object(live,'warm'):
            result=await routes.create_live_session(None,routes.LiveSessionRequest(sdp='offer',room_id='r'))
            self.assertEqual(result['session']['id'],'live-new')
            self.assertIn('14号車',str(live._sessions['live-new']['history']))
            self.assertFalse(any(k.startswith('pending-') for k in live._sessions))
            response.status_code=502
            from fastapi import HTTPException
            with self.assertRaises(HTTPException):
                await routes.create_live_session(None,routes.LiveSessionRequest(sdp='offer',room_id='r'))
            self.assertFalse(any(k.startswith('pending-') for k in live._sessions))

    def test_live_frontend_is_live_one_with_short_separate_instructions(self):
        config = live.session_config('long backend procedures', [{'name': 'read'}])
        self.assertEqual(config['model'], 'gpt-live-1')
        # 2026-09-22: the speech model hands the turn to a backend model that holds Dan's tools (responses delegation);
        # DAN_VOICE_DELEGATION=client restores the previous form.
        self.assertEqual(config['delegation']['type'], 'responses')
        self.assertIn('web_search', [t['type'] for t in config['delegation']['responses']['tools']])
        self.assertIn('get_saved_information', [t.get('name') for t in config['delegation']['responses']['tools']])
        self.assertNotIn('long backend procedures', config['instructions'])
        self.assertIn('本人の承認が必要', config['instructions'])
        self.assertNotIn(live.CONFIRMATION_RULE, config['instructions'])
        self.assertIn(live.CONFIRMATION_RULE, live._sessions['s']['instructions'])

    def test_local_date_crosses_utc_midnight(self):
        from datetime import datetime, timezone
        instant = datetime(2026, 9, 17, 15, 49, tzinfo=timezone.utc)
        with patch.object(live, 'datetime') as clock:
            clock.now.side_effect = lambda zone: instant.astimezone(zone)
            tokyo = live.session_config('', [], timezone='Asia/Tokyo')['instructions']
            la = live.session_config('', [], timezone='America/Los_Angeles')['instructions']
            fallback = live.session_config('', [], timezone='invalid')['instructions']
        self.assertIn('2026-09-18T00:49:00+09:00（金曜日、Asia/Tokyo）', tokyo)
        self.assertIn('2026-09-17T08:49:00-07:00（木曜日、America/Los_Angeles）', la)
        self.assertEqual(tokyo, fallback)

    async def test_cli_failure_does_not_claim_api_credit_exhaustion(self):
        from app.api import voicelog_routes as routes
        from fastapi import HTTPException
        error = RuntimeError('CLI disconnected')
        with patch.object(routes, '_get_user', return_value=SimpleNamespace(user_id='owner')), \
             patch.object(live, 'respond', new_callable=AsyncMock, side_effect=error):
            with self.assertRaises(HTTPException) as raised:
                await routes.live_backend(None, routes.LiveBackendRequest(session_id='s', input=[{'text':'status'}]))
        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn('Astra', raised.exception.detail)
        self.assertNotIn('残高', raised.exception.detail)
