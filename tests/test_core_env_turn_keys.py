"""A Core started from inside a parallel job or a room's turn must not keep that job's or room's identity
(2026-11-08: the 9215 Core started by finished job 6224154e made every chat turn of its room a stopped job)."""
import os
import subprocess
import sys
from pathlib import Path

from app.core import generations

JOB = {'DAN_COMMAND_JOB_ID': '6224154e-470f-442b-9dee-90c31e889a4b', 'DAN_WORK_DIR': '/tmp/jobs/6224154e',
       'DAN_SESSION_ID': 'room-a', 'DAN_ROOM_ID': 'room-a', 'DAN_PARALLEL_JOB': '1', 'CLAUDE_CODE_SESSION_ID': 'x',
       'CLAUDE_EFFORT': 'high', 'DAN_CLI_MODEL': 'fable', 'CLAUDE_CODE_OAUTH_TOKEN': 'token'}


def test_core_env_drops_the_starting_job_and_room(monkeypatch):
    for k, v in JOB.items():
        monkeypatch.setenv(k, v)
    env = generations.core_env(DAN_GENERATION='g')
    for k in ('DAN_COMMAND_JOB_ID', 'DAN_WORK_DIR', 'DAN_SESSION_ID', 'DAN_ROOM_ID', 'DAN_PARALLEL_JOB',
              'CLAUDE_CODE_SESSION_ID', 'CLAUDE_EFFORT'):
        assert k not in env
    assert env['DAN_CLI_MODEL'] == 'fable' and env['CLAUDE_CODE_OAUTH_TOKEN'] == 'token' and env['DAN_GENERATION'] == 'g'


def test_core_started_with_a_job_environment_forgets_it():
    """The leak as it happened: a Core process whose own environment carries the job (started before this fix's
    core_env, or by any other launcher). Importing the Core app clears it before any turn copies os.environ."""
    root = Path(__file__).resolve().parents[1]
    code = "import os, app.core.main; print(os.environ.get('DAN_COMMAND_JOB_ID'), os.environ.get('DAN_SESSION_ID'), os.environ.get('DAN_CLI_MODEL'))"
    out = subprocess.run([sys.executable, '-c', code], cwd=root, env={**os.environ, **JOB}, capture_output=True,
                         text=True, timeout=180)
    assert out.stdout.strip().splitlines()[-1] == 'None None fable', out.stderr[-2000:]
