"""The Core closes runs whose work is gone. Only the process that owns the work can tell that it is gone.

Before (until 2026-09-28): whoever read the current run (the sandbox, polled every 2 s by the screen) marked a run 'failed'
when its updated_at was 90 s old. That was a guess from a missing heartbeat, written by a reader that cannot see the work:
a Codex turn that was compacting its context for two minutes was marked failed at 16:04 and finished at 16:06, and the
screen hid its process monitor for the rest of the turn, because a failed run never comes back. Runs waiting for the
owner's approval or paused were closed the same way.

Now: the Core checks, for each active run that has been quiet a while, whether its work is still alive here (a job's own
state, a CLI/Codex process, a streaming turn, a registered cancellable turn). Only a run with nothing alive behind it is
closed. A Core that died leaves its runs to run_recovery at the next start.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 30
QUIET_SECONDS = float(os.environ.get('DAN_RUN_QUIET_SECONDS', '90'))   # a run touched within this is not looked at (its work may not be registered yet)


def room_turn_alive(room_id):
    """A chat turn for this room is running in this Core."""
    if not room_id:
        return False
    try:
        from app.services.cancellation import CancellationRegistry
        if CancellationRegistry.get_active_info(room_id):
            return True
    except Exception:
        pass
    try:
        from app.agent.cli_runner import is_cli_active
        if is_cli_active(room_id):
            return True
    except Exception:
        pass
    try:
        from app.agent.streaming_session import get_session
        session = get_session(room_id)
        if session is not None and session.is_alive() and session.is_turn_active():
            return True
    except Exception:
        pass
    return False


WAITING_FOR_OWNER = {'paused', 'awaiting_confirmation', 'awaiting_approval'}


def job_alive(job_id):
    """A job's work is its runner task in this Core (command_job_runner runs both engines). A job waiting for the owner
    (approval, pause) is alive without one. A job file that still says 'running' with no task here is left over from an
    earlier Core (six such files from 2026-09-23..26 were seen on 2026-09-27)."""
    from app.services import command_job_state as state
    from app.services.command_job_runner import _tasks
    task = _tasks.get(job_id)
    if task is not None and not task.done():
        return True
    try:
        saved = state.read(job_id)
    except Exception:
        return False
    return bool(saved) and saved.get('state') in WAITING_FOR_OWNER


def is_job_run(run):
    """A command job's run: its work is the job (command_job_state). Other runs with a watch_id (a watch handed off by
    command_handoff) are chat turns run by process_message_cli in the room."""
    from app.services import command_job_state as state
    watch_id = (run.get('metadata') or {}).get('watch_id')
    return bool(watch_id) and state.path(watch_id).exists()


def alive(run, newest_turn_run_by_room):
    if run.get('state') in WAITING_FOR_OWNER:
        return True   # waiting for the owner's answer: no process is needed, and only the owner's answer ends it
    if is_job_run(run):
        return job_alive(run['metadata']['watch_id'])
    # A chat turn: only the room's newest turn run can be the one a live turn belongs to.
    return newest_turn_run_by_room.get(run.get('room_id')) == run['id'] and room_turn_alive(run.get('room_id'))


def reconcile_once(dry_run=False):
    """Close the quiet active runs with no live work in this Core. dry_run lists them without closing (only this Core can
    judge liveness: run elsewhere, every chat turn looks dead)."""
    from app.services.run_service import ACTIVE_RUN_STATES
    from app.services.supabase_client import get_supabase_client
    sb = get_supabase_client().client
    before = (datetime.now(timezone.utc) - timedelta(seconds=QUIET_SECONDS)).isoformat()
    rows = (sb.table('agent_runs').select('id,room_id,state,metadata,created_at,updated_at')
            .in_('state', list(ACTIVE_RUN_STATES)).lt('updated_at', before).limit(100).execute().data or [])
    if not rows:
        return 0
    newest = {}
    for room_id in {r.get('room_id') for r in rows if r.get('room_id')}:
        recent = (sb.table('agent_runs').select('id,metadata').eq('room_id', room_id)
                  .order('created_at', desc=True).limit(20).execute().data or [])
        turn = next((r for r in recent if not is_job_run(r)), None)
        if turn:
            newest[room_id] = turn['id']
    closed = 0
    for run in rows:
        if alive(run, newest):
            continue
        if dry_run:
            print('would close', run['id'][:8], (run.get('room_id') or '?')[:8], run.get('state'), run.get('updated_at'))
            closed += 1
            continue
        sb.table('agent_runs').update({'state': 'failed', 'updated_at': datetime.now(timezone.utc).isoformat()}) \
            .eq('id', run['id']).in_('state', list(ACTIVE_RUN_STATES)).execute()
        closed += 1
        logger.warning("[run-reconciler] closed run %s (room=%s, was %s): no live work in this Core",
                       run['id'][:8], (run.get('room_id') or '?')[:8], run.get('state'))
    return closed


async def loop():
    while True:
        await asyncio.sleep(INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(reconcile_once)
        except Exception as e:  # noqa: BLE001 - the loop must survive a failed pass
            logger.warning("[run-reconciler] pass failed: %s", e)
