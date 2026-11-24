"""Owner's circuit view. Join only on recorded session, room, job and run IDs."""
import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from app.paths import LIVE_ROOT
from app.services import command_job_state, voice_calls, voice_sideband
from app.agent.activity_line import activity_phrase
from app.services.run_service import background

VOICE = {
    'voice_configured': ('voice', '通話の指示文を準備'),
    'sideband_attached': ('voice', '音声接続'), 'route_chosen': ('router', '振り分け'),
    'route_answered': ('voice', '音声へ返答'), 'route_job_started': ('parallel', '作業を委譲'),
    'route_job_refused': ('error', '作業を開始できず'), 'route_failed': ('error', '振り分け失敗'),
    'sideband_failed': ('error', '音声接続でエラー'), 'sideband_closed': ('voice', '通話終了'),
    'chat_in_call': ('voice', 'チャットから通話に到着'),
    'function_done': ('tool', '道具の結果'), 'lookup_started': ('lookup', '調査開始'),
    'lookup_answered': ('lookup', '調査完了'), 'stage_page': ('stage', '画面表示'),
    'route_luna_round': ('backend', '担当が判断'), 'backend_completed': ('backend', '担当が返答'),
    'lookup_handed_over': ('parallel', '調査を引き継ぎ'), 'whisper_heard': ('voice', '音声を文字に変換'),
}
VOICE_ACTIVITY = {
    'voice_configured': '通話で使う指示文を読み込みました。',
    'sideband_attached': '通話の音声につながりました。',
    'sideband_closed': '通話が終わりました。',
    'route_answered': '振り分けの結果を通話のダンに返しました。',
    'route_job_started': '依頼を並行作業の担当に渡しました。',
    'lookup_handed_over': '調べものを並行作業の担当に引き継ぎました。',
    'lookup_started': '通話で頼まれたことを調べています。',
    'lookup_answered': '調べた結果を通話のダンに返しました。',
    'stage_page': '通話の画面に資料を表示しました。',
    'whisper_heard': '聞き取った言葉を文字にしました。',
    'route_luna_round': '判断役が依頼の進め方を確認しています。',
    'backend_completed': '判断役が結果を返しました。',
    'chat_in_call': 'チャットの言葉が通話に届きました。',
    'route_job_refused': '作業を担当に渡せませんでした。',
    'route_failed': '依頼の振り分けに失敗しました。',
    'sideband_failed': '音声につなげませんでした。',
}
STATE = {'running': '作業中', 'completed': '完了', 'failed': '失敗', 'cancelled': '停止',
         'superseded': '次の依頼へ移行', 'paused': '一時停止', 'queued': '受付', 'awaiting_confirmation': '確認待ち',
         'awaiting_approval': '承認待ち', 'succeeded': '完了'}
ROUTES = {'make': '制作', 'lookup': '調査', 'app': 'アプリ操作', 'site': 'サイト操作',
          'dan': 'ダンの開発', 'other': '担当に相談', 'reply': '返事', 'calendar': '予定',
          'show': '画面表示', 'status': '進み具合', 'end': '通話終了', 'clock': '時刻',
          'contact': '連絡', 'document': '文書', 'message': 'メッセージ', 'rooms': '部屋'}

def step(at, node, label, detail='', **extra):
    return dict(at=at, node=node, label=label, detail=detail or '', **extra)


@lru_cache(maxsize=4)
def _voice_file(path, stamp, size):
    by_room = {}
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            phase = row.get('phase')
            if phase not in VOICE and phase != 'speech_start':
                continue
            session = row.get('session_id')
            if not session or not row.get('at'):
                continue
            room = by_room.setdefault(row.get('room_id'), {})
            room.setdefault(session, []).append(row)
    return by_room


def voice_records(room):
    log = voice_sideband.LOG
    data = {}
    live = LIVE_ROOT / '.tmp' / log.name
    paths = dict.fromkeys(p.resolve() for base in (live, log) for p in (base.with_suffix('.previous.jsonl'), base))
    for path in paths:
        try:
            stat = path.stat()
            for sid, rows in _voice_file(path, stat.st_mtime_ns, stat.st_size).get(room, {}).items():
                data.setdefault(sid, []).extend(rows)
        except FileNotFoundError:
            continue
    return data


def voice_steps(rows, jobs):
    events = []
    for row in rows:
        phase, at = row['phase'], row['at']
        if phase == 'speech_start':
            owner = row.get('side') == 'owner'
            events.append(step(at, 'owner' if owner else 'voice', '本人の発話' if owner else 'ダンの発話',
                               activity='みきさんが話し始めました。' if owner else 'ダンが話し始めました。'))
            continue
        node, label = VOICE[phase]
        detail = row.get('route') or row.get('name') or row.get('model') or ''
        detail = ROUTES.get(detail, detail)
        calls = row.get('calls')
        if isinstance(calls, list):
            detail = ' · '.join(filter(None, [detail, *map(str, calls)]))
        activity = VOICE_ACTIVITY.get(phase, label)
        if phase == 'route_chosen':
            activity = f'依頼を「{detail}」に振り分けました。'
        if phase == 'function_done':
            node = 'sandbox'
            activity = row.get('activity') or activity_phrase(row.get('name') or '', {}) or '道具から結果が返りました。'
        events.append(step(at, node, label, detail, activity=activity, prompts=row.get('prompts', []),
                           ms=row.get('elapsed_ms', row.get('ms', row.get('transcribe_ms')))))
        prefix = row.get('job_id')
        if prefix and phase in ('route_job_started', 'lookup_handed_over'):
            matches = [j for j in jobs if j['id'].startswith(prefix)]
            if len(matches) == 1:
                events[-1]['handoff'] = matches[0].get('task')
                events.extend(job_steps(matches[0]))
    return sorted(events, key=lambda e: e['at'])


@lru_cache(maxsize=4096)
def job_origin(path, stamp):
    try:
        job = json.loads(path.read_bytes())
        if not job.get('internal_check'):
            return job.get('origin_room_id'), job.get('user_id'), job.get('created_at') or '', job.get('state'), (job.get('title') or job.get('task') or '')[:80]
    except (ValueError, OSError):
        pass
    return None, None, '', '', ''


def room_jobs(room, user):
    matches = []
    for path in command_job_state.ROOT.glob('*.json'):
        try:
            origin, who, date, _, _ = job_origin(path, path.stat().st_mtime_ns)
        except FileNotFoundError:
            continue
        if (origin, who) == (room, user):
            matches.append((date, path.stem))
    return [row for _, job_id in sorted(matches, reverse=True)
            if (row := command_job_state.read(job_id))]


def job_steps(job):
    events = [step(job['created_at'], 'parallel', '担当に渡った依頼文', job.get('task'),
                   activity='作業担当が依頼を受け取りました。', handoff=job.get('task'))]
    for e in job.get('events', []):
        kind = e.get('kind')
        labels = {'tool': '道具を使用', 'result': '結果', 'progress': '進み具合', 'error': 'エラー',
                  'confirmation': '確認待ち', 'control': '追加指示', 'waiting': '返答待ち'}
        if kind in labels and e.get('at'):
            detail = e.get('text') or ''
            activity = e.get('activity') or e.get('label') or detail
            if kind == 'tool' and not e.get('activity'):
                name, _, action = detail.partition(':')
                activity = activity_phrase(name, {'action': action}) or '道具を使いました。'
            events.append(step(e['at'], 'parallel', labels[kind], detail if kind != 'tool' else '',
                               activity=activity, ms=e.get('ms'), prompt=e.get('prompt')))
    return events


def owner_rooms(db, user):
    projects = (db.table('projects').select('room_id,title,metadata->editor,updated_at')
                .eq('user_id', user).order('updated_at', desc=True).execute().data or [])
    items = {p['room_id']: dict(id=p['room_id'], title=p['title'], editor=bool(p.get('editor')))
             for p in projects if p.get('room_id')}
    members = (db.table('chat_room_members').select('chat_rooms!inner(id,name,type)')
               .eq('user_id', user).eq('chat_rooms.type', 'dan').execute().data or [])
    for row in members:
        r = row['chat_rooms']
        items.setdefault(r['id'], dict(id=r['id'], title=r['name'], editor=False))
    return list(items.values())


def active_requests(db, user):
    rooms = {r['id']: r['title'] for r in owner_rooms(db, user)}
    if not rooms:
        return []
    items = []
    runs = (db.table('agent_runs').select('id,room_id,origin_message_id,created_at,metadata,state')
            .in_('state', ['running', 'queued', 'awaiting_confirmation', 'awaiting_approval'])
            .execute().data or [])
    runs = [r for r in runs if r['room_id'] in rooms and not background(r)]
    # A chat can continue after its HTTP stream closes. Its subsequent events
    # still identify the actual run or (in a plain room) the individual turn.
    from app.services.run_service import RECORD_ACTIVE_WINDOW
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=RECORD_ACTIVE_WINDOW)).isoformat()
    recent = (db.table('execution_events').select('room_id,run_id,turn_id,event_type,created_at')
              .gte('created_at', cutoff).order('seq', desc=True).execute().data or [])
    latest = {}
    for e in recent:
        if e['room_id'] in rooms and (e.get('run_id') or e.get('turn_id')):
            latest.setdefault((e['room_id'], e.get('run_id'), e.get('turn_id')), e)
    by_run = {}
    for (room, run_id, turn_id), e in latest.items():
        if run_id:
            by_run.setdefault(run_id, e)
        elif e['event_type'] != 'done':
            items.append(dict(room=room, id='turn/'+turn_id, kind='チャット', title=rooms[room],
                              at=e['created_at'], state='作業中'))
    active_ids = {r['id'] for r in runs}
    extra_ids = [rid for rid, e in by_run.items() if rid not in active_ids and e['event_type'] != 'done']
    if extra_ids:
        extra = (db.table('agent_runs').select('id,room_id,origin_message_id,created_at,metadata,state')
                 .in_('id', extra_ids).execute().data or [])
        runs += [r for r in extra if r['room_id'] in rooms and r['state'] == 'paused' and not background(r)]
    runs = [r for r in runs if by_run.get(r['id'], {}).get('event_type') != 'done']
    ids = [r['origin_message_id'] for r in runs if r.get('origin_message_id')]
    messages = {m['id']: m for m in db.table('chat_messages').select('id,room_id,content')
                .in_('id', ids).execute().data or []} if ids else {}
    for r in runs:
        room = r['room_id']
        msg = messages.get(r.get('origin_message_id')) or {}
        title = msg.get('content') if msg.get('room_id') == room else ''
        items.append(dict(room=room, id='chat/'+r['id'], kind='チャット', title=(title or rooms[room])[:80],
                          at=r['created_at'], state=STATE.get(r['state'], r['state'])))
    for path in voice_calls.ROOT.glob('*.json'):
        room = path.stem
        if room in rooms and (call := voice_calls.active(room)):
            items.append(dict(room=room, id='voice/'+call['session_id'], kind='通話', title=rooms[room],
                              at=datetime.fromtimestamp(call['at'], timezone.utc).isoformat(), state='通話中'))
    for path in command_job_state.ROOT.glob('*.json'):
        try:
            room, who, date, state, title = job_origin(path, path.stat().st_mtime_ns)
        except FileNotFoundError:
            continue
        if room in rooms and who == user and state in ('running', 'queued', 'awaiting_confirmation', 'waiting'):
            items.append(dict(room=room, id='job/'+path.stem, kind='並行作業', title=title or rooms[room],
                              at=date, state=STATE.get(state, state)))
    return sorted(items, key=lambda i: i['at'], reverse=True)


def chat_steps(rows):
    events = []
    for e in reversed(rows):
        meta = e.get('metadata') or {}
        labels = {'tool_use': '道具を使用', 'phase': '作業の進行', 'done':'作業終了','error':'エラー'}
        activity = meta.get('activity') or meta.get('done')
        if not activity and e['tool_name']:
            activity = activity_phrase(e['tool_name'])
        events.append(step(e['created_at'], 'chat', labels[e['event_type']], activity=activity or {'phase':'次の段階に進みました。', 'done':'チャットの作業が終わりました。',
                                                 'error':'作業中にエラーが起きました。'}.get(e['event_type'], '道具を使いました。'),
                           prompt=meta.get('skill_requested'), handoff=meta.get('handoff')))
    return events


def event_time(event):
    try:
        value = datetime.fromisoformat(str(event.get('at') or '').replace('Z', '+00:00'))
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp()
    except (ValueError, OverflowError):
        return float('-inf')


def chat_replies(db, room, turns):
    if not turns:
        return []
    rows = (db.table('chat_messages').select('created_at,content')
            .eq('room_id', room).eq('sender_type', 'ai').in_('ai_context->>turn_id', sorted(turns))
            .order('created_at').execute().data or [])
    return [step(m['created_at'], 'owner', 'ダンの返事', m['content'])
            for m in rows if (m.get('content') or '').strip()]


def snapshot(db, room, user, selected=''):
    runs = (db.table('agent_runs').select('id,origin_message_id,state,created_at,updated_at')
            .eq('room_id', room).order('created_at', desc=True).limit(50).execute().data or [])
    if selected.startswith('chat/') and not any('chat/'+r['id'] == selected for r in runs):
        from uuid import UUID
        try:
            run_id = str(UUID(selected[5:]))
        except ValueError:
            run_id = None
        if run_id:
            runs += (db.table('agent_runs').select('id,origin_message_id,state,created_at,updated_at')
                     .eq('room_id', room).eq('id', run_id).limit(1).execute().data or [])
    ids = [r['origin_message_id'] for r in runs if r.get('origin_message_id')]
    messages = {}
    if ids:
        messages = {m['id']: m for m in db.table('chat_messages').select('id,content,created_at')
                    .eq('room_id', room).in_('id', ids).execute().data or []}
    jobs = room_jobs(room, user)
    calls = voice_records(room)
    items = []
    for r in runs:
        msg = messages.get(r['origin_message_id']) or {}
        items.append(dict(id='chat/'+r['id'], at=r['created_at'], title=(msg.get('content') or 'チャットの作業')[:80],
                          state=STATE.get(r['state'], r['state']), kind='チャット', origin=r['origin_message_id']))
    for sid, rows in calls.items():
        items.append(dict(id='voice/'+sid, at=rows[0]['at'], title='音声の会話',
                          state='終了' if any(x['phase']=='sideband_closed' for x in rows) else '接続の記録', kind='音声'))
    for j in jobs:
        items.append(dict(id='job/'+j['id'], at=j['created_at'], title=(j.get('title') or j.get('task') or '担当の作業')[:80],
                          state=STATE.get(j['state'], j['state']), kind='並行作業'))
    standalone = {}
    # Plain rooms and follow-up messages can lack a run. Show recorded messages in order,
    # and keep without-run tool events separate instead of guessing who triggered them.
    recent = (db.table('chat_messages').select('id,sender_type,content,created_at')
              .eq('room_id', room).order('created_at', desc=True).limit(100).execute().data or [])
    current = None
    for m in reversed(recent):
        if m['sender_type'] in ('human','user'):
            if m['id'] in messages:
                current = None
                continue
            current = m['id']
            standalone[current] = []
            items.append(dict(id='message/'+current, origin=current, at=m['created_at'], title=(m['content'] or '発言')[:80],
                              state='履歴', kind='チャット'))
        if current and m['sender_type'] in ('human','user','dan','ai','assistant'):
            human = m['sender_type'] in ('human','user')
            if not human:
                standalone[current].append(step(m['created_at'], 'chat', '返事を書きました'))
            standalone[current].append(step(m['created_at'], 'owner',
                                            '本人の言葉' if human else 'ダンの返事', m['content']))
    items.sort(key=lambda x: x['at'], reverse=True)
    key = selected or (items[0]['id'] if items else '')
    events = []
    for run in runs:
        if key != 'chat/'+run['id']:
            continue
        msg = messages.get(run['origin_message_id'])
        if msg:
            events.append(step(msg['created_at'], 'owner', '本人から届いた言葉', msg['content']))
        events.append(step(run['created_at'], 'chat', 'チャットで受付'))
        rows = (db.table('execution_events').select('created_at,event_type,tool_name,tool_label,metadata,turn_id')
                .eq('room_id', room).eq('run_id', run['id']).in_('event_type',['tool_use','phase','done','error'])
                .order('seq', desc=True).limit(250).execute().data or [])
        events.extend(chat_steps(rows))
        events.extend(chat_replies(db, room, {r['turn_id'] for r in rows if r.get('turn_id')}))
        if run['state'] not in ('running','queued'):
            events.append(step(run['updated_at'], 'chat', STATE.get(run['state'],run['state'])))
        break
    if key.startswith('turn/'):
        from uuid import UUID
        try:
            turn_id = str(UUID(key[5:]))
        except ValueError:
            turn_id = None
        if turn_id:
            rows = (db.table('execution_events').select('created_at,event_type,tool_name,tool_label,metadata,turn_id')
                    .eq('room_id', room).eq('turn_id', turn_id).is_('run_id', 'null')
                    .in_('event_type', ['tool_use','phase','done','error']).order('seq', desc=True)
                    .limit(250).execute().data or [])
            events = chat_steps(rows) + chat_replies(db, room, {turn_id})
            if rows:
                items.insert(0, dict(id=key, at=events[0]['at'], title='チャットの作業', kind='チャット',
                                     state='完了' if rows[0]['event_type']=='done' else '作業中'))
    if key.startswith('message/'):
        events = standalone.get(key[8:], [])
    if key.startswith('voice/'):
        sid = key[6:]
        events = voice_steps(calls.get(sid, []), jobs)
        if sid in calls:
            transcript = (db.table('chat_messages').select('sender_type,content,created_at,ai_context')
                          .eq('room_id', room).eq('ai_context->>voice_session_id', sid)
                          .order('created_at').execute().data or [])
            for row in transcript:
                human = row['sender_type'] == 'human'
                text = (row.get('content') or '').removeprefix('🎙 ').strip()
                if text:
                    events.append(step(row['created_at'], 'owner', '聞き取った言葉' if human else 'ダンが話した言葉', text))
                    if human and (row.get('ai_context') or {}).get('audio_endpoint') == 'pin':
                        events.append(step(row['created_at'], 'pin', 'ピンから音声を入力'))
                        events.append(step(row['created_at'], 'audio', 'スマホの音声モードに届きました'))
    if key.startswith('job/'):
        events = next((job_steps(j) for j in jobs if j['id']==key[4:]), [])
    events.sort(key=event_time)
    return dict(items=items, selected=key, steps=events)
