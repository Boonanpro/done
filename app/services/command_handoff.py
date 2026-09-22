"""Durable cross-room work: a visible request, run lineage, and final delivery."""
import asyncio
from datetime import datetime, timedelta, timezone

from app.services.chat_service import ChatService
from app.services.run_service import RunService
from app.services.project_service import ProjectService
from app.services.followups import reschedule_watch, mark_status


def usable(text):
    return bool(text and text.strip() and '応答テキストが空でした' not in text
                and 'バックグラウンド作業の続きを実行しました' not in text)


async def defer(row, spec):
    await asyncio.to_thread(reschedule_watch, row['id'], 'command_report', row['plain_note'], spec,
                            datetime.now(timezone.utc) + timedelta(seconds=15))


async def start(row):
    if row['spec'].get('engine') == 'steerable_cli':
        from app.services.command_job_runner import dispatch
        dispatch(row)
        return
    from app.agent.cli_runner import process_message_cli
    from app.services.command_center import report_id, CONFIRMATION_RULE
    spec = dict(row['spec'])
    # A recovered watch must observe its existing run rather than execute twice.
    if spec.get('run_id'):
        await defer(row, spec)
        return
    chat = ChatService()
    project = await ProjectService().get_project_by_room_id(row['room_id'])
    identity = {'watch_id': row['id']}
    existing = await asyncio.to_thread(lambda: chat.supabase.table('agent_runs').select('*')
        .eq('room_id', row['room_id']).contains('metadata', identity).limit(1).execute())
    if existing.data:
        run = existing.data[0]
        spec.update(run_id=run['id'], started_at=run['created_at'])
        await defer(row, spec)
        return
    message = await chat.send_message(row['room_id'], row['user_id'],
        '【あなたの依頼・Done経由】\n' + spec.get('task', row['plain_note']), sender_type='system',
        message_id=report_id(row['id'] + ':request'))
    runs = RunService()
    run = await runs.create_run(project['id'], row['room_id'], origin_message_id=message['id'],
        metadata={'started_by': 'command_center', **identity, 'origin_room_id': spec['origin_room_id']})
    spec.update(run_id=run['id'], started_at=datetime.now(timezone.utc).isoformat())
    # Persist the identity before starting the runner, while keeping the watch claimed.
    from app.services.followups import encode_watch_note
    await asyncio.to_thread(lambda: chat.supabase.table('pending_followups').update({
        'note': encode_watch_note('handoff', row['plain_note'], spec)}).eq('id', row['id']).execute())
    try:
        async for event in process_message_cli(room_id=row['room_id'], user_id=row['user_id'],
                content=row['plain_note'] + '\n\n【実行時の確認規則】\n' + CONFIRMATION_RULE,
                project_id=project['id'], run_id=run['id']):
            if event.get('type') == 'result':
                spec['result'] = event.get('text') or ''
                spec['is_error'] = bool(event.get('is_error'))
            elif event.get('type') == 'error':
                spec['is_error'] = True
                spec['result'] = str(event.get('message') or '実行エラー')
    except Exception as error:
        spec.update(is_error=True, result=str(error))
        await runs.update_run(run['id'], state='failed')
    await defer(row, spec)


async def lineage(run_id):
    runs = RunService()
    root = await runs.get_run(run_id)
    if not root:
        return []
    rows, frontier = [root], [run_id]
    while frontier:
        children = await asyncio.to_thread(lambda: runs.supabase.table('agent_runs').select('*')
            .in_('parent_run_id', frontier).execute())
        known = {r['id'] for r in rows}
        fresh = [r for r in children.data or [] if r['id'] not in known]
        rows.extend(fresh)
        frontier = [r['id'] for r in fresh]
    return rows


async def deliver(row):
    from app.services.command_center import execute, report_id
    spec = row['spec']
    runs = await lineage(spec['run_id'])
    for run in runs:
        if run['state'] == 'running' and RunService._is_run_stale(run):
            await RunService().update_run(run['id'], state='failed')
            run['state'] = 'failed'
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(spec['started_at'])).total_seconds()
    active = any(r['state'] in ('running', 'paused', 'awaiting_approval', 'awaiting_confirmation') for r in runs)
    if active:
        await defer(row, spec)
        return
    # Native background completions can create their successor just after the
    # empty initial turn exits. Do not finalize that placeholder as success.
    text = spec.get('result', '')
    latest = max(runs, key=lambda r: r['created_at'], default=None)
    failed = bool(spec.get('is_error') or (latest and latest['state'] == 'failed'))
    if failed and usable(text):
        text = '作業は失敗しました。\n' + text
    sb = ChatService().supabase
    for run in sorted(runs, key=lambda r: r['created_at'], reverse=True):
        events = await ProjectService().get_execution_events(run['project_id'], run_id=run['id'], limit=100)
        turns = list({e['turn_id'] for e in events if e.get('turn_id')})
        if turns:
            messages = await asyncio.to_thread(lambda: sb.table('chat_messages').select('content,created_at')
                .eq('room_id', row['room_id']).in_('ai_context->>turn_id', turns).eq('sender_type', 'ai')
                .order('created_at', desc=True).execute())
            found = next((m['content'] for m in messages.data or [] if usable(m['content'])), None)
            if found:
                text = found if run['state'] != 'failed' else '作業は失敗しました。\n' + found
                break
    if not usable(text):
        if age < 60:
            await defer(row, spec)
            return
        text = '作業の完了を確認できませんでした。実行結果が空かエラーのため、確認が必要です。'
        failed = True
    # Deliver the executor's own answer without a second model deciding
    # whether it deserves delivery. A finished turn is not proof that the
    # user's whole task succeeded; preserve the answer and actual run state.
    spec.pop('assessed_text', None)
    spec['outcome'] = 'failed' if failed else 'reported'
    await execute({'action': 'report', 'project_id': spec['origin_project_id'], 'task': text[:2800]},
                  row['room_id'], row['user_id'], report_message_id=report_id(row['id']))
    from app.services.followups import encode_watch_note
    spec['report'] = text
    await asyncio.to_thread(lambda: sb.table('pending_followups').update({
        'note': encode_watch_note('command_report', row['plain_note'], spec)}).eq('id', row['id']).execute())
    await asyncio.to_thread(mark_status, row['id'], 'failed' if spec.get('outcome') == 'failed' else 'done')
