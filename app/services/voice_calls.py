"""Which rooms have a call going, and what the owner sends to the chat during one.

Dan is one person (owner, 2026-10-01): while the owner is on a call with Dan, what they type or paste into that room's
chat goes to the Dan on the call, not to a second Dan started by the chat. The call runs in the sandbox process (the
sideband), the chat's send in the core: they meet here, in files.

    ~/.dan/voice-calls/<room>.json          the call: session id, the sideband's pid, when it began
    ~/.dan/voice-calls/<room>.inbox.jsonl   what the owner sent to the chat during it, one line each

A call whose process is gone is not a call (a crash leaves the file; the pid tells).
"""
import json
import os
import re
import time
from pathlib import Path

ROOT = Path.home()/'.dan'/'voice-calls'


def _name(room_id):
    return re.sub(r'[^A-Za-z0-9-]', '_', room_id or '')


def _call_file(room_id):
    return ROOT/(_name(room_id)+'.json')


def _inbox(room_id):
    return ROOT/(_name(room_id)+'.inbox.jsonl')


def begin(room_id, session_id):
    if not room_id: return
    ROOT.mkdir(parents=True, exist_ok=True)
    _inbox(room_id).unlink(missing_ok=True)
    _call_file(room_id).write_text(json.dumps({'session_id': session_id, 'pid': os.getpid(), 'at': time.time()}), encoding='utf-8')


def end(room_id, session_id):
    path = _call_file(room_id)
    try:
        if json.loads(path.read_text(encoding='utf-8')).get('session_id') == session_id:
            path.unlink(missing_ok=True)
            _inbox(room_id).unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def active(room_id):
    """The call in this room, or None."""
    try:
        call = json.loads(_call_file(room_id).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    try:
        import psutil
        alive = psutil.pid_exists(int(call.get('pid') or 0))
    except Exception:
        alive = True
    return call if alive else None


def deliver(room_id, text):
    """Hand what the owner sent to the call in this room."""
    with _inbox(room_id).open('a', encoding='utf-8') as out:
        out.write(json.dumps({'at': time.time(), 'text': text}, ensure_ascii=False)+chr(10))


def take(room_id, done):
    """What arrived after the first `done` lines. Returns (new texts, new count)."""
    try:
        lines = _inbox(room_id).read_text(encoding='utf-8').splitlines()
    except OSError:
        return [], done
    texts = []
    for line in lines[done:]:
        try: texts.append(json.loads(line)['text'])
        except (ValueError, KeyError): continue
    return texts, len(lines)
