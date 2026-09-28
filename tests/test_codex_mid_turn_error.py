"""A Codex error while the turn goes on is not the turn's end (2026-09-28: the chat marked the run failed and the screen
dropped its process monitor while Codex kept working)."""
import json
import os
import queue
import sys
import tempfile
import unittest

from app.agent import codex_runner


class MidTurnErrorTests(unittest.TestCase):
    def test_error_line_during_a_turn_does_not_end_it(self):
        lines = [
            {'type': 'thread.started', 'thread_id': 't-1'},
            {'type': 'error', 'message': 'image generation request failed; retrying'},
            {'type': 'item.completed', 'item': {'type': 'error', 'id': 'e1', 'message': 'tool call failed'}},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'id': 'm1', 'text': 'できました'}},
            {'type': 'turn.completed', 'usage': {}},
        ]
        script = tempfile.NamedTemporaryFile('w', suffix='.py', delete=False, encoding='utf-8')
        script.write('import sys\nsys.stdin.read()\n' + ''.join(f'print({json.dumps(json.dumps(l, ensure_ascii=False))})\n' for l in lines))
        script.close()
        events = queue.Queue()
        try:
            with unittest.mock.patch('app.agent.cli_runner._save_session'), \
                 unittest.mock.patch('app.agent.cli_runner._update_run_sync'):
                result = codex_runner.run_codex_process([sys.executable, script.name], 'hi', {**os.environ, 'PYTHONIOENCODING': 'utf-8'}, 'room-test', events)
        finally:
            os.unlink(script.name)
        kinds = []
        while not events.empty():
            kinds.append(events.get().get('type'))
        self.assertNotIn('error', kinds)
        self.assertFalse(result['is_error'])
        self.assertEqual(result['result_text'], 'できました')


import unittest.mock  # noqa: E402

if __name__ == '__main__':
    unittest.main()
