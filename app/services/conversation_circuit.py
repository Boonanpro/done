"""Owner's circuit view. Join only on recorded session, room, job and run IDs."""
import json
from functools import lru_cache
from pathlib import Path

from app.paths import LIVE_ROOT
from app.services import command_job_state, voice_sideband

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
            events.append(step(at, 'owner' if owner else 'voice', '本人の発話' if owner else 'ダンの発話'))
            continue
        node, label = VOICE[phase]
        detail = row.get('route') or row.get('name') or row.get('model') or ''
        detail = ROUTES.get(detail, detail)
        calls = row.get('calls')
        if isinstance(calls, list):
            detail = ' · '.join(filter(None, [detail, *map(str, calls)]))
        events.append(step(at, node, label, detail, prompts=row.get('prompts', []), ms=row.get('elapsed_ms', row.get('ms'))))
        prefix = row.get('job_id')
        if prefix and phase in ('route_job_started', 'lookup_handed_over'):
            matches = [j for j in jobs if j['id'].startswith(prefix)]
            if len(matches) == 1:
                events.extend(job_steps(matches[0]))
    return sorted(events, key=lambda e: e['at'])


@lru_cache(maxsize=4096)
def job_origin(path, stamp):
    try:
        job = json.loads(path.read_bytes())
        if not job.get('internal_check'):
            return job.get('origin_room_id'), job.get('user_id'), job.get('created_at') or ''
    except (ValueError, OSError):
        pass
    return None, None, ''


def room_jobs(room, user):
    matches = []
    for path in command_job_state.ROOT.glob('*.json'):
        try:
            origin, who, date = job_origin(path, path.stat().st_mtime_ns)
        except FileNotFoundError:
            continue
        if (origin, who) == (room, user):
            matches.append((date, path.stem))
    return [row for _, job_id in sorted(matches, reverse=True)
            if (row := command_job_state.read(job_id))]


def job_steps(job):
    events = [step(job['created_at'], 'parallel', '担当に渡った依頼文', job.get('task'))]
    for e in job.get('events', []):
        kind = e.get('kind')
        labels = {'tool': '道具を使用', 'result': '結果', 'progress': '進み具合', 'error': 'エラー',
                  'confirmation': '確認待ち', 'control': '追加指示', 'waiting': '返答待ち'}
        if kind in labels and e.get('at'):
            events.append(step(e['at'], 'error' if kind == 'error' else 'parallel', labels[kind], e.get('label') or e.get('text')))
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


def snapshot(db, room, user, selected=''):
    runs = (db.table('agent_runs').select('id,origin_message_id,state,created_at,updated_at')
            .eq('room_id', room).order('created_at', desc=True).limit(50).execute().data or [])
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
            standalone[current].append(step(m['created_at'], 'owner' if human else 'chat',
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
        rows = (db.table('execution_events').select('created_at,event_type,tool_name,tool_label,metadata')
                .eq('room_id', room).eq('run_id', run['id']).in_('event_type',['tool_use','phase','done','error'])
                .order('seq', desc=True).limit(250).execute().data or [])
        for e in reversed(rows):
            meta = e.get('metadata') or {}
            labels = {'tool_use': '道具を使用', 'phase': '作業の進行', 'done':'作業終了','error':'エラー'}
            events.append(step(e['created_at'], 'tool' if e['tool_name'] else 'chat', e.get('tool_label') or labels[e['event_type']],
                               meta.get('activity') or e['tool_name'], prompt=meta.get('skill_requested')))
        if run['state'] not in ('running','queued'):
            events.append(step(run['updated_at'], 'chat', STATE.get(run['state'],run['state'])))
        break
    if key.startswith('message/'):
        events = standalone.get(key[8:], [])
    if key.startswith('voice/'):
        events = voice_steps(calls.get(key[6:], []), jobs)
    if key.startswith('job/'):
        events = next((job_steps(j) for j in jobs if j['id']==key[4:]), [])
    return dict(items=items, selected=key, steps=events)

