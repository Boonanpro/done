from types import SimpleNamespace
import logging
import pytest

from app.services.collab_service import CollabService
from app.services.collab_link_preview import MetadataParser, public_target


class Duplicate(Exception):
    code = '23505'


class Database:
    def __init__(self):
        self.rows = {}
        self.fail_after_insert = True

    def table(self, name):
        db = self

        class Query:
            operation, value, filters = None, None, None

            def insert(self, value):
                self.operation, self.value = 'insert', value
                return self

            def update(self, value):
                self.operation = 'update'
                return self

            def select(self, value):
                self.operation, self.filters = 'select', {}
                return self

            def eq(self, key, value):
                if self.filters is not None:
                    self.filters[key] = value
                return self

            def execute(self):
                if self.operation == 'insert':
                    if self.value['id'] in db.rows:
                        raise Duplicate()
                    db.rows[self.value['id']] = dict(self.value)
                    if db.fail_after_insert:
                        db.fail_after_insert = False
                        raise OSError('connection reset')
                    return SimpleNamespace(data=[self.value])
                if self.operation == 'select':
                    return SimpleNamespace(data=[r for r in db.rows.values() if all(r[k] == v for k, v in self.filters.items())])
                return SimpleNamespace(data=[])
        return Query()


@pytest.mark.asyncio
async def test_lost_response_and_repeated_send_do_not_duplicate_message():
    service = CollabService.__new__(CollabService)
    service.supabase = Database()
    service.logger = logging.getLogger(__name__)
    args = dict(room_id='test-room', sender_type='guest', sender_name='同じ名前', content='写真です',
                metadata={'sender_id': 'guest-a'}, message_id='stable-message-id')
    first = await service.send_message(**args)
    second = await service.send_message(**args)
    assert first['id'] == second['id']
    assert len(service.supabase.rows) == 1
    assert not first['_replayed'] and second['_replayed']


def test_preview_extracts_title_and_description_without_markup():
    parser = MetadataParser()
    parser.feed('<title>代替</title><meta property="og:title" content="題名 &amp; 内容"><meta name="description" content="説明">')
    assert parser.values['og:title'] == '題名 & 内容'
    assert parser.values['description'] == '説明'


@pytest.mark.parametrize('url', ['https://127.0.0.1', 'https://[::1]', 'http://example.com', 'https://user:pass@example.com', 'https://example.com:8000'])
def test_preview_rejects_internal_or_unsafe_destinations(url):
    with pytest.raises(ValueError):
        public_target(url)


@pytest.mark.asyncio
async def test_explicit_guest_identity_wins_over_owner_cookie(monkeypatch):
    from starlette.requests import Request
    from unittest.mock import AsyncMock
    from app.api import collab_routes as routes
    from app.models.collab_schemas import CollabMessageSendRequest
    request = Request({'type': 'http', 'headers': [(b'cookie', b'done_access_token=owner'), (b'x-guest-token', b'guest')]})
    monkeypatch.setattr(routes, '_decode_guest_token', lambda value: {'sub': 'guest-id', 'guest_name': 'Test guest', 'room_id': 'room'} if value == 'guest' else None)
    monkeypatch.setattr(routes, 'decode_access_token', lambda value: SimpleNamespace(user_id='owner-id', email='owner') if value == 'owner' else None)
    service = SimpleNamespace(get_room=AsyncMock(return_value={'owner_id': 'owner-id'}), send_message=AsyncMock(return_value={
        'id': 'message', 'room_id': 'room', 'sender_type': 'guest', 'sender_name': 'Test guest', 'content': 'hello',
        'metadata': {}, 'created_at': '2026-10-28T00:00:00Z', '_replayed': True}))
    assert await routes._room_access(request, None, service, 'room') == (False, 'guest-id')
    await routes.send_message('room', CollabMessageSendRequest(content='hello', metadata={'sender_id': 'forged', 'client_msg_id': 'temp-test'}), request, None, service)
    args = service.send_message.call_args.kwargs
    assert args['sender_type'] == 'guest'
    assert args['sender_name'] == 'Test guest'
    assert args['metadata']['sender_id'] == 'guest-id'
    assert args['message_id']


@pytest.mark.asyncio
async def test_push_destination_is_derived_from_authenticated_participant(monkeypatch):
    from starlette.requests import Request
    from unittest.mock import AsyncMock
    from app.api import collab_routes, push_routes
    request = Request({'type': 'http', 'headers': [(b'x-guest-token', b'guest')]})
    monkeypatch.setattr(collab_routes, '_room_access', AsyncMock(return_value=(False, 'mine')))
    monkeypatch.setattr(collab_routes, 'get_collab_service', lambda: SimpleNamespace(list_invites=AsyncMock(return_value=[{'id': 'mine', 'token': 'personal'}])))
    req = push_routes.SubscribeRequest(room_id='room', sender_type='guest', subscription={}, landing_url='//evil.example')
    assert await push_routes._subscription_identity(req, request) == ('/collab/join/personal', 'mine')
    req.sender_type = 'owner'
    with pytest.raises(push_routes.HTTPException) as error:
        await push_routes._subscription_identity(req, request)
    assert error.value.status_code == 403


class SubscriptionTable:
    """push_subscriptions の代わり。select → eq → execute で全行を返す。"""
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        rows = self.rows

        class Query:
            def select(self, *_):
                return self

            def eq(self, key, value):
                self.rows = [r for r in rows if r.get(key) == value]
                return self

            def execute(self):
                return SimpleNamespace(data=self.rows)
        return Query()


@pytest.mark.asyncio
async def test_guest_message_push_reaches_other_guests_but_not_the_sender(monkeypatch):
    from app.services import push_service
    from app.services.push_service import PushService
    monkeypatch.setattr(push_service.settings, 'VAPID_PRIVATE_KEY', 'private')
    monkeypatch.setattr(push_service.settings, 'VAPID_PUBLIC_KEY', 'public')
    delivered = []
    monkeypatch.setattr(push_service, 'webpush', lambda **kw: delivered.append(kw['subscription_info']['endpoint']))
    svc = PushService.__new__(PushService)
    svc.supabase = SubscriptionTable([
        {'room_id': 'room', 'sender_type': 'guest', 'sender_id': 'guest-a', 'endpoint': 'a', 'p256dh': '', 'auth': ''},
        {'room_id': 'room', 'sender_type': 'guest', 'sender_id': 'guest-b', 'endpoint': 'b', 'p256dh': '', 'auth': ''},
        {'room_id': 'room', 'sender_type': 'guest', 'sender_id': None, 'endpoint': 'legacy-guest', 'p256dh': '', 'auth': ''},
        {'room_id': 'room', 'sender_type': 'owner', 'sender_id': None, 'endpoint': 'owner', 'p256dh': '', 'auth': ''},
        {'room_id': 'other', 'sender_type': 'owner', 'sender_id': None, 'endpoint': 'elsewhere', 'p256dh': '', 'auth': ''},
    ])
    result = await svc.notify_room('room', exclude_type='guest', title='A', body='hi', exclude_sender_id='guest-a')
    # 本人(a)は除く。別のゲスト(b)とオーナーには届く。身元の無い古いゲスト購読は従来どおり種類で除く
    assert delivered == ['b', 'owner']
    assert result == {'attempted': 2, 'sent': 2, 'failed': 0}
    delivered.clear()
    await svc.notify_room('room', exclude_type='guest', title='A', body='hi')
    assert delivered == ['owner']


def test_private_dan_consultation_is_only_visible_to_its_guest():
    from app.api.collab_routes import _visible_to_guest
    public = {'metadata': {'sender_id': 'guest-b'}}
    owner_consult = {'metadata': {'visibility': 'owner_only'}}
    a_question = {'metadata': {'visibility': 'guest_only', 'sender_id': 'guest-a'}}
    a_answer = {'metadata': {'visibility': 'guest_only', 'recipient_id': 'guest-a'}}
    legacy_answer = {'metadata': {'visibility': 'guest_only'}}
    assert [_visible_to_guest(m, 'guest-a') for m in (public, owner_consult, a_question, a_answer, legacy_answer)] == [True, False, True, True, True]
    assert [_visible_to_guest(m, 'guest-b') for m in (public, owner_consult, a_question, a_answer, legacy_answer)] == [True, False, False, False, True]


class Socket:
    def __init__(self):
        self.received = []

    async def send_json(self, payload):
        self.received.append(payload)


@pytest.mark.asyncio
async def test_guest_dan_assist_is_delivered_only_to_the_consulting_guest(monkeypatch):
    from unittest.mock import AsyncMock
    from app.api import collab_routes as routes
    import app.services.collab_dan_service as dan_service
    manager = routes.CollabConnectionManager()
    a, a_phone, b, owner = Socket(), Socket(), Socket(), Socket()
    manager.add('room', a, 'guest', '同じ名前', 'guest-a')
    manager.add('room', a_phone, 'guest', '同じ名前', 'guest-a')   # 同じ人の2台目
    manager.add('room', b, 'guest', '同じ名前', 'guest-b')         # 同じ名前の別人
    manager.add('room', owner, 'owner', 'みき', 'owner-id')
    monkeypatch.setattr(routes, 'collab_manager', manager)
    history = [
        {'sender_type': 'owner', 'sender_name': 'みき', 'content': '公開の発言', 'metadata': {}},
        {'sender_type': 'owner', 'sender_name': 'みき', 'content': 'ダンへの秘密の相談', 'metadata': {'visibility': 'owner_only'}},
        {'sender_type': 'guest', 'sender_name': '同じ名前', 'content': 'Bの相談', 'metadata': {'visibility': 'guest_only', 'sender_id': 'guest-b'}},
        {'sender_type': 'dan_guest', 'sender_name': 'DAN', 'content': 'Bへの返事', 'metadata': {'visibility': 'guest_only', 'recipient_id': 'guest-b'}},
    ]
    seen = {}
    def fake_dan(title, description, recent, trigger, owner_name=None, system_override=''):
        seen['history'] = recent
        seen['prompt'] = system_override
        return 'Aへの返事'
    monkeypatch.setattr(dan_service, 'get_dan_response', fake_dan)
    sent = []
    async def send_message(**kw):
        sent.append(kw)
        return {'id': 'dan-1', 'created_at': '2026-10-28T00:00:00Z', **kw}
    service = SimpleNamespace(get_room=AsyncMock(return_value={'title': '試験', 'description': None}),
                              get_messages=AsyncMock(return_value=history), send_message=send_message)
    await routes._trigger_guest_dan_assist(service, 'room', {
        'sender_type': 'guest', 'sender_name': '同じ名前', 'content': 'Aの質問', 'metadata': {'sender_id': 'guest-a'}})
    assert [m['content'] for m in seen['history']] == ['公開の発言']
    assert '秘密の相談' not in seen['prompt'] and 'Bの相談' not in seen['prompt']
    assert sent[0]['metadata'] == {'visibility': 'guest_only', 'recipient_id': 'guest-a'}
    assert [p['type'] for p in a.received] == ['dan_thinking', 'new_message']
    assert [p['type'] for p in a_phone.received] == ['dan_thinking', 'new_message']
    assert b.received == [] and owner.received == []
