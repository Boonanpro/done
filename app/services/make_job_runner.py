"""The making lane of Dan's core: heavy making (pages, videos, documents, code) asked for from any surface is done by chat
Dan's own harness in that room — Claude Code (Opus, the default; or Fable) or Codex (GPT Astra) — with the same room,
memory and brief as chat. The job wraps the turn so the surfaces follow it like any other work: the call screen's status
line, 「どうなってる？」 (job_status), a change or a stop (steer_job), and the result spoken in the call.

Why (2026-09-30): the worker that did work asked for by voice was DeepSeek Flash with a short brief, so a voice request to
make or fix something could not be done the way chat does it. Heavy making is what these harnesses are built for.
"""
import asyncio
import logging

from app.services import command_job_state as state
from app.services.command_job_runner import mark_status

logger = logging.getLogger(__name__)

MODELS = {'opus': 'opus', 'fable': 'fable', 'astra': 'gpt-6-astra'}
DEFAULT_MODEL = 'opus'   # the owner's choice (2026-09-30)
BUSY_WAIT = 300
ORIGIN_NOTE = ('\n\n（通話で本人から頼まれた制作です。結果は通話でも読み上げられるので、最後の報告は要点から短く。'
               '取り返しのつかない確定（公開・送信・購入・削除）の前は、内容を示して本人の返事を待つ。）')


def words(task):
    """The owner's request as said, without the job's internal notes."""
    from app.services.voice_parts import VOICE_TASK
    return task.replace(VOICE_TASK, '').split('\n参考の直前会話（')[0].removeprefix('今回のユーザー発言（原文）:\n').strip()


async def _turn(job_id, row, prompt, model):
    """One chat turn in the room with the chosen model. Returns Dan's final text ('' if none)."""
    from app.agent.cli_runner import process_message_cli
    from app.services.followup_poller import _resolve_project_id
    final = ''
    async for event in process_message_cli(room_id=row['room_id'], user_id=row['user_id'], content=prompt,
                                           project_id=_resolve_project_id(row['room_id']), model_override=model):
        kind = event.get('type')
        if kind == 'tool_use':
            name = str(event.get('tool_name') or event.get('name') or event.get('tool') or 'tool')
            state.change(job_id, lambda s: s.update(current_tool={'name': name}))
            state.publish(job_id, 'tool', name)
        elif kind == 'text' and event.get('text'):
            state.publish(job_id, 'progress', str(event['text'])[:500])
            final = str(event['text'])
        elif kind == 'result':
            final = str(event.get('text') or event.get('result') or final)
        elif kind == 'error':
            raise RuntimeError(str(event.get('message') or event.get('error') or 'エラー')[:300])
    return final.strip()


async def run(row):
    from app.agent.cli_runner import kill_cli_process
    from app.services.cancellation import CancellationRegistry
    from app.services.chat_service import ChatService
    from app.services.followup_poller import _room_busy
    job_id, spec = row['id'], row['spec']
    room = row['room_id']
    s = state.read(job_id)
    model = MODELS.get(str(s.get('model') or ''), MODELS[DEFAULT_MODEL])
    state.publish(job_id, 'progress', '制作の担当に渡しています', state='running')

    async def stop_on_cancel():
        while True:
            await asyncio.sleep(1)
            if state.read(job_id).get('state') == 'cancelled':
                CancellationRegistry.cancel(room)
                kill_cli_process(room)
                return
    watcher = asyncio.create_task(stop_on_cancel())
    try:
        waited = 0
        while _room_busy(room):   # never interleave with a turn the owner is having in this room
            if waited >= BUSY_WAIT:
                raise RuntimeError('この部屋のダンが別の返事の途中で、5分待っても空きませんでした')
            await asyncio.sleep(5)
            waited += 5
        asked = words(spec['task'])
        await ChatService().send_message(room, row['user_id'], '📞 通話からの依頼: ' + asked, sender_type='human')
        final = await _turn(job_id, row, asked + ORIGIN_NOTE, model)
        while True:   # changes said while it worked (steer_job update) are the next turns of the same work
            cur = state.read(job_id)
            if cur['state'] == 'cancelled':
                return
            pending = [i for i in cur.get('inputs', []) if i['revision'] > cur.get('applied_revision', 0)]
            if not pending:
                break
            state.change(job_id, lambda x: x.update(applied_revision=pending[-1]['revision']))
            final = await _turn(job_id, row, '\n'.join(i['text'] for i in pending), model)
        if state.read(job_id)['state'] == 'cancelled':
            return
        state.publish(job_id, 'result', final or '制作が終わりました。部屋に結果を出しています。', result=final or '制作が終わりました。', state='completed')
        await asyncio.to_thread(mark_status, job_id, 'done')
    except Exception as exc:
        logger.exception('make job failed %s', job_id)
        if state.read(job_id).get('state') != 'cancelled':
            state.publish(job_id, 'error', f'作業を停止しました: {exc}', state='failed', error=str(exc)[:300])
            await asyncio.to_thread(mark_status, job_id, 'failed')
    finally:
        watcher.cancel()
