import unittest
from unittest.mock import AsyncMock, patch

from app.services import command_center as cc


class CommandCenterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        local = patch('app.services.command_job_state.create')
        self.local = local.start(); self.addCleanup(local.stop)
        network = patch('httpx.AsyncClient')
        network.start(); self.addCleanup(network.stop)
        wake = patch.object(cc,'_wake_job',new_callable=AsyncMock)
        wake.start();self.addCleanup(wake.stop)
        self.chat = AsyncMock()
        self.projects = AsyncMock()
        self.chat.get_room.return_value = {"id": "room"}
        self.projects.get_project.return_value = {"id": "target", "room_id": "target-room", "title": "Target"}
        self.projects.get_project_by_room_id.return_value = {
            "id": "hub", "room_id": "hub-room", "title": "Hub", "user_id": "owner"}
        for name, obj in [("ChatService", self.chat), ("ProjectService", self.projects)]:
            p = patch.object(cc, name, return_value=obj)
            p.start()
            self.addCleanup(p.stop)
        run_patch = patch('app.services.run_service.RunService')
        self.runs = run_patch.start().return_value
        self.runs.get_current_run = AsyncMock(return_value=None)
        self.addCleanup(run_patch.stop)

    async def test_source_access_required_before_listing(self):
        self.chat.get_room.return_value = None
        with self.assertRaises(ValueError):
            await cc.execute({"action": "list"}, "foreign-room", "owner")
        self.projects.list_projects.assert_not_called()

    async def test_approval_is_judged_by_jev_against_the_presented_proposal(self):
        """「問題ない、買って」 was refused by the old word list (on 「ない」); the reply is now judged against the proposal."""
        asked = []
        async def choose(self_, state, questions):
            asked.append(state)
            ok = state['reply'] == '問題ない、買って'
            return {'available': True, 'answers': {'reply': {'choice': 'approve' if ok else 'change_or_question',
                                                            'probabilities': {'approve': .97 if ok else .02}}}}
        with patch('app.services.command_job_state.owned', return_value={'confirmation': {'summary': 'のぞみ8号 14,320円を購入'}}),              patch('app.services.jev_decisions.Decisions.choose', choose):
            self.assertTrue(await cc._approves('owner', 'hub-room', 'job', '問題ない、買って'))
            self.assertFalse(await cc._approves('owner', 'hub-room', 'job', '何号車？'))
            self.assertFalse(await cc._approves('owner', 'hub-room', 'job', ''))
        self.assertEqual(asked[0]['presented'], 'のぞみ8号 14,320円を購入')

    async def test_unavailable_judgement_never_approves(self):
        async def choose(self_, state, questions): return {'available': False, 'reason': 'unavailable'}
        with patch('app.services.command_job_state.owned', return_value={'confirmation': {'summary': 'x'}}),              patch('app.services.jev_decisions.Decisions.choose', choose):
            self.assertFalse(await cc._approves('owner', 'hub-room', 'job', 'はい'))

    async def test_confirmation_cannot_reuse_reply_before_proposal(self):
        self.chat.get_messages.return_value = [{'sender_type':'human','content':'はい',
            'created_at':'2026-09-15T09:00:00Z'}]
        with patch('app.services.command_job_state.owned',return_value={
            'confirmation':{'created_at':'2026-09-15T09:01:00+00:00'}}), \
            patch('app.services.command_job_state.control') as control,             patch.object(cc,'_approves',new_callable=AsyncMock,return_value=True):
            with self.assertRaisesRegex(ValueError,'提示した後'):
                await cc.execute({'action':'control_job','operation':'confirm','job_id':'job',
                    'confirmation_id':'proposal','approval_text':'はい'},'hub-room','owner')
            control.assert_not_called()

    async def test_question_is_not_confirmation(self):
        with patch('app.services.command_job_state.control') as control,              patch.object(cc, '_approves', new_callable=AsyncMock, return_value=False):
            with self.assertRaises(ValueError):
                await cc.execute({'action':'control_job','operation':'confirm','job_id':'job',
                    'confirmation_id':'proposal','approval_text':'何号車？'},'hub-room','owner')
            control.assert_not_called()

    async def test_target_access_required_before_read_or_write(self):
        self.projects.get_project.return_value = None
        for action in ("read", "delegate", "report"):
            with self.assertRaises(ValueError):
                await cc.execute({"action": action, "project_id": "foreign", "task": "work"}, "hub-room", "owner")
        self.chat.get_messages.assert_not_called()
        self.chat.send_message.assert_not_called()

    async def test_read_is_read_only_and_paginates(self):
        self.chat.get_messages.return_value = [{"id": "m", "created_at": "2026-09-12T00:00:00Z", "content": "fact"}]
        with patch('app.services.timeline_live.editor_state', return_value=None):
            result = await cc.execute({"action": "read", "project_id": "target", "limit": 1}, "hub-room", "owner")
        self.assertEqual(result["next_before"], "2026-09-12T00:00:00Z")
        self.chat.send_message.assert_not_called()

    async def test_delegate_durably_targets_selected_room_and_returns_receipt(self):
        with patch('app.services.followups.create_watch', return_value={"scheduled": True, "id": "watch"}) as watch:
            result = await cc.execute({"action": "delegate", "project_id": "target", "task": "check only"}, "hub-room", "owner")
        self.assertTrue(result["accepted"])
        watch.assert_not_called()
        self.assertEqual(self.local.call_args.kwargs['room_id'],'target-room')
        self.assertEqual(self.local.call_args.kwargs['origin_room_id'],'hub-room')
        self.assertEqual(self.local.call_args.kwargs['queue_owner'],'core')
        self.chat.send_message.assert_not_called()

    async def test_report_returns_to_selected_project_with_source_link(self):
        self.chat.send_message.return_value = {"id": "report"}
        result = await cc.execute({"action": "report", "project_id": "target", "task": "done"}, "hub-room", "owner")
        self.assertTrue(result['reported'])
        self.assertEqual(self.chat.send_message.call_args.args[:2], ('target-room', 'owner'))
        self.assertIn('/chat/hub', self.chat.send_message.call_args.args[2])

    async def test_local_work_uses_authenticated_room_and_durable_tracker(self):
        with patch('app.services.followups.create_watch', return_value={'scheduled': True, 'id': 'local-watch'}) as watch:
            result = await cc.execute({'action': 'work', 'project_id': 'untrusted', 'task': 'Read a web page; do not buy'}, 'hub-room', 'owner')
        self.assertTrue(result['accepted'])
        watch.assert_not_called()
        self.assertEqual(self.local.call_args.kwargs['room_id'],'hub-room')
        self.assertEqual(self.local.call_args.kwargs['origin_project_id'],'hub')
        self.assertEqual(result['report_message_id'], cc.report_id(result['receipt']['id']))
        self.projects.get_project.assert_not_called()

    async def test_local_work_rejects_foreign_project_owner(self):
        self.projects.get_project_by_room_id.return_value['user_id'] = 'foreign'
        with patch('app.services.followups.create_watch') as watch:
            with self.assertRaises(ValueError):
                await cc.execute({'action': 'work', 'task': 'work'}, 'hub-room', 'owner')
        watch.assert_not_called()


class DispatchRelayTests(unittest.IsolatedAsyncioTestCase):
    async def test_wake_retries_only_same_durable_job_after_timeout(self):
        import httpx
        from unittest.mock import MagicMock
        client=AsyncMock();client.__aenter__.return_value=client
        response=MagicMock();response.json.return_value={'accepted':True}
        client.post.side_effect=[httpx.ReadTimeout('timeout'),response]
        with patch('httpx.AsyncClient',return_value=client),patch('app.services.browser_lifecycle._token_path') as path,patch.object(cc.asyncio,'sleep',new_callable=AsyncMock):
            path.return_value.read_text.return_value='test-token'
            await cc._wake_job('same-job')
        self.assertEqual(client.post.await_count,2)
        self.assertTrue(all(c.kwargs['json']=={'job_id':'same-job'} for c in client.post.await_args_list))

    def test_mcp_formatter_preserves_capability_payload(self):
        import json
        from app.agent.v2.tools import format_tool_result
        payload = {'projects': [{'id': 'p', 'title': 'test'}], 'count': 1}
        self.assertEqual(json.loads(format_tool_result(payload, '_command_center', 'manage').text), payload)

    async def test_command_dispatch_uses_durable_tracker(self):
        from app.services.followup_poller import _fire_handoff
        row = {'id': 'job', 'room_id': 'target', 'spec': {'command_center': True}}
        with patch('app.services.command_handoff.start', new_callable=AsyncMock) as start:
            await _fire_handoff(row)
        start.assert_awaited_once_with(row)
