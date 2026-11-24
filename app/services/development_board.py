"""Development proposals and observations attached to boxes on the owner's architecture diagram."""
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from app.services import prompt_store

STAGES = ('提案', '作業中', '確認結果')


def connection():
    directory = prompt_store.root() / '.board'
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / 'development.sqlite3', timeout=3)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS changes (id INTEGER PRIMARY KEY, node TEXT, phase TEXT, text TEXT, at TEXT)')
    return db


def add(node, phase, text):
    if phase not in STAGES or not node or not text.strip() or len(text) > 1600:
        raise ValueError('対象の箱・段階・1600字以内の内容を指定してください。')
    with closing(connection()) as db, db:
        db.execute('INSERT INTO changes(node, phase, text, at) VALUES(?,?,?,?)',
                   (node, phase, text.strip(), datetime.now(timezone.utc).isoformat()))


def recent():
    with closing(connection()) as db:
        return [dict(row) for row in db.execute('SELECT * FROM changes ORDER BY id DESC LIMIT 160')]
