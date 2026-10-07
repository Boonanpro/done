"""Work in one room can run in parallel (chat Dan and its parallel jobs). Two of them must not change the same thing at
the same moment: the same file, the PC screen, the phone. Whoever starts changing it first holds it until it is done;
the other waits for that one thing only and keeps the rest of its work going. The owner never arranges this.

Owners: 'job:<job id>' (a parallel job) or 'room:<room id>' (chat Dan's own turn in that room).
A job holds what it touched until the job ends. A room's turn holds it until the turn ends (released at the end of the
turn; a lock the turn could not release expires after ROOM_TTL without use).
Standard library only: the Claude hook (scripts/work_lock_hook.py) imports this file directly in a short-lived process.
"""
import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path.home() / '.dan' / 'command-jobs'
LOCKS = ROOT / 'locks'
ROOM_TTL = 20 * 60
WAIT_LIMIT = 15 * 60
TERMINAL = {'completed', 'failed', 'cancelled'}

_SKIP_PARTS = ('\\appdata\\local\\temp\\', '\\.claude\\', '\\.dan\\command-jobs\\', '\\dan-workspace\\jobs\\',
               '\\node_modules\\', '\\.next\\', '\\__pycache__\\', '\\.git\\')


def file_key(path, work_dir=''):
    """The lock name for a file, or '' when nobody else can be using it (temp, caches, a job's own folder)."""
    if not path:
        return ''
    full = os.path.normcase(os.path.abspath(str(path).replace('/', os.sep)))
    if work_dir and full.startswith(os.path.normcase(os.path.abspath(work_dir))):
        return ''
    if any(part in full + os.sep for part in _SKIP_PARTS):
        return ''
    return 'file:' + full


def tool_key(name, arguments):
    """Things only one piece of work can drive at a time, chosen from a Dan tool call."""
    if name == 'desktop':
        return 'device:desktop'
    if name == 'phone':
        return 'device:phone'
    if name in ('write_file', 'edit_file'):
        return file_key((arguments or {}).get('path') or (arguments or {}).get('file_path'),
                        os.environ.get('DAN_WORK_DIR', ''))
    return ''


def label(key):
    if key.startswith('file:'):
        return Path(key[5:]).name
    return {'device:desktop': 'PCの画面操作', 'device:phone': 'スマホ操作'}.get(key, key)


def _path(key):
    return LOCKS / (hashlib.sha1(key.encode('utf-8')).hexdigest() + '.json')


@contextmanager
def _exclusive():
    import msvcrt
    LOCKS.mkdir(parents=True, exist_ok=True)
    with (LOCKS / '.guard').open('a+b') as guard:
        if guard.tell() == 0:
            guard.write(b'0'); guard.flush()
        deadline = time.monotonic() + 10
        while True:
            try:
                guard.seek(0); msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('作業の順番の記録が混み合っています')
                time.sleep(.01)
        try:
            yield
        finally:
            guard.seek(0); msvcrt.locking(guard.fileno(), msvcrt.LK_UNLCK, 1)


def _job(job_id):
    try:
        return json.loads((ROOT / (job_id + '.json')).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _alive(record):
    owner = record.get('owner', '')
    if owner.startswith('job:'):
        job = _job(owner[4:])
        return bool(job) and job.get('state') not in TERMINAL
    return time.time() - record.get('touched', 0) < ROOM_TTL


def _read(key):
    try:
        return json.loads(_path(key).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def holder(key, owner):
    """The live record of someone else holding key, or None."""
    record = _read(key)
    if record and record.get('owner') != owner and _alive(record):
        return record
    return None


def try_acquire(key, owner, title=''):
    """Take key if free (or already ours). Returns None on success, else the other holder's record."""
    if not key or not owner:
        return None
    with _exclusive():
        other = holder(key, owner)
        if other:
            return other
        _path(key).write_text(json.dumps({'key': key, 'owner': owner, 'title': title[:80],
                                          'touched': time.time()}, ensure_ascii=False), encoding='utf-8')
        return None


def acquire(key, owner, title='', on_wait=None, limit=WAIT_LIMIT):
    """Wait until key is ours. on_wait(record) is called once when waiting starts. Returns None when held,
    otherwise the holder still in the way after `limit` seconds (the caller tells its model to work around it)."""
    started = time.monotonic()
    told = False
    while True:
        other = try_acquire(key, owner, title)
        if not other:
            return None
        if not told and on_wait:
            on_wait(other)
            told = True
        if time.monotonic() - started >= limit:
            return other
        time.sleep(2)


def release_owner(owner):
    """Everything this job or room turn holds becomes free."""
    if not owner or not LOCKS.exists():
        return
    with _exclusive():
        for path in LOCKS.glob('*.json'):
            try:
                if json.loads(path.read_text(encoding='utf-8')).get('owner') == owner:
                    path.unlink()
            except (OSError, ValueError):
                continue


def held_by(owner):
    if not LOCKS.exists():
        return []
    rows = []
    for path in LOCKS.glob('*.json'):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if record.get('owner') == owner:
            rows.append(record)
    return rows


def waiting_text(record):
    who = record.get('title') or ('チャットの会話' if record.get('owner', '').startswith('room:') else '別の作業')
    return f'「{who}」の完了待ち（{label(record.get("key", ""))}）'


def changed_while_waiting(key, record):
    """What to tell a piece of work that waited: the thing changed meanwhile, so look again before acting."""
    who = waiting_text(record).removesuffix(f'（{label(key)}）').removesuffix('の完了待ち')
    look = '画面を見直して' if key.startswith('device:') else 'ファイルを読み直して最新の内容を確かめて'
    return (f'{label(key)} は{who}が使い終わり、この作業の番になりました。待っている間に中身が変わっているので、'
            f'この操作はまだ行っていません。{look}から、やり直してください。')


def wait_limit(owner):
    """A job waits as long as it takes; chat Dan's own turn waits a minute, then is told, so the owner is not left waiting
    in silence (it can say so, or hand the change to a parallel job)."""
    return WAIT_LIMIT if owner.startswith('job:') else 60


def hook_settings():
    """--settings for Dan's Claude Code processes: take a file before writing it (scripts/work_lock_hook.py)."""
    hook = (Path(__file__).resolve().parents[2] / 'scripts' / 'work_lock_hook.py').as_posix()
    return json.dumps({'hooks': {'PreToolUse': [{'matcher': 'Write|Edit|MultiEdit|NotebookEdit', 'hooks': [
        {'type': 'command', 'command': f'python "{hook}"', 'timeout': WAIT_LIMIT + 60}]}]}})


def current_owner():
    """The owner of the process this runs in (set by whoever started the CLI or the tool host)."""
    job = os.environ.get('DAN_COMMAND_JOB_ID')
    if job:
        return 'job:' + job
    return os.environ.get('DAN_LOCK_OWNER') or ('room:' + os.environ['DAN_SESSION_ID'] if os.environ.get('DAN_SESSION_ID') else '')


def current_title():
    job = os.environ.get('DAN_COMMAND_JOB_ID')
    if job:
        s = _job(job) or {}
        return (s.get('title') or s.get('task') or '')[:60]
    return 'チャットの会話'


def _job_state():
    """command_job_state without importing the app package (the hook process must start fast)."""
    import sys
    module = sys.modules.get('app.services.command_job_state')
    if module is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location('_dan_job_state', Path(__file__).with_name('command_job_state.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def note_waiting(owner, record):
    """Show on the job (the room's work list) what it is waiting for; cleared by clear_waiting."""
    if not owner.startswith('job:'):
        return
    try:
        _job_state().publish(owner[4:], 'waiting', waiting_text(record), waiting_for=waiting_text(record))
    except Exception:
        pass


def clear_waiting(owner):
    if not owner.startswith('job:'):
        return
    try:
        state = _job_state()
        if (state.read(owner[4:]) or {}).get('waiting_for'):
            state.change(owner[4:], lambda s: s.update(waiting_for=None))
    except Exception:
        pass
