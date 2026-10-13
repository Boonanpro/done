"""The same answers with fewer database requests (2026-10-13). The database ran out of its disk allowance and stopped for
30 minutes; three things were asking it far more than their answers needed:
the outside-contact list (17 requests for 5 rooms, re-read by the phone app every 30 seconds), the open chat's room info
(3 requests every 3 seconds), and the CLI session id (written again on every system event)."""
import asyncio
import types

import pytest

from app.agent import cli_runner
from app.api import collab_routes
from app.services import collab_service
from app.services.project_service import ProjectService

ROOM = dict(owner_id='u', title='窓口', status='active', ai_auto_assist=False,
            created_at='2026-09-01T00:00:00+00:00', updated_at='2026-09-01T00:00:00+00:00')
MESSAGE = dict(sender_type='guest', sender_name='客', content='見積もりください', metadata={}, created_at='2026-09-19T11:57:13.18+00:00')


class ListService:
    """The list's sources, recording what was asked."""
    def __init__(self, owned, as_guest=()):
        self.owned, self.as_guest, self.asked = owned, list(as_guest), []

    async def list_rooms_with_summary(self, user_id):
        self.asked.append('rooms with summary')
        return self.owned

    async def list_guest_rooms(self, user_id):
        self.asked.append('rooms joined as a guest')
        return self.as_guest

    async def summaries_of(self, ids):
        self.asked.append('summaries of ' + ','.join(ids))
        return {i: {'id': i, 'collab_invites': [{'status': 'joined'}], 'last': [], 'last_guest': []} for i in ids}

    async def unread_count_for_owner(self, room):
        self.asked.append('unread count of ' + room['id'])
        return 3

    unread_count_from_summary = collab_service.CollabService.unread_count_from_summary


def listed(service):
    user = types.SimpleNamespace(user_id='u')
    return asyncio.run(collab_routes.list_rooms(user=user, service=service)).rooms


def test_the_list_is_read_with_the_rooms_and_asks_nothing_per_room():
    read = dict(ROOM, id='read', owner_last_read_at='2026-09-19T13:17:13.5+00:00', last=[MESSAGE], last_guest=[{'created_at': MESSAGE['created_at']}],
                collab_invites=[{'status': 'joined'}, {'status': 'joined'}, {'status': 'pending'}])
    empty = dict(ROOM, id='empty', owner_last_read_at=None, last=[], last_guest=[], collab_invites=[])
    service = ListService([read, empty])
    rooms = {r.id: r for r in listed(service)}
    assert service.asked == ['rooms with summary', 'rooms joined as a guest']
    assert (rooms['read'].guest_count, rooms['read'].last_message, rooms['read'].unread_count) == (2, '見積もりください', 0)
    assert (rooms['empty'].guest_count, rooms['empty'].last_message, rooms['empty'].unread) == (0, None, False)


def test_the_unread_count_is_asked_only_where_a_guest_wrote_after_the_owner_last_read():
    unread = dict(ROOM, id='unread', owner_last_read_at='2026-09-19T11:57:13.1+00:00', last=[MESSAGE], last_guest=[{'created_at': MESSAGE['created_at']}], collab_invites=[])
    never_read = dict(ROOM, id='never', owner_last_read_at=None, last=[MESSAGE], last_guest=[{'created_at': MESSAGE['created_at']}], collab_invites=[])
    service = ListService([unread, never_read])
    rooms = {r.id: r for r in listed(service)}
    assert sorted(a for a in service.asked if a.startswith('unread')) == ['unread count of never', 'unread count of unread']
    assert rooms['unread'].unread_count == 3 and rooms['unread'].unread and rooms['never'].unread_count == 3


def test_rooms_joined_as_a_guest_get_their_summary_in_one_more_request():
    service = ListService([], as_guest=[dict(ROOM, id='g1', _invite_token='t'), dict(ROOM, id='g2', _invite_token='t')])
    rooms = listed(service)
    assert service.asked == ['rooms with summary', 'rooms joined as a guest', 'summaries of g1,g2']
    assert [r.guest_count for r in rooms] == [1, 1]


def test_database_timestamps_with_a_shortened_fraction_compare_by_time():
    """".18" is 180 ms, later than ".1"; as text "…13.18+00:00" also sorts after "…13.1+00:00", but "…13+00:00" does not."""
    assert collab_service._db_time('2026-09-19T11:57:13.18+00:00') > collab_service._db_time('2026-09-19T11:57:13.1+00:00')
    assert collab_service._db_time('2026-09-19T11:57:13.5+00:00') > collab_service._db_time('2026-09-19T11:57:13+00:00')
    assert collab_service._db_time('2026-09-19T11:57:13Z') == collab_service._db_time('2026-09-19T11:57:13.000000+00:00')


class Table:
    """One table of a database that records each request it executes."""
    def __init__(self, db, name):
        self.db, self.name, self.selected = db, name, None

    def select(self, columns, **k):
        self.selected = columns
        return self

    def upsert(self, row):
        return self

    def __getattr__(self, _):
        return lambda *a, **k: self

    def execute(self):
        self.db.requests.append(self.name)
        return types.SimpleNamespace(data=self.db.answer(self))


class Database:
    def __init__(self, answer=lambda table: []):
        self.requests, self.answer = [], answer

    def table(self, name):
        return Table(self, name)


def test_the_session_id_is_written_when_it_changes_not_every_time_the_cli_repeats_it(monkeypatch):
    db = Database()
    import app.services.supabase_client as client
    monkeypatch.setattr(client, 'get_supabase_client', lambda: types.SimpleNamespace(client=db))
    monkeypatch.setattr(cli_runner, '_cli_sessions', {})
    monkeypatch.setattr(cli_runner, '_sessions_in_db', {})
    for _ in range(5):
        cli_runner._save_session('room', 'session-1')
    assert db.requests == ['cli_sessions'] and cli_runner._load_session('room') == 'session-1'
    cli_runner._save_session('room', 'session-2')
    assert db.requests == ['cli_sessions'] * 2
    cli_runner._clear_cli_session('room')            # forgotten: the same id is a new fact again
    cli_runner._save_session('room', 'session-2')
    assert db.requests == ['cli_sessions'] * 4


def test_a_session_id_that_could_not_be_written_is_tried_again(monkeypatch):
    calls = []

    def failing_then_fine():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('The read operation timed out')
        return types.SimpleNamespace(client=Database())
    import app.services.supabase_client as client
    monkeypatch.setattr(client, 'get_supabase_client', failing_then_fine)
    monkeypatch.setattr(cli_runner, '_cli_sessions', {})
    monkeypatch.setattr(cli_runner, '_sessions_in_db', {})
    cli_runner._save_session('room', 's')
    cli_runner._save_session('room', 's')
    cli_runner._save_session('room', 's')
    assert len(calls) == 2 and cli_runner._cli_sessions['room'] == 's'


def project_service(db):
    service = ProjectService.__new__(ProjectService)
    service.supabase = db
    return service


def test_the_open_chats_room_info_is_one_request_with_the_same_fields():
    row = {'id': 'p', 'user_id': 'u', 'room_id': 'r', 'title': '部屋', 'room_state': {
        'last_message_at': '2026-10-13T08:52:48+00:00', 'updated_at': '2026-10-01T00:00:00+00:00', 'last_message_preview': 'いや、今は直ってるわ',
        'chat_room_members': [{'unread_count': 2}]}}
    db = Database(lambda table: [dict(row)])
    project = project_service(db)._get_project_sync('p', 'u')
    assert db.requests == ['projects']
    assert project == {'id': 'p', 'user_id': 'u', 'room_id': 'r', 'title': '部屋', 'unread_count': 2,
                       'last_message_at': '2026-10-13T08:52:48+00:00', 'last_message_preview': 'いや、今は直ってるわ'}
    no_room = project_service(Database(lambda table: [{'id': 'p', 'room_id': None, 'room_state': None}]))._get_project_sync('p', 'u')
    assert (no_room['unread_count'], no_room['last_message_at'], no_room['last_message_preview']) == (0, None, None)
    assert project_service(Database())._get_project_sync('missing', 'u') is None


def test_room_info_falls_back_to_reading_in_steps_when_the_one_request_is_refused():
    def answer(table):
        if table.name == 'projects' and 'room_state' in (table.selected or ''):
            raise RuntimeError('Could not find a relationship')
        return {'projects': [{'id': 'p', 'room_id': 'r'}], 'chat_room_members': [{'unread_count': 4}],
                'chat_rooms': [{'last_message_at': None, 'updated_at': '2026-10-01T00:00:00+00:00', 'last_message_preview': None}]}[table.name]
    db = Database(answer)
    project = project_service(db)._get_project_sync('p', 'u')
    assert project['unread_count'] == 4 and project['last_message_at'] == '2026-10-01T00:00:00+00:00'
