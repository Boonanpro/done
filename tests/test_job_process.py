import asyncio
import os
import signal
import subprocess
import sys
import uuid
from pathlib import Path

import psutil
import pytest
from app.services import command_job_state as state, job_process


@pytest.fixture
def job(tmp_path, monkeypatch):
    monkeypatch.setattr(state, 'ROOT', tmp_path)
    job_id = str(uuid.uuid4())
    state.create(job_id, runner_request={'id': job_id})
    return job_id


@pytest.mark.asyncio
async def test_two_owners_execute_once_and_record_identity(job):
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []
    async def run(row):
        calls.append(row)
        assert job_process.alive(state.read(job))
        started.set()
        await release.wait()
        state.change(job, lambda s: s.update(state='completed'))
    first = asyncio.create_task(job_process.own(job, run))
    await started.wait()
    await job_process.own(job, run)
    assert len(calls) == 1
    release.set()
    await first
    assert not job_process.alive(state.read(job))


@pytest.mark.asyncio
async def test_dead_runner_is_not_replayed(job):
    state.change(job, lambda s: s.update(runner_started='earlier', state='running'))
    async def run(row):
        pytest.fail('could repeat a payment')
    await job_process.own(job, run)
    assert state.read(job)['state'] == 'failed'


def test_reused_pid_is_not_a_live_owner():
    p = psutil.Process()
    assert not job_process.alive({'runner_process': {'pid': p.pid, 'created': p.create_time() - 1}})


@pytest.mark.asyncio
async def test_completed_result_can_be_delivered_without_rerunning_work(job):
    state.change(job, lambda s: s.update(state='completed', delivery_pending=True, runner_started='earlier'))
    seen = []
    async def deliver(row):
        seen.append(row)
        state.change(job, lambda s: s.update(delivery_pending=False))
    await job_process.own(job, deliver)
    assert len(seen) == 1


@pytest.mark.skipif(os.name == 'nt', reason='POSIX process-group lifecycle')
def test_detached_runner_survives_owning_core_process_group_exit(tmp_path):
    # Real processes, no production jobs, network or model. The parent uses the
    # production launch function; the substitute runner writes after parent exit.
    root = Path(__file__).resolve().parents[1]
    child = tmp_path / 'worker.py'
    child.write_text('import time, pathlib\ntime.sleep(.4)\npathlib.Path(__file__).with_suffix(".done").write_text("finished")\n')
    parent = tmp_path / 'parent.py'
    parent.write_text('''import asyncio, sys, os, uuid
from pathlib import Path
from app.services import job_process as j, command_job_state as s
s.ROOT = Path(sys.argv[1])
job = str(uuid.uuid4()); s.create(job)
original = asyncio.create_subprocess_exec
async def substitute(*args, **kwargs):
    p = await original(sys.executable, sys.argv[2], **kwargs)
    Path(sys.argv[1], 'ready').write_text(str(p.pid))
    return p
asyncio.create_subprocess_exec = substitute
asyncio.run(j.launch({'id': job}))
''')
    env = {**os.environ, 'PYTHONPATH': str(root)}
    p = subprocess.Popen([sys.executable, str(parent), str(tmp_path), str(child)], env=env, start_new_session=True)
    import time
    try:
        deadline = time.monotonic() + 5
        while not (tmp_path / 'ready').exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert (tmp_path / 'ready').exists()
        os.killpg(p.pid, signal.SIGTERM)
        p.wait(timeout=5)
        while not child.with_suffix('.done').exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert child.with_suffix('.done').read_text() == 'finished'
    finally:
        if p.poll() is None:
            p.terminate(); p.wait(timeout=5)
