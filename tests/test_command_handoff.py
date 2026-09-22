import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from app.services import command_handoff as h


class RunLineageTests(unittest.TestCase):
    def test_autonomous_completion_preserves_parent_run(self):
        from app.agent import cli_runner as cli
        runs = MagicMock()
        runs.create_run = AsyncMock(return_value={'id': 'child'})
        with patch('app.services.run_service.RunService', return_value=runs), \
             patch.object(cli, '_save_execution_event_sync'), patch.object(cli, '_cli_debug'):
            sink = cli._make_autonomous_sink('room', 'user', 'project', None, parent_run_id='parent')
            sink({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Finishing the job'}]}})
        self.assertEqual(runs.create_run.call_args.kwargs['parent_run_id'], 'parent')


class HandoffTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.row = {'id': 'job', 'room_id': 'room', 'user_id': 'owner', 'plain_note': 'inspect',
                    'spec': {'run_id': 'root', 'origin_project_id': 'hub', 'started_at':
                             (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat()}}

    async def test_recovered_watch_does_not_execute_again(self):
        with patch.object(h, 'defer', new_callable=AsyncMock) as defer:
            await h.start(self.row)
        defer.assert_awaited_once()

    async def test_executor_answer_is_delivered_without_claiming_task_success(self):
        self.row['spec']['result'] = 'The analysis is still running; I will report later.'
        self.row['spec']['started_at'] = (datetime.now(timezone.utc)-timedelta(seconds=90)).isoformat()
        with patch.object(h, 'lineage', new_callable=AsyncMock, return_value=[]), \
             patch.object(h, 'ChatService'), patch.object(h, 'start', new_callable=AsyncMock) as resume, \
             patch.object(h, 'mark_status'), \
             patch('app.services.command_center.execute', new_callable=AsyncMock) as report:
            await h.deliver(self.row)
        resume.assert_not_awaited()
        self.assertEqual(report.call_args.args[0]['task'], self.row['spec']['result'])
        self.assertEqual(self.row['spec']['outcome'], 'reported')

    async def test_api_outage_does_not_block_delivery_of_saved_result(self):
        self.row['spec']['result'] = 'Train options found; purchase not made.'
        with patch.object(h, 'lineage', new_callable=AsyncMock, return_value=[]), \
             patch.object(h, 'ChatService'), patch.object(h, 'defer', new_callable=AsyncMock) as defer, \
             patch.object(h, 'mark_status'), \
             patch('httpx.AsyncClient', side_effect=RuntimeError('credit_balance_exhausted')), \
             patch('app.services.command_center.execute', new_callable=AsyncMock) as report:
            await h.deliver(self.row)
        defer.assert_not_awaited()
        report.assert_awaited_once()

    async def test_active_successor_is_not_reported_as_done(self):
        with patch.object(h, 'lineage', new_callable=AsyncMock, return_value=[{'state': 'running'}]), \
             patch.object(h, 'defer', new_callable=AsyncMock) as defer, \
             patch('app.services.command_center.execute', new_callable=AsyncMock) as report:
            await h.deliver(self.row)
        defer.assert_awaited_once()
        report.assert_not_awaited()

    async def test_failed_run_reports_error_instead_of_deferring(self):
        self.row['spec'].update(result='Browser login failed', is_error=True, outcome='completed')
        with patch.object(h, 'lineage', new_callable=AsyncMock, return_value=[]), \
             patch.object(h, 'ChatService'), patch.object(h, 'mark_status') as mark, \
             patch('app.services.command_center.execute', new_callable=AsyncMock) as report:
            await h.deliver(self.row)
        self.assertIn('Browser login failed', report.call_args.args[0]['task'])
        self.assertEqual(self.row['spec']['outcome'], 'failed')
        mark.assert_called_once_with('job', 'failed')

    async def test_delivery_failure_keeps_watch_retryable(self):
        self.row['spec']['result'] = 'Saved result'
        with patch.object(h, 'lineage', new_callable=AsyncMock, return_value=[]), \
             patch.object(h, 'ChatService'), patch.object(h, 'mark_status') as mark, \
             patch('app.services.command_center.execute', new_callable=AsyncMock, side_effect=RuntimeError('database offline')):
            with self.assertRaises(RuntimeError):
                await h.deliver(self.row)
        mark.assert_not_called()

    async def test_empty_initial_result_waits_for_background_completion(self):
        self.row['spec']['result'] = '（応答テキストが空でした。もう一度お試しください。）'
        with patch.object(h, 'lineage', new_callable=AsyncMock, return_value=[]), \
             patch.object(h, 'ChatService'), patch.object(h, 'defer', new_callable=AsyncMock) as defer, \
             patch('app.services.command_center.execute', new_callable=AsyncMock) as report:
            await h.deliver(self.row)
        defer.assert_awaited_once()
        report.assert_not_awaited()

    async def test_child_result_replaces_empty_parent(self):
        self.row['spec']['result'] = '（応答テキストが空でした。もう一度お試しください。）'
        child = {'id': 'child', 'state': 'completed', 'created_at': '2026-09-14', 'project_id': 'p'}
        db = MagicMock()
        query = db.table.return_value
        for name in ('select', 'eq', 'in_', 'order', 'update'):
            getattr(query, name).return_value = query
        query.execute.return_value = SimpleNamespace(data=[{'content': '3 articles; healthy'}])
        project = MagicMock()
        project.get_execution_events = AsyncMock(return_value=[{'turn_id': 'child-turn'}])
        with patch.object(h, 'lineage', new_callable=AsyncMock, return_value=[child]), \
             patch.object(h, 'ChatService', return_value=SimpleNamespace(supabase=db)), \
             patch.object(h, 'ProjectService', return_value=project), \
             patch.object(h, 'mark_status') as mark, \
             patch('app.services.command_center.execute', new_callable=AsyncMock) as report:
            await h.deliver(self.row)
        self.assertEqual(report.call_args.args[0]['task'], '3 articles; healthy')
        query.in_.assert_called_with('ai_context->>turn_id', ['child-turn'])
        mark.assert_called_once_with('job', 'done')
