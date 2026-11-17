"""The Core side of an API job: the same preamble, state, steering, cancellation and delivery as a Codex CLI job
(command_job_runner), but the model loop runs in api_job_worker (a small Python process using the Responses API) instead
of the Codex CLI with an MCP child. Chosen per job: state['engine'] == 'api' (voice-originated work by default).
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.services import command_job_state as state
from app.services.command_job_runner import mark_status, relay_request
from app.services import prompt_store

def _dan_ws():
    from app.paths import DAN_WORKSPACE
    return DAN_WORKSPACE.as_posix()


# JOB_INSTRUCTIONS: the text is ~/.dan/workspace/prompts/work/api-job-instructions.md (seed app/prompts/seed/), read at each use (prompt_store).


def job_rules():
    """The job's rules and the local date (the owner's 「明日」「26日」; a job without it spent a step running `date`)."""
    from app.services.command_center import CONFIRMATION_RULE
    now = datetime.now(ZoneInfo('Asia/Tokyo'))
    from app.paths import localize
    return CONFIRMATION_RULE + localize(_PROMPTS['JOB_INSTRUCTIONS']()) + f"現在の日時: {now.isoformat(timespec='minutes')}（{'月火水木金土日'[now.weekday()]}曜日）" + chr(10)


def job_instructions(room_title=''):
    """What a job model is told (also used by the model benchmark, so it measures the real thing)."""
    head = 'あなたはダン。本人（このアカウントの持ち主）に頼まれた作業を、このパソコンのブラウザや道具で実行する。' + (f'部屋: {room_title}。' if room_title else '')
    return head + chr(10) + job_rules()


async def run(row):
    from app.services.chat_service import ChatService
    from app.services.project_service import ProjectService
    from app.services.run_service import RunService
    from app.services.command_center import report_id, execute
    from app.agent.cli_runner import _build_system_prompt
    job_id, spec = row['id'], row['spec']
    chat, projects, runs = ChatService(), ProjectService(), RunService()
    process, monitor = None, None
    try:
        if state.read(job_id)['state'] in state.TERMINAL:
            return
        state.publish(job_id, 'progress', '実行先を確認しています')
        project = await projects.get_project_by_room_id(row['room_id'])
        if not project: raise RuntimeError('実行先のプロジェクトが見つかりません')
        message = await relay_request(chat, row, spec, job_id)
        run_row = await runs.create_run(project['id'], row['room_id'], origin_message_id=message['id'] if message else None,
                                        metadata={'started_by': 'command_center', 'watch_id': job_id, 'engine': 'api', 'origin_room_id': spec['origin_room_id']})
        initial_state = state.read(job_id)['state']
        state.publish(job_id, 'progress', '依頼内容を確認しています', run_id=run_row['id'], state='running' if initial_state == 'queued' else initial_state)
        # Dan's one core brief (the same as chat Dan's: the owner, the persona, how Dan works, the saved information, the
        # workspace rules), then this surface's own job rules. Until 2026-09-30 a job read only the 1,300 characters of
        # job rules, so work asked for by voice was done by a Dan that knew little of the owner or of how chat Dan works.
        from app.services.dan_core import shared
        instructions = await asyncio.to_thread(shared, row['room_id'], row['user_id'], project.get('title', ''), project.get('description') or '')
        instructions += chr(10) * 2 + '# 作業担当としてのきまり' + chr(10) + job_rules()
        # No room conversation is put in front of the job. The last 8 messages used to be, as if just said, and a job
        # took an old request in them for its own: a Shinkansen search two jobs back (2026-09-24), and a cancelled
        # $10 top-up it set out to "resume" instead of its own task (2026-09-30). Leaving out one kind of copy at a time
        # (Done経由, then 📞) only moved the leak. The task carries what the asker knows it needs; anything more
        # the job reads itself (lookup), where it arrives as a record, not as words said to it now.
        history = []
        state.change(job_id, lambda s: s.update(instructions=instructions, history=history))
        env = {**os.environ, 'DAN_USER_ID': row['user_id'], 'DAN_SESSION_ID': row['room_id'], 'DAN_BROWSER_ROOM': state.browser_room(job_id),
               'DAN_COMMAND_JOB_ID': job_id, 'DAN_BROWSER_HEADLESS': '1', 'DAN_BROWSER_OBSERVATION': 'dom', 'DAN_CORE_PORT': '9000',
               'DAN_WORK_DIR': f'{_dan_ws()}/jobs/{job_id[:8]}',   # the job's own folder: never Dan's repository
               'PYTHONIOENCODING': 'utf-8'}
        root = Path(__file__).resolve().parents[2]
        creation = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0   # never a console window (owner's rule)
        process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'app.services.api_job_worker', job_id, cwd=str(root), env=env,
                                                       stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, creationflags=creation)
        state.change(job_id, lambda s: s.update(worker_pid=process.pid))

        async def controls():
            heartbeat = 0
            while True:
                await asyncio.sleep(.2)
                s = state.read(job_id)
                if s['state'] == 'cancelled' and process.returncode is None:
                    process.terminate(); return
                if time.monotonic() - heartbeat > 10:
                    await runs.update_run(run_row['id'], state=s['state'] if s['state'] in {'paused', 'awaiting_confirmation'} else 'running', only_if_active=True)
                    heartbeat = time.monotonic()
        monitor = asyncio.create_task(controls())
        _, stderr = await process.communicate()
        s = state.read(job_id)
        if s['state'] == 'cancelled':
            await runs.update_run(run_row['id'], state='superseded')
            await asyncio.to_thread(mark_status, job_id, 'cancelled')
            return
        if s['state'] != 'completed':
            tail = (stderr or b'').decode('utf-8', 'replace').strip().splitlines()[-1:] if stderr else []
            raise RuntimeError(f'実行担当が終了しました (rc={process.returncode})' + (': ' + tail[0][:300] if tail else ''))
        result = s.get('result') or ''
        await runs.update_run(run_row['id'], state='completed')
        await execute({'action': 'report', 'project_id': spec['origin_project_id'], 'task': result[:2800]}, row['room_id'], row['user_id'],
                      report_message_id=report_id(job_id))
        await asyncio.to_thread(mark_status, job_id, 'done')
    except Exception as exc:
        saved = state.read(job_id)
        if saved and saved['state'] == 'completed':
            state.publish(job_id, 'error', '作業結果は保存済みです。部屋への配達を再試行します。')
            await asyncio.to_thread(mark_status, job_id, 'pending')
            return
        text = '作業を停止しました: ' + str(exc)[:600]
        s = state.publish(job_id, 'error', text, state='failed', error=text)
        if s.get('run_id'): await runs.update_run(s['run_id'], state='failed')
        await asyncio.to_thread(mark_status, job_id, 'failed')
    finally:
        if monitor:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        if process and process.returncode is None:
            process.terminate()


_PROMPTS = {
    'JOB_INSTRUCTIONS': lambda: '\n' + prompt_store.text('work/api-job-instructions') + '\n',
}


def __getattr__(name):
    """The sentences moved to prompts/ (2026-11-17), read when used so a change on the /prompts screen works at once."""
    if name in _PROMPTS: return _PROMPTS[name]()
    raise AttributeError(name)
