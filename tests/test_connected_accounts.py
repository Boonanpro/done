"""Connected accounts (2026-09-25): any provider, any number per user, one default writer per capability; add, reconnect,
replace, remove; signed OAuth state. The Supabase table is replaced by an in-memory fake."""
import itertools

import pytest

from app.services import connected_accounts as ca


class FakeTable:
    def __init__(self, rows):
        self.rows, self.filters, self.op, self.payload = rows, [], 'select', None

    def select(self, *_a, **_k): self.op = 'select'; return self
    def eq(self, k, v): self.filters.append((k, v)); return self
    def order(self, *_a, **_k): return self
    def update(self, payload): self.op, self.payload = 'update', payload; return self
    def insert(self, payload): self.op, self.payload = 'insert', payload; return self
    def delete(self): self.op = 'delete'; return self

    def execute(self):
        match = [r for r in self.rows if all(r.get(k) == v for k, v in self.filters)]
        if self.op == 'insert':
            row = {'id': f'id{next(IDS)}', 'label': None, 'created_at': str(next(IDS)), **self.payload}
            self.rows.append(row); match = [row]
        elif self.op == 'update':
            for r in match: r.update(self.payload)
        elif self.op == 'delete':
            for r in match: self.rows.remove(r)
        return type('R', (), {'data': [dict(r) for r in match]})()


IDS = itertools.count(1)


@pytest.fixture
def db(monkeypatch):
    rows = []
    client = type('C', (), {'table': lambda self, name: FakeTable(rows)})()
    monkeypatch.setattr(ca, '_db', lambda: client)
    monkeypatch.setattr(ca, 'encrypt_data', lambda s: 'enc:' + s)
    monkeypatch.setattr(ca, 'decrypt_data', lambda s: s[4:])
    return rows


def test_two_accounts_of_one_provider_live_side_by_side_and_the_first_is_the_default(db):
    a = ca.save('u', 'google', 'shub@gmail.com', ['calendar'], {'token': 1})
    b = ca.save('u', 'google', '0aw@gmail.com', ['calendar'], {'token': 2})
    assert {r['account'] for r in ca.list_accounts('u', 'calendar')} == {'shub@gmail.com', '0aw@gmail.com'}
    assert ca.default_account('u', 'calendar')['id'] == a['id']
    assert ca.find('u', 'calendar', '0aw')['id'] == b['id'] and ca.token('u', b['id']) == {'token': 2}


def test_reconnecting_the_same_account_refreshes_it_and_replacing_moves_the_default(db):
    a = ca.save('u', 'google', 'shub@gmail.com', ['calendar'], {'token': 1})
    again = ca.save('u', 'google', 'shub@gmail.com', ['calendar'], {'token': 9})
    assert again['id'] == a['id'] and len(db) == 1 and ca.token('u', a['id']) == {'token': 9}
    c = ca.save('u', 'microsoft', 'me@outlook.com', ['calendar'], {'token': 3}, replace_id=a['id'])
    assert [r['account'] for r in ca.list_accounts('u', 'calendar')] == ['me@outlook.com']
    assert ca.default_account('u', 'calendar')['id'] == c['id']


def test_removing_the_default_passes_it_on(db):
    a = ca.save('u', 'google', 'shub@gmail.com', ['calendar'], {'token': 1})
    b = ca.save('u', 'google', '0aw@gmail.com', ['calendar'], {'token': 2})
    ca.set_default('u', b['id'], 'calendar')
    assert ca.default_account('u', 'calendar')['id'] == b['id']
    ca.remove('u', b['id'])
    assert ca.default_account('u', 'calendar')['id'] == a['id']


def test_oauth_state_is_signed_and_expires(monkeypatch):
    state = ca.sign_state({'u': 'user-1', 'p': 'google'})
    assert ca.read_state(state)['u'] == 'user-1'
    body, mac = state.rsplit('.', 1)
    assert ca.read_state(body + '.' + '0' * len(mac)) is None      # forged
    assert ca.read_state('user-1') is None                           # the old bare user id
    monkeypatch.setattr(ca, 'STATE_SECONDS', -1)
    assert ca.read_state(ca.sign_state({'u': 'x'})) is None          # expired
