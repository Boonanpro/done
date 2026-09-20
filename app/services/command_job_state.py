"""Local durable state shared by Core, voice API and isolated job MCP workers."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import uuid

ROOT = Path.home() / '.dan' / 'command-jobs'
TERMINAL = {'completed', 'failed', 'cancelled'}

def now():
    return datetime.now(timezone.utc).isoformat()

def path(job_id):
    return ROOT / (str(uuid.UUID(job_id)) + '.json')

@contextmanager
def locked(job_id):
    import msvcrt
    ROOT.mkdir(parents=True, exist_ok=True)
    with path(job_id).with_suffix('.lock').open('a+b') as lock:
        if lock.tell() == 0:
            lock.write(b'0'); lock.flush()
        deadline = time.monotonic() + 10
        while True:
            try:
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline: raise TimeoutError('作業状態の更新が混み合っています')
                time.sleep(.01)
        try: yield
        finally:
            lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)

def read(job_id):
    try: return json.loads(path(job_id).read_text(encoding='utf-8'))
    except FileNotFoundError: return None

def change(job_id, fn):
    with locked(job_id):
        state = read(job_id)
        result = fn(state)
        if result is not None: state = result
        state['updated_at'] = now()
        temp = path(job_id).with_suffix('.tmp')
        temp.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        # Windows readers briefly open the destination without delete sharing.
        # Retry the atomic rename, not fn(state): repeating the state mutation
        # could duplicate a control event or consume an approval twice.
        deadline=time.monotonic()+2
        while True:
            try:
                os.replace(temp, path(job_id));break
            except PermissionError:
                if time.monotonic()>=deadline:raise
                time.sleep(.01)
        return state

def event(state, kind, text):
    seq = state.get('seq', 0) + 1
    state['seq'] = seq
    state.setdefault('events', []).append({'seq': seq, 'kind': kind, 'text': text[:3000], 'at': now()})
    state['events'] = state['events'][-40:]

def publish(job_id, kind, text, **fields):
    def update(s):
        s.update(fields); event(s, kind, text)
    return change(job_id, update)

def create(job_id, **fields):
    def init(s):
        return s or {'id': job_id, 'state': 'queued', 'revision': 0, 'applied_revision': 0,
                     'inputs': [], 'events': [], 'seq': 0, 'created_at': now(), **fields}
    return change(job_id, init)

def owned(job_id, user_id, origin_room_id):
    s = read(job_id)
    if not s or s['user_id'] != user_id or s['origin_room_id'] != origin_room_id:
        raise ValueError('この作業へのアクセス権がありません')
    return s

def browser_room(job_id):
    """Reuse this user's idle browser without sharing it with parallel jobs."""
    job = read(job_id)
    lease = str(uuid.uuid5(uuid.NAMESPACE_URL,'dan-browser:'+job['user_id']+':'+job['origin_room_id']))
    with locked(lease):
        job = read(job_id)
        if job.get('browser_room'): return job['browser_room']
        rows = [read(p.stem) for p in ROOT.glob('*.json')]
        rows = [s for s in rows if s and s.get('user_id')==job['user_id'] and s.get('origin_room_id')==job['origin_room_id']]
        from app.services.browser_lifecycle import profile_for_room
        for previous in rows:
            legacy = 'voice-job-'+previous['id']
            if not previous.get('browser_room') and profile_for_room(legacy).exists():
                previous['browser_room'] = legacy
        busy = {s.get('browser_room') for s in rows if s['state'] not in TERMINAL}
        idle = sorted((s for s in rows if s.get('browser_room') and s['browser_room'] not in busy),key=lambda s:s['updated_at'],reverse=True)
        room = idle[0]['browser_room'] if idle else 'voice-job-'+job_id
        change(job_id,lambda s:s.update(browser_room=room))
        return room

def control(job_id, user_id, origin_room_id, action, text='', confirmation_id=None):
    owned(job_id, user_id, origin_room_id)
    def update(s):
        if s['state'] in TERMINAL: raise ValueError('この作業は終了しています。結果を確認してください')
        if action == 'confirm':
            proposal = s.get('confirmation')
            if not proposal or proposal['id'] != confirmation_id or proposal['revision'] != s['revision']:
                raise ValueError('確認内容が更新されています。最新の確認内容を提示してください')
            if s['state'] != 'awaiting_confirmation': raise ValueError('現在は確定の確認待ちではありません')
            s['approved'] = proposal['id']; s['state'] = 'running'
            event(s, 'control', '提示した内容への本人の承認を受け付けました')
            return
        if action not in {'update', 'pause', 'resume', 'cancel'}: raise ValueError('未対応の作業操作です')
        if action == 'update' and not text.strip(): raise ValueError('追加指示が必要です')
        s['revision'] += 1
        s.pop('approved', None); s.pop('confirmation', None)
        s['state'] = 'cancelled' if action == 'cancel' else 'paused' if action == 'pause' else 'running'
        if action in {'update', 'resume'}:
            s['inputs'].append({'revision': s['revision'], 'text': text or '作業を再開してください。確定操作は改めて本人への確認が必要です。'})
        else:
            s['applied_revision'] = s['revision']
        event(s, 'control', {'update':'追加指示を受け付けました（反映待ち）', 'pause':'一時停止しました',
                             'resume':'再開を受け付けました', 'cancel':'停止しました'}[action])
    return change(job_id, update)

def public(s):
    return {k:s.get(k) for k in ('id','task','state','revision','applied_revision','events','seq',
        'confirmation','result','error','created_at','updated_at','run_id','room_id','report_message_id','current_tool','last_tool','last_observation')}

def list_owned(user_id, origin_room_id):
    if not ROOT.exists(): return []
    rows = []
    for p in ROOT.glob('*.json'):
        s = read(p.stem)
        if s and s.get('user_id') == user_id and s.get('origin_room_id') == origin_room_id: rows.append(s)
    return sorted(rows, key=lambda s:s['created_at'], reverse=True)[:20]
