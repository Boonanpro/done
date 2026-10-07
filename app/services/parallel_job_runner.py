"""Parallel work inside one room: a job branches off the room's conversation and runs as its own CLI session while chat
Dan keeps talking with the owner. Opus / Fable run here (Claude Code); GPT-6 runs in command_job_runner's Codex path.

Why (2026-10-08): in one room the owner wants, e.g., to decide how to run X while research on which posts grow is under
way and another post goes out — without waiting for the research. Voice jobs could already run in parallel, but only on
GPT-6 with the last 8 messages; making with Opus ran as a turn of the room itself and waited for the room to be free.

Same model as the room: the job continues the room's own session (--resume <room session> --fork-session), so it knows
everything the room knows, and the room's session is not touched. Another model: the job starts with the room's record
rebuilt from the database (the same rebuild a room uses after its session is lost).
The job's final answer is posted in the room under the job's name. A finished job continues with a new instruction
(update): it resumes its own session. Files and the screen/phone the job changes are taken in turn (work_locks).
"""
import asyncio
import json
import logging
import os
import queue
import subprocess
import threading
from pathlib import Path

from app.services import command_job_state as state
from app.services import work_locks

logger = logging.getLogger(__name__)

MODELS = {'opus': 'opus', 'fable': 'fable', 'astra': 'gpt-6-astra'}
LABELS = {'opus': 'Opus', 'fable': 'Fable', 'astra': 'GPT-6'}
_procs: dict[str, subprocess.Popen] = {}

JOB_RULES = """
## この会話について
これは本人とのチャットの部屋から枝分かれした「並行作業」の1つ。部屋では本人とダンの会話が別に続いている。
ここでは頼まれた作業だけを最後までやる。最後の返事がそのまま部屋に「並行作業の結果」として届くので、結果・作ったもの・残っていることを本人向けに書く。
途中で本人から追加の指示が届くことがある（追加の発言として届く）。
同じファイルや、PCの画面操作・スマホ操作を別の作業が使っている時は、その部分だけ自動で順番待ちになる。待ちが長いと書き込みが断られることがあるので、その時はほかの部分を先に進めてから試し直す。
"""


def model_key(value):
    """'opus' / 'fable' / 'astra' from what the owner or a model said ('GPT-6', 'gpt-6-astra', 'Opus' …), else ''."""
    v = str(value or '').strip().lower().replace(' ', '')
    if not v:
        return ''
    if v in MODELS:
        return v
    if 'gpt' in v or 'astra' in v or 'codex' in v:
        return 'astra'
    if 'fable' in v:
        return 'fable'
    if 'opus' in v or 'claude' in v:
        return 'opus'
    return ''


def room_model(room_id):
    from app.agent.cli_runner import resolve_room_backend
    try:
        model, backend = resolve_room_backend(room_id)
    except Exception:
        return 'opus'
    if backend == 'codex':
        return 'astra'
    return 'fable' if model == 'fable' else 'opus'


def title_of(task):
    first = next((line.strip() for line in str(task).splitlines() if line.strip()), '')
    return (first[:57] + '…') if len(first) > 58 else first


async def deliver(job_id, text):
    """The job's answer as a message of the room, under the job's name. On a call in this room the call speaks it."""
    from app.services.chat_service import ChatService
    from app.services.command_center import report_id
    from app.services import voice_calls
    s = state.read(job_id)
    if voice_calls.active(s['room_id']):
        return None
    body = f"**【並行作業：{s.get('title') or title_of(s['task'])}】**\n\n{text.strip()}"
    revision = s.get('delivered_revision', -1) + 1
    message_id = report_id(job_id + (f':{revision}' if revision else ''))
    message = await ChatService().send_message(s['room_id'], s['user_id'], body, sender_type='ai', message_id=message_id)
    state.change(job_id, lambda x: x.update(delivered_revision=revision, report_message_id=message.get('id', message_id)))
    return message


def _kill(job_id):
    proc = _procs.get(job_id)
    if proc and proc.poll() is None:
        subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)], capture_output=True,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def _user_line(text):
    return (json.dumps({'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': text}]}},
                       ensure_ascii=False) + '\n').encode('utf-8')


async def _launch(job_id, s):
    """The command line, environment and first message for this job's Claude Code session."""
    from app.agent import cli_runner as cr
    from app.agent import codex_runner as codex
    from app.services.project_service import ProjectService
    room, user = s['room_id'], s['user_id']
    project = await ProjectService().get_project_by_room_id(room) or {}
    task = s['task']
    resume, fork, content = None, False, task
    if s.get('session_id'):   # a finished job continuing with the owner's new words
        resume = s['session_id']
        pending = [i['text'] for i in s.get('inputs', []) if i['revision'] > s.get('applied_revision', 0)]
        content = '\n'.join(pending) or task
    else:
        room_session = cr._load_session(room)
        same = (room_session and codex.backend_for_session(room_session) == 'claude'
                and room_model(room) == s['model'] and cr._session_transcript_path(room_session) is not None
                and not cr._transcript_exceeds_limit(room_session))
        if same:
            resume, fork = room_session, True
            content = '（ここから並行作業）\n' + task
        else:
            context = await asyncio.to_thread(cr._build_reseed_context, room, project_id=project.get('id'), max_chars=12000)
            content = f'{context}\n\n（ここから並行作業）\n{task}' if context else task
    system_prompt, room_mcp = await cr._prepare_cli_inputs(room, user, None, None, None, dict(
        title=project.get('title', ''), description=project.get('description') or '', status=project.get('status') or 'in_progress',
        user_messages='', latest_user_message=task, room_id=room, user_id=user))
    from app.services.command_center import CONFIRMATION_RULE
    system_prompt += '\n' + JOB_RULES + '\n' + CONFIRMATION_RULE + (s.get('origin_note') or '')
    work_dir = f'D:/dan-workspace/jobs/{job_id[:8]}'
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    cfg = json.loads(Path(room_mcp).read_text(encoding='utf-8'))
    tools_env = cfg['mcpServers']['dan-tools'].setdefault('env', {})
    tools_env.update({'DAN_COMMAND_JOB_ID': job_id, 'DAN_PARALLEL_JOB': '1', 'DAN_JOB_HARNESS': 'claude',
                      'DAN_BROWSER_ROOM': state.browser_room(job_id), 'DAN_BROWSER_HEADLESS': '1', 'DAN_WORK_DIR': work_dir})
    job_mcp = Path(room_mcp).with_name(f'mcp_job_{job_id[:8]}.json')
    job_mcp.write_text(json.dumps(cfg), encoding='utf-8')
    launch_prompt, content = cr._prepare_cli_launch_payload(system_prompt, content)
    claude_cmd, cli_js = cr._resolve_claude_cli()
    if not claude_cmd:
        raise RuntimeError('claude CLI が見つかりません')
    cmd = cr._build_cli_cmd(claude_cmd, cli_js, str(job_mcp), launch_prompt, resume_session_id=resume,
                            fork_session=fork, model=MODELS[s['model']])
    cmd += ['--input-format', 'stream-json']   # --settings (the file hook) comes with _build_cli_cmd
    env = {k: v for k, v in os.environ.items() if k not in ('CLAUDECODE', 'ANTHROPIC_API_KEY')}
    env.update({'DAN_SESSION_ID': room, 'DAN_ROOM_ID': room, 'DAN_COMMAND_JOB_ID': job_id, 'DAN_WORK_DIR': work_dir,
                'CLAUDE_CODE_ENABLE_TASKS': 'true', 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'Never',
                'GH_PROMPT_DISABLED': '1', 'CI': '1', 'NO_COLOR': '1'})
    if project.get('id'):
        env['DAN_PROJECT_ID'] = project['id']
    from app.config import settings
    for key in ('SUPABASE_URL', 'SUPABASE_KEY', 'SUPABASE_SERVICE_ROLE_KEY'):
        if getattr(settings, key, None) and key not in env:
            env[key] = getattr(settings, key)
    return cmd, env, content, job_mcp


async def _session(job_id, s, first):
    """One Claude Code process for this job: the first message, then any words the owner adds while it works.
    Returns the final answer. Raises on a CLI error."""
    cmd, env, first_text, job_mcp = first
    cmd = [c for c in cmd if c != '--include-partial-messages']   # whole messages only: one progress line per step
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            env=env, cwd='D:/dan-workspace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    _procs[job_id] = proc
    lines: queue.Queue = queue.Queue()

    def reader():
        try:
            for raw in proc.stdout:
                lines.put(raw)
        finally:
            lines.put(None)
    threading.Thread(target=reader, daemon=True).start()
    revision = state.read(job_id)['revision']
    proc.stdin.write(_user_line(first_text)); proc.stdin.flush()
    state.change(job_id, lambda x: x.update(applied_revision=max(x['applied_revision'], revision)))

    def send_new_words():
        """The owner's new words go to the running session at once (it takes them after the current step)."""
        cur = state.read(job_id)
        fresh = [i for i in cur['inputs'] if i['revision'] > cur['applied_revision']]
        if not fresh or proc.poll() is not None or proc.stdin.closed:
            return
        proc.stdin.write(_user_line('\n'.join(i['text'] for i in fresh))); proc.stdin.flush()
        rev = fresh[-1]['revision']

        def applied(x):
            x['applied_revision'] = max(x['applied_revision'], rev)
            state.event(x, 'applied', '追加の指示を作業に渡しました')
        state.change(job_id, applied)

    async def watch():
        while True:
            await asyncio.sleep(.5)
            if state.read(job_id)['state'] == 'cancelled':
                _kill(job_id)
                return
            send_new_words()
    watcher = asyncio.create_task(watch())
    final = ''
    try:
        while True:
            raw = await asyncio.to_thread(lines.get)
            if raw is None:
                break
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            kind = event.get('type')
            if kind == 'system' and event.get('session_id'):
                state.change(job_id, lambda x: x.update(session_id=event['session_id']))
            elif kind == 'assistant':
                for block in (event.get('message') or {}).get('content') or []:
                    if block.get('type') == 'text' and block.get('text', '').strip():
                        state.publish(job_id, 'progress', block['text'][:500])
                    elif block.get('type') == 'tool_use':
                        name = str(block.get('name') or 'tool').removeprefix('mcp__dan-tools__')
                        state.change(job_id, lambda x, n=name: x.update(current_tool={'name': n, 'started_at': state.now()}))
                        state.publish(job_id, 'tool', name)
            elif kind == 'result':
                if event.get('session_id'):
                    state.change(job_id, lambda x: x.update(session_id=event['session_id']))
                if event.get('is_error'):
                    raise RuntimeError(str(event.get('result') or event.get('subtype') or 'エラー')[:300])
                final = str(event.get('result') or final)
                send_new_words()
                cur = state.read(job_id)
                if cur['applied_revision'] >= cur['revision'] and not proc.stdin.closed:
                    # Nothing more to say: end of input. Words already sent are still answered before it exits.
                    proc.stdin.close()
        await asyncio.to_thread(proc.wait, 30)
        return final
    finally:
        watcher.cancel()
        _kill(job_id)
        _procs.pop(job_id, None)


async def run(row):
    """One parallel job on Claude Code, from start (or continuation) to the answer posted in the room. Words the owner
    adds after the process has finished its input continue the job's own session in the same run."""
    from app.services.command_job_runner import _slots, mark_status
    job_id = row['id']
    owner = 'job:' + job_id
    job_mcp = None
    try:
        async with _slots:
            s = state.read(job_id)
            if s['state'] in state.TERMINAL:
                return
            state.publish(job_id, 'progress', '作業を始めています', state='running')
            while True:
                launch = await _launch(job_id, state.read(job_id))
                job_mcp = launch[3]
                final = await _session(job_id, state.read(job_id), launch)
                cur = state.read(job_id)
                if cur['state'] == 'cancelled':
                    return
                if cur['applied_revision'] < cur['revision'] and cur.get('session_id'):
                    continue   # new words arrived as the session closed: continue it
                break
            if not final.strip():
                raise RuntimeError('作業の返事が空でした')
            state.publish(job_id, 'result', final[:3000], result=final, state='completed', current_tool=None, waiting_for=None)
            await deliver(job_id, final)
            await asyncio.to_thread(mark_status, job_id, 'done')
    except Exception as exc:
        logger.exception('parallel job failed %s', job_id)
        if (state.read(job_id) or {}).get('state') not in ('cancelled', 'completed'):
            text = f'作業を停止しました: {exc}'[:600]
            state.publish(job_id, 'error', text, state='failed', error=text, current_tool=None)
            try:
                await deliver(job_id, text)
            except Exception:
                logger.exception('parallel job error delivery failed %s', job_id)
            await asyncio.to_thread(mark_status, job_id, 'failed')
    finally:
        _kill(job_id)
        work_locks.release_owner(owner)
        if job_mcp:
            try:
                Path(job_mcp).unlink(missing_ok=True)
            except OSError:
                pass


def public(s):
    """A job as the room's work list shows it."""
    st = s.get('state')
    waiting = s.get('waiting_for')
    label = {'queued': '開始待ち', 'running': '進行中', 'paused': '一時停止', 'awaiting_confirmation': '確認待ち',
             'completed': '完了', 'failed': '失敗', 'cancelled': '停止'}.get(st, st or '')
    if waiting and st not in state.TERMINAL:
        st, label = 'waiting', '順番待ち'
    progress = next((e['text'] for e in reversed(s.get('events') or []) if e.get('kind') in ('progress', 'waiting')), None)
    model = s.get('model') or ''
    return {'id': s['id'], 'title': s.get('title') or title_of(s.get('task', '')), 'task': s.get('task', ''),
            'model': model, 'model_label': LABELS.get(model, model), 'state': st, 'state_label': label,
            'waiting_for': waiting if st == 'waiting' else None,
            'last_progress': (progress or '')[:300] or None,
            'result_excerpt': (s.get('result') or s.get('error') or '')[:300] or None,
            'report_message_id': s.get('report_message_id') if s.get('delivered_revision') is not None else None,
            'active': s.get('state') not in state.TERMINAL, 'created_at': s.get('created_at'), 'updated_at': s.get('updated_at')}


def room_jobs(user_id, room_id, hours=24):
    """This room's parallel jobs: all active ones and those of the last `hours`, newest first."""
    from datetime import datetime, timedelta, timezone
    if not state.ROOT.exists():
        return []
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = []
    for p in state.ROOT.glob('*.json'):
        s = state.read(p.stem)
        if (s and s.get('user_id') == user_id and s.get('room_id') == room_id and s.get('engine') in ('parallel', 'make')
                and (s['state'] not in state.TERMINAL or (s.get('updated_at') or '') >= since)):
            rows.append(s)
    rows.sort(key=lambda s: (s['state'] in state.TERMINAL, s.get('created_at') or ''), reverse=False)
    active = [s for s in rows if s['state'] not in state.TERMINAL]
    done = [s for s in rows if s['state'] in state.TERMINAL]
    return (sorted(active, key=lambda s: s.get('created_at') or '', reverse=True)
            + sorted(done, key=lambda s: s.get('updated_at') or '', reverse=True))[:20]


async def start(room_id, user_id, task, model='', title=''):
    """Start a parallel job in this room (from chat Dan's tool or the room's work list)."""
    from app.services.command_center import execute
    model = model_key(model) or room_model(room_id)
    out = await execute({'action': 'work', 'engine': 'parallel', 'model': model, 'task': task, 'title': title},
                        room_id, user_id)
    if not out.get('accepted'):
        raise ValueError(out.get('error') or '作業を始められませんでした')
    return state.read(out['receipt']['id'])


async def control(room_id, user_id, job_id, operation, text='', model=''):
    """update / cancel / switch_model on a job of this room. A finished job continues on update."""
    from app.services.command_center import _wake_job
    s = state.read(job_id)
    if not s or s.get('user_id') != user_id or s.get('room_id') != room_id or s.get('engine') not in ('parallel', 'make'):
        raise ValueError('この部屋の並行作業が見つかりません')
    if operation == 'switch_model':
        new = model_key(model)
        if not new:
            raise ValueError('モデルを選んでください')
        if s['state'] not in state.TERMINAL:
            state.control(job_id, user_id, s['origin_room_id'], 'cancel')
        return await start(room_id, user_id, s['task'], new, s.get('title') or '')
    if operation == 'update' and s['state'] in ('completed', 'failed'):
        if not str(text).strip():
            raise ValueError('追加の指示が必要です')
        if s['model'] == 'astra' and not s.get('persistent_thread'):
            # GPT-6 started without the room's session: continue in a new job that knows the previous result
            follow = f"{s['task']}\n\n（前回の結果）\n{(s.get('result') or s.get('error') or '')[:4000]}\n\n（追加の指示）\n{text}"
            return await start(room_id, user_id, follow, 'astra')

        def reopen(x):
            x['revision'] += 1
            x['inputs'].append({'revision': x['revision'], 'text': str(text)})
            x.update(state='queued', result=None, error=None, waiting_for=None)
            x.pop('accepted_at', None)
            state.event(x, 'control', '追加の指示で作業を再開します')
        state.change(job_id, reopen)
        await _wake_job(job_id)
        return state.read(job_id)
    if operation in ('update', 'cancel'):
        out = state.control(job_id, user_id, s['origin_room_id'], operation, text)
        if operation == 'cancel':
            _kill(job_id)
            work_locks.release_owner('job:' + job_id)
        return out
    raise ValueError('未対応の操作です')
