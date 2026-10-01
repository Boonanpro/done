"""The inbox: each user's own mailboxes, one queue, a rule sieve, Dan's judgement, the outcome said in chat."""
import pytest

from app.services import inbox


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox, 'ROOT', tmp_path)
    monkeypatch.setattr('app.services.encryption.encrypt_data', lambda s: s)
    monkeypatch.setattr('app.services.encryption.decrypt_data', lambda s: s)
    return tmp_path


def mail(sender='田中 <tanaka@example.co.jp>', **headers):
    return {'id': 'm1', 'subject': '見積の件', 'content': '来週までにお見積りをいただけますか', 'sender_info': {'from': sender},
            'metadata': {'headers': headers}}


def test_the_sieve_drops_lists_automatic_mail_and_the_users_own_mail_and_keeps_people():
    own = {'me@example.com'}
    assert inbox.sieve(mail(), own) == ''
    assert inbox.sieve(mail(**{'List-Unsubscribe': '<mailto:x>'}), own) == 'list'
    assert inbox.sieve(mail(**{'Auto-Submitted': 'auto-generated'}), own) == 'automatic'
    assert inbox.sieve(mail(**{'Precedence': 'bulk'}), own) == 'bulk'
    assert inbox.sieve(mail('Me <ME@example.com>'), own) == 'own'


def test_users_are_kept_apart_and_a_mailbox_is_kept_only_when_it_logs_in(home, monkeypatch):
    class Box:
        def logout(self): pass
    monkeypatch.setattr(inbox, '_login', lambda box: Box())
    inbox.connect_mailbox('user-a', 'A@iCloud.com', 'pw')
    assert inbox.settings('user-a')['mailboxes'][0] == {'address': 'a@icloud.com', 'host': 'imap.mail.me.com', 'port': 993, 'password': 'pw'}
    assert inbox.settings('user-b') == {} and sorted(inbox.users()) == ['user-a']
    def refuse(box): raise RuntimeError('login failed')
    monkeypatch.setattr(inbox, '_login', refuse)
    with pytest.raises(RuntimeError):
        inbox.connect_mailbox('user-b', 'b@gmail.com', 'wrong')
    assert inbox.settings('user-b') == {}


@pytest.mark.asyncio
async def test_a_judged_item_is_said_in_its_room_or_the_home_room_and_a_watch_wakes_its_room(home, monkeypatch):
    said, woke = [], []
    class Chat:
        async def send_message(self, room, user, text, sender_type): said.append((room, text)); return {'id': 'x'}
    monkeypatch.setattr('app.services.chat_service.ChatService', Chat)
    monkeypatch.setattr(inbox, '_recent_rooms', lambda user, limit=15: [{'room_id': 'room-project', 'title': '見積'}])
    monkeypatch.setattr('app.services.inbound_wakeup.schedule_room_wakeup', lambda item, room, reason: woke.append((room, item['_inbox_prompt'])) or True)
    inbox.set_home_room('u', 'room-home')
    assert await inbox.deliver('u', mail(), {'decision': 'tell', 'room_id': 'room-project', 'line': '田中さんから見積の依頼'}, []) == 'room-project'
    assert await inbox.deliver('u', mail(), {'decision': 'tell', 'room_id': 'made-up', 'line': '別件'}, []) == 'room-home'
    watch = {'id': 'w1', 'room_id': 'room-watch', 'from': 'example.co.jp', 'note': '見積の返事が来たら知らせる'}
    assert await inbox.deliver('u', mail(), {'decision': 'act', 'watch_id': 'w1', 'line': '待っていた返事'}, [watch]) == 'room-watch'
    assert said == [('room-project', '田中さんから見積の依頼'), ('room-home', '別件')]
    assert woke[0][0] == 'room-watch' and '見積の返事が来たら知らせる' in woke[0][1]


@pytest.mark.asyncio
async def test_a_reply_to_what_dan_sent_is_never_dropped(home, monkeypatch):
    marked = {}
    monkeypatch.setattr(inbox, '_mail_watches', lambda user: [])
    monkeypatch.setattr(inbox, '_recent_rooms', lambda user, limit=300: [])
    monkeypatch.setattr(inbox, '_rooms_that_know', lambda sender, rooms: [])
    async def judge(*a, **k): return {'decision': 'ignore'}
    monkeypatch.setattr(inbox, 'judge', judge)
    async def deliver(user, item, decision, watches): return decision.get('room_id')
    monkeypatch.setattr(inbox, 'deliver', deliver)
    monkeypatch.setattr(inbox, '_mark', lambda item_id, result: marked.update(result))
    class Match:
        reason, route = 'in_reply_to_message_id', {'origin_room_id': 'room-sent'}
    class Routing:
        def find_route(self, item): return Match()
    monkeypatch.setattr('app.services.external_message_routing.get_external_message_routing_service', lambda: Routing())
    assert await inbox.handle('u', mail(), set()) == 'tell' and marked['room'] == 'room-sent'


@pytest.mark.asyncio
async def test_a_watch_is_matched_by_its_own_condition_without_the_model(home, monkeypatch):
    watch = {'id': 'w1', 'room_id': 'room-watch', 'from': 'openai.com', 'subject': '', 'note': 'OpenAI の返事'}
    monkeypatch.setattr(inbox, '_mail_watches', lambda user: [watch])
    async def judge(*a, **k): raise AssertionError('the model is not asked')
    monkeypatch.setattr(inbox, 'judge', judge)
    sent = []
    async def deliver(user, item, decision, watches): sent.append(decision); return decision['room_id']
    monkeypatch.setattr(inbox, 'deliver', deliver)
    monkeypatch.setattr(inbox, '_mark', lambda item_id, result: None)
    assert await inbox.handle('u', mail('OpenAI <noreply@openai.com>'), set()) == 'act'
    assert sent[0]['watch_id'] == 'w1' and sent[0]['room_id'] == 'room-watch'
    assert inbox.watch_hit(mail('田中 <tanaka@example.co.jp>'), [watch]) is None
