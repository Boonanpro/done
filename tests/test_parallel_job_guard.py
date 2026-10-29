"""A parallel job's worker neither hands work to background Agents nor sleeps (ScheduleWakeup), and leftover background
work after its answer does not keep the job running (2026-10-29, ローレンタンの部屋「スキルクリエイター比べ」)."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app.services import command_job_state as state
from app.services import parallel_job_runner as runner
from app.services import work_locks

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'scripts' / 'job_tool_hook.py'
sys.path.insert(0, str(ROOT / 'scripts'))
import job_tool_hook  # noqa: E402


class HookTests(unittest.TestCase):
    def test_background_agent_and_wakeup_are_refused_in_a_job_only(self):
        job = {'DAN_COMMAND_JOB_ID': 'j1'}
        self.assertIn('前面', job_tool_hook.decide('Agent', {'run_in_background': True}, job))
        self.assertIn('眠れません', job_tool_hook.decide('ScheduleWakeup', {'delaySeconds': 1800}, job))
        self.assertEqual('', job_tool_hook.decide('Agent', {'prompt': 'x'}, job))
        self.assertEqual('', job_tool_hook.decide('Agent', {'run_in_background': False}, job))
        self.assertEqual('', job_tool_hook.decide('Bash', {'command': 'ls'}, job))
        room = {'DAN_LOCK_OWNER': 'room:r1'}   # a chat room keeps its input open: nothing is refused there
        self.assertEqual('', job_tool_hook.decide('Agent', {'run_in_background': True}, room))
        self.assertEqual('', job_tool_hook.decide('ScheduleWakeup', {}, room))

    def test_hook_process_answers_claude_code(self):
        env = {k: v for k, v in os.environ.items() if k != 'DAN_COMMAND_JOB_ID'}
        call = json.dumps({'tool_name': 'Agent', 'tool_input': {'run_in_background': True, 'prompt': 'x'}})
        out = subprocess.run([sys.executable, str(HOOK)], input=call, capture_output=True, text=True,
                             env={**env, 'DAN_COMMAND_JOB_ID': 'j1'})
        decision = json.loads(out.stdout)['hookSpecificOutput']
        self.assertEqual('deny', decision['permissionDecision'])
        self.assertIn('run_in_background', decision['permissionDecisionReason'])
        out = subprocess.run([sys.executable, str(HOOK)], input=call, capture_output=True, text=True, env=env)
        self.assertEqual('', out.stdout.strip())

    def test_settings_run_the_hook_for_agent_and_wakeup(self):
        hooks = json.loads(work_locks.hook_settings())['hooks']['PreToolUse']
        matchers = {h['matcher']: h['hooks'][0]['command'] for h in hooks}
        self.assertIn('job_tool_hook.py', matchers['Agent|ScheduleWakeup'])
        self.assertIn('work_lock_hook.py', matchers['Write|Edit|MultiEdit|NotebookEdit'])


class CommandTests(unittest.TestCase):
    def test_job_cmd_drops_partials_and_forbids_wakeup(self):
        cmd = ['claude', '-p', '--include-partial-messages', '--disallowedTools', 'ExitPlanMode,AskUserQuestion', '--x']
        self.assertEqual(['claude', '-p', '--disallowedTools', 'ExitPlanMode,AskUserQuestion,ScheduleWakeup', '--x'],
                         runner.job_cmd(cmd))
        self.assertEqual(['claude', '--disallowedTools', 'ScheduleWakeup'], runner.job_cmd(['claude']))
        self.assertEqual(runner.job_cmd(cmd), runner.job_cmd(runner.job_cmd(cmd)))

    def test_rules_tell_the_worker(self):
        self.assertIn('run_in_background', runner.JOB_RULES)
        self.assertIn('ScheduleWakeup', runner.JOB_RULES)
        self.assertIn('更新時刻', runner.JOB_RULES)


FAKE_CLI = textwrap.dedent('''
    import json, sys, time
    sys.stdin.readline()
    print(json.dumps({'type': 'system', 'subtype': 'init', 'session_id': 'S1'}), flush=True)
    print(json.dumps({'type': 'result', 'is_error': False, 'result': 'LAUNCHED', 'session_id': 'S1'}), flush=True)
    time.sleep(float(sys.argv[1]))   # background work the harness waits for, long after the input was closed
''')


class LeftoverWorkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [patch.object(state, 'ROOT', root), patch.object(work_locks, 'ROOT', root),
                        patch.object(work_locks, 'LOCKS', root / 'locks'),
                        patch.dict(os.environ, {'DAN_CLI_RECORDS_DIR': str(root / 'records')}),
                        patch.object(runner, 'AFTER_CLOSE_SILENCE', 1), patch.object(runner, 'AFTER_CLOSE_LIMIT', 3)]
        for p in self.patches:
            p.start()
        self.fake = root / 'fake_cli.py'
        self.fake.write_text(FAKE_CLI, encoding='utf-8')

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def run_job(self, seconds):
        job_id = str(uuid.uuid4())
        state.create(job_id, user_id='U', room_id='R', origin_room_id='R', task='調査して', engine='parallel',
                     model='opus', title='調査', revision=1)
        cmd = [sys.executable, str(self.fake), str(seconds), '--include-partial-messages']
        first = (cmd, {**os.environ, 'DAN_ROOM_ID': 'R'}, '調査して', None)
        final = asyncio.run(runner._session(job_id, state.read(job_id), first))
        return final, state.read(job_id)

    def test_leftover_work_is_cut_and_the_answer_kept(self):
        final, s = self.run_job(120)
        self.assertEqual('LAUNCHED', final)
        self.assertEqual(['返事の後に残っていた裏の作業が終わらないので打ち切りました'],
                         [e['text'] for e in s['events'] if e.get('kind') == 'control'])
        self.assertNotIn(s['id'], runner._procs)

    def test_a_worker_that_exits_is_not_cut(self):
        final, s = self.run_job(0)
        self.assertEqual('LAUNCHED', final)
        self.assertEqual([], [e for e in s['events'] if e.get('kind') == 'control'])


if __name__ == '__main__':
    unittest.main()
