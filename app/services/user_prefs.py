"""The user's own wishes about how Dan behaves ("こういうのはいらない", "こういう時は電話して", "これはしないで"),
kept per user and read where the behaviour is decided (owner, 2026-10-02: every user wants different things, and what
they say once must hold from then on). The inbox judge reads the 連絡 ones first.

Kept per user, encrypted: ~/.dan/prefs/<user>.json = {items: [{id, scope, text, at}]}. Nothing of one user reaches another.
"""
import json
import os
import threading
import time
import uuid
from pathlib import Path

ROOT = Path.home()/'.dan'/'prefs'
SCOPES = ('連絡', '電話', '全般')
_lock = threading.Lock()


def _file(user_id):
    return ROOT/f'{user_id}.json'


def _load(user_id):
    path = _file(user_id)
    if not user_id or not path.exists():
        return {'items': []}
    from app.services.encryption import decrypt_data
    try:
        return json.loads(decrypt_data(path.read_text(encoding='utf-8').strip()))
    except Exception:
        return {'items': []}


def _save(user_id, data):
    from app.services.encryption import encrypt_data
    ROOT.mkdir(parents=True, exist_ok=True)
    temp = _file(user_id).with_suffix('.tmp')
    temp.write_text(encrypt_data(json.dumps(data, ensure_ascii=False)), encoding='utf-8')
    os.replace(temp, _file(user_id))


def items(user_id, scopes=None):
    rows = _load(user_id).get('items') or []
    return [r for r in rows if not scopes or r.get('scope') in scopes]


def add(user_id, scope, text):
    row = {'id': uuid.uuid4().hex[:8], 'scope': scope if scope in SCOPES else '全般', 'text': text.strip()[:500], 'at': time.time()}
    with _lock:
        data = _load(user_id); data['items'] = (data.get('items') or []) + [row]; _save(user_id, data)
    return row


def remove(user_id, pref_id):
    with _lock:
        data = _load(user_id); before = len(data.get('items') or [])
        data['items'] = [r for r in data.get('items') or [] if r.get('id') != pref_id]; _save(user_id, data)
    return before != len(data['items'])


TOOL = {
    'name': 'preference',
    'description': ('本人の希望（ダンの振る舞いについて「こういうのはいらない」「こういう時はこうして」「これはしないで」）を、本人ごとに残す・見る・消す。'
                    '本人がそう言ったら、その場で add する（言い回しは本人の意図が分かる短い文に。例: 「銀行や証券のお知らせメールは知らせなくていい」）。'
                    '残した希望は、届いた連絡の判断などが毎回読んで従う。前の希望と食い違う時は古い方を remove する。'
                    'scope: 連絡＝届いたメール・SNS などを知らせるかどうか／電話＝ダンから電話するかどうか／全般＝それ以外。'),
    'input_schema': {'type': 'object', 'properties': {
        'action': {'type': 'string', 'enum': ['add', 'list', 'remove']},
        'scope': {'type': 'string', 'enum': list(SCOPES)},
        'text': {'type': 'string', 'description': 'add: 本人の希望'},
        'id': {'type': 'string', 'description': 'remove: 消す希望の id（list で分かる）'},
    }, 'required': ['action'], 'additionalProperties': False},
}


async def tool(params):
    user_id = os.environ.get('DAN_USER_ID', '')
    if not user_id:
        return {'success': False, 'error': 'user unknown'}
    action = params.get('action')
    if action == 'add':
        text = str(params.get('text') or '').strip()
        if not text:
            return {'success': False, 'error': 'text が空'}
        row = add(user_id, params.get('scope') or '全般', text)
        return {'success': True, 'output': f'残した（{row["scope"]} / id {row["id"]}）: {row["text"]}'}
    if action == 'remove':
        return {'success': remove(user_id, str(params.get('id') or '')), 'output': '消した' if params.get('id') else 'id が要る'}
    rows = items(user_id, [params['scope']] if params.get('scope') else None)
    return {'success': True, 'output': '\n'.join(f'{r["id"]} [{r["scope"]}] {r["text"]}' for r in rows) or '本人の希望はまだない'}
