import asyncio
import unittest
from unittest.mock import MagicMock, patch

from app.services import run_reconciler


class AliveTests(unittest.TestCase):
    def test_waiting_for_owner_is_alive(self):
        self.assertTrue(run_reconciler.alive({'id': 'r', 'room_id': 'R', 'state': 'awaiting_confirmation', 'metadata': {}}, {}))

    def test_chat_turn_alive_only_as_the_rooms_newest_with_a_live_turn(self):
        run = {'id': 'r', 'room_id': 'R', 'state': 'running', 'metadata': {}}
        with patch.object(run_reconciler, 'room_turn_alive', return_value=True):
            self.assertTrue(run_reconciler.alive(run, {'R': 'r'}))
            self.assertFalse(run_reconciler.alive(run, {'R': 'newer'}))
        with patch.object(run_reconciler, 'room_turn_alive', return_value=False):
            self.assertFalse(run_reconciler.alive(run, {'R': 'r'}))

    def test_job_run_follows_its_runner_task(self):
        from app.services import command_job_runner
        run = {'id': 'r', 'room_id': 'R', 'state': 'running', 'metadata': {'watch_id': 'job1'}}
        task = MagicMock(); task.done.return_value = False
        with patch.object(run_reconciler, 'is_job_run', return_value=True), \
             patch.dict(command_job_runner._tasks, {'job1': task}, clear=True):
            self.assertTrue(run_reconciler.alive(run, {}))
            task.done.return_value = True
            with patch('app.services.command_job_state.read', return_value={'state': 'running'}):
                self.assertFalse(run_reconciler.alive(run, {}))   # a job file left over from an earlier Core


class ReadDoesNotWriteTests(unittest.TestCase):
    def test_current_run_returns_a_quiet_running_run_unchanged(self):
        from app.services.run_service import RunService
        service = RunService.__new__(RunService)
        service.supabase = MagicMock()
        row = {'id': 'r', 'state': 'running', 'updated_at': '2020-01-01T00:00:00+00:00', 'superseded_by_run_id': None}
        service.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[row])
        self.assertEqual(asyncio.run(service.get_current_run('p'))['state'], 'running')
        service.supabase.table.return_value.update.assert_not_called()


if __name__ == '__main__':
    unittest.main()
