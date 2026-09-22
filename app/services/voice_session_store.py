"""Restart recovery for room intake state; never executes or retries tools."""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB = Path.home() / '.dan' / 'voice-sessions.sqlite3'
TTL = 7200


@contextmanager
def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=3)
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL, data TEXT NOT NULL)')
            yield db
    finally:
        db.close()


def save(session_id, state):
    if not state.get('room_id') or session_id.startswith('pending-'):
        return
    data = {k: state[k] for k in ('user_id', 'room_id', 'instructions', 'tools', 'history')}
    data['pending'] = state['agent'].pending
    with connect() as db:
        db.execute('DELETE FROM sessions WHERE expires < ?', (time.time(),))
        db.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?, ?, ?)',
                   (session_id, state['user_id'], time.time()+TTL, json.dumps(data, ensure_ascii=False)))


def load(session_id, user_id):
    with connect() as db:
        row = db.execute('SELECT data FROM sessions WHERE id=? AND owner=? AND expires>?',
                         (session_id, user_id, time.time())).fetchone()
    return json.loads(row[0]) if row else None


def remove(session_id, user_id):
    with connect() as db:
        db.execute('DELETE FROM sessions WHERE id=? AND owner=?', (session_id, user_id))
