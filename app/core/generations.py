"""Durable routing for overlapping Core/Sandbox generations.

The public gateway and browser/event services stay put. Each new release owns
its code directory and ports; a room with a live turn and a call with an open
session keep their owner. Health checks precede the atomic active pointer swap.
"""
import json
import os
from pathlib import Path
import tempfile

import psutil

ROOT = Path(os.environ.get('DAN_GENERATIONS_ROOT') or Path.home() / '.dan' / 'generations')


def read(name):
    try:
        return json.loads((ROOT / (name + '.json')).read_text())
    except FileNotFoundError:
        return None


def write(name, value):
    ROOT.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.routing-', dir=ROOT)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f); f.flush(); os.fsync(f.fileno())
        os.replace(temporary, ROOT / (name + '.json'))
    finally:
        Path(temporary).unlink(missing_ok=True)


def identity():
    p = psutil.Process()
    return {'pid': p.pid, 'created': p.create_time()}


def living(owner):
    try:
        p = psutil.Process(owner['pid'])
        return p.create_time() == owner['created'] and p.status() != psutil.STATUS_ZOMBIE
    except (TypeError, KeyError, psutil.Error):
        return False


def key(kind, value):
    import hashlib
    return kind + '-' + hashlib.sha256(str(value).encode()).hexdigest()


def track(kind, value, active=True, **extra):
    generation = os.environ.get('DAN_GENERATION')
    if not generation or not value:
        return
    name = key(kind, value)
    if active:
        write(name, dict(generation=generation, owner=identity(), **extra))
    else:
        saved = read(name)
        if saved and saved.get('generation') == generation:
            (ROOT / (name + '.json')).unlink(missing_ok=True)


def owner(kind, value):
    saved = read(key(kind, value)) if value else None
    if saved and living(saved.get('owner')):
        return read('release-' + saved['generation'])
    return None


def run_changed(row):
    if (row.get('metadata') or {}).get('started_by') == 'command_center':
        return
    # Only the process that created a turn may acquire its room. Other writers
    # may publish its result; they must not take ownership of that room.
    process = (row.get('metadata') or {}).get('process_owner')
    if process != identity():
        return
    from app.services.run_service import ACTIVE_RUN_STATES
    if row.get('state') not in ACTIVE_RUN_STATES:
        saved = read(key('room', row.get('room_id')))
        if not saved or saved.get('run_id') != row.get('id'):
            return
    track('room', row.get('room_id'), row.get('state') in ACTIVE_RUN_STATES, run_id=row.get('id'))


def target(kind, room_id=None, session_id=None):
    chosen = owner('call', session_id) or owner('voice-room', room_id) or owner('room', room_id) or read('active')
    return (chosen or {'core': 9000, 'sandbox': 8000})[kind]


def reserve_room(room_id):
    """Serialize pointer selection with an in-flight message before a run exists."""
    if not room_id:
        return None
    from app.services.job_process import lease
    import time
    name = key('room', room_id)
    deadline = time.monotonic() + 5
    while True:
        with lease(ROOT / (name + '.lock')) as locked:
            if locked:
                chosen = owner('room', room_id) or read('active')
                if not chosen: return None
                if not owner('room', room_id):
                    import uuid
                    token = uuid.uuid4().hex
                    write(name, {'generation': chosen['id'], 'owner': chosen['owner'], 'reservation': token})
                    return chosen, token
                return chosen, None
        if time.monotonic() >= deadline: raise TimeoutError('Room routing is busy')
        time.sleep(.01)


def release_room(room_id, token):
    if not token: return
    from app.services.job_process import lease
    name = key('room', room_id)
    with lease(ROOT / (name + '.lock')) as locked:
        if not locked: return
        saved = read(name)
        if saved and saved.get('reservation') == token:
            (ROOT / (name + '.json')).unlink(missing_ok=True)


def legacy_room_alive(room_id):
    saved = read(key('legacy', room_id)) if room_id else None
    if not saved: return False
    from app.services.supabase_client import get_supabase_client
    from app.services.run_service import ACTIVE_RUN_STATES
    try:
        rows = get_supabase_client().client.table('agent_runs').select('state').in_('id', saved['runs']).execute().data
        active = any(row['state'] in ACTIVE_RUN_STATES for row in rows or [])
    except Exception:
        return True  # A failed lookup cannot transfer a potentially live turn.
    if not active: (ROOT / (key('legacy', room_id) + '.json')).unlink(missing_ok=True)
    return active
