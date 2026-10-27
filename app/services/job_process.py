"""A job owns its runner, pipes and control loop outside Core's lifetime.

The per-job OS lock prevents duplicate execution even during simultaneous wakes.
A crashed runner is never replayed: the normal recovery path marks it interrupted.
"""
import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys

import psutil
from app.services import command_job_state as state
from app.services.file_lock import lock


def alive(saved):
    identity = (saved or {}).get('runner_process') or {}
    try:
        process = psutil.Process(identity['pid'])
        return process.create_time() == identity['created'] and process.status() != psutil.STATUS_ZOMBIE
    except (KeyError, TypeError, psutil.Error):
        return False


@contextmanager
def lease(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            lock(handle.fileno(), True)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            lock(handle.fileno(), False)


async def launch(row):
    job_id = row['id']
    saved = state.read(job_id)
    if alive(saved):
        return
    # Persist before spawn. There is no stdin pipe for Core to close on exit.
    state.change(job_id, lambda s: s.update(runner_request=row))
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, 'DAN_COMMAND_JOB_ROOT': str(state.ROOT), 'PYTHONUNBUFFERED': '1'}
    process = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'app.services.job_process', job_id,
        cwd=str(root), env=env, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=os.name != 'nt',
        creationflags=(getattr(subprocess, 'CREATE_NO_WINDOW', 0) |
                       getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)) if os.name == 'nt' else 0)
    # Waiting does not own the child: cancelling this monitor never kills work.
    code = await process.wait()
    saved = state.read(job_id)
    if code and saved and saved['state'] not in state.TERMINAL and not alive(saved):
        state.publish(job_id, 'error', '作業の実行接続が切れました。実行済み操作の確認が必要です。',
                      state='failed', error='Job runner exited')


async def own(job_id, run=None):
    with lease(state.path(job_id).with_suffix('.runner.lock')) as acquired:
        if not acquired:
            return
        saved = state.read(job_id)
        if saved is None or (saved['state'] in state.TERMINAL and not saved.get('delivery_pending')):
            return
        if saved.get('runner_started') and saved['state'] not in state.TERMINAL:
            # A previous runner disappeared. An external operation might have
            # committed; preserve evidence and require reconciliation.
            state.publish(job_id, 'error', '作業の実行接続が切れました。実行済み操作の確認が必要です。',
                          state='failed', error='Job runner exited')
            return
        state.change(job_id, lambda s: s.update(runner_process={
            'pid': os.getpid(), 'created': psutil.Process().create_time()}))
        if run is None:
            from app.services.command_job_runner import run
        # The former in-Core semaphore did not bound two overlapping Cores.
        # OS slot locks bound all runner generations on this machine.
        while True:
            current = state.read(job_id)
            if current['state'] in state.TERMINAL and not current.get('delivery_pending'):
                return
            for index in range(4):
                with lease(state.ROOT / ('slot-' + str(index) + '.lock')) as slot:
                    if not slot:
                        continue
                    state.change(job_id, lambda s: s.update(runner_started=state.now()))
                    try:
                        await run(saved['runner_request'])
                    except Exception as exc:
                        state.publish(job_id, 'error', '作業の実行接続が終了しました。実行済み操作の確認が必要です。',
                                      state='failed', error=type(exc).__name__)
                        raise
                    finally:
                        state.change(job_id, lambda s: s.update(runner_process=None))
                    return
            await asyncio.sleep(.5)


if __name__ == '__main__':
    asyncio.run(own(sys.argv[1]))
