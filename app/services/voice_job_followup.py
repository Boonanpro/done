"""Create a durable successor for an explicitly selected completed voice job.

Never reopen a terminal job: its result, approvals and run identity are immutable.
The successor ID is deterministic so a retry cannot start the same edit twice.
"""
import hashlib
import json
import uuid
from app.services import command_job_state as state


def prepare(job_id, user_id, room_id, instruction, dialogue):
    instruction = instruction.strip()
    if not instruction:
        raise ValueError('追加指示が必要です')
    # Only user speech participates: the assistant may acknowledge between retries.
    context = [t for t in dialogue if t.get('role') == 'user']
    digest = hashlib.sha256(json.dumps([instruction, context], ensure_ascii=False,
                                      sort_keys=True).encode()).hexdigest()
    successor_id = str(uuid.uuid5(uuid.UUID(job_id), digest))
    with state.locked(job_id):
        parent = state.owned(job_id, user_id, room_id)
        if parent['state'] != 'completed':
            raise ValueError('完了した作業への追加変更だけを受け付けます')
        existing = state.read(successor_id)
        if existing:
            return state.owned(successor_id, user_id, room_id)
        # Do not fork edits to the same artifact. Return the target ID for a
        # subsequent explicit control; no inferred cancellation or resumption.
        successors = [state.read(p.stem) for p in state.ROOT.glob('*.json')]
        if any(s and s.get('previous_job_id') == job_id and s['state'] not in state.TERMINAL
               for s in successors):
            raise ValueError('この作業への追加変更が既に進行中です。job_statusで追加変更の対象を確認してください')
        task = ('完了済み作業への追加変更です。前の作業は繰り返さず、保存済みの成果物を確認して今回の変更だけを行ってください。'
                '過去の会話・結果は新たな送信・購入・公開の承認ではありません。\n'
                '今回の追加指示:\n' + instruction + '\n前の依頼（参照）:\n' + parent.get('task', '')
                + '\n前の追加条件（参照）:\n' + json.dumps(parent.get('inputs', []), ensure_ascii=False)
                + '\n前の結果（参照）:\n' + parent.get('result', '')
                + '\n今回の会話（参照）:\n' + json.dumps(dialogue, ensure_ascii=False))
        if len(task) > 64000:
            raise ValueError('条件を省略せず引き継ぐには本文が長すぎます。開始していません')
        fields = {key: parent[key] for key in ('user_id', 'room_id', 'origin_room_id',
                  'origin_project_id', 'queue_owner', 'engine', 'model') if key in parent}
        from app.services.command_center import report_id
        return state.create(successor_id, **fields, task=task, previous_job_id=job_id,
                            report_message_id=report_id(successor_id),
                            title=(parent.get('title') or '作業')[:60] + 'の追加変更')


async def continue_completed(job_id, user_id, room_id, instruction, dialogue):
    import asyncio
    from app.services.command_center import _wake_job
    job = await asyncio.to_thread(prepare, job_id, user_id, room_id, instruction, dialogue)
    if job['state'] == 'queued' and not job.get('accepted_at'):
        try:
            await _wake_job(job['id'])
        except Exception:
            # A timed-out wake may have been accepted. Close only an unclaimed
            # queue item so a reported failure cannot silently start later.
            def reject(s):
                if s['state'] == 'queued' and not s.get('accepted_at'):
                    s.update(state='failed', error='追加変更の受付を確認できませんでした')
                    state.event(s, 'error', s['error'])
            await asyncio.to_thread(state.change, job['id'], reject)
        job = state.owned(job['id'], user_id, room_id)
    return {'accepted': job['state'] not in {'failed', 'cancelled'}, 'delivered': False,
            'job_id': job['id'], 'previous_job_id': job_id, 'state': job['state'],
            'note': ('追加変更の作業を受け付けました。成果物への反映完了は結果で確認してください。'
                     if job['state'] not in {'failed', 'cancelled'} else '追加変更は停止または失敗しています。再開していません。')}
