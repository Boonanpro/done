"""A notice that wakes a room never stops the owner's running work there (2026-11-10, 中村さん's script): it goes to the
room's receiver, a burst is read together, and only a change of premise reaches the working Dan."""
import asyncio

import pytest

from app.services import room_receiver as rr
from app.services import work_continuity as w


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(w, 'DB', tmp_path / 'work.sqlite')
    monkeypatch.setattr(w, '_tasks', {})
    monkeypatch.setattr(rr, '_background', {})


def busy_room(monkeypatch, busy):
    async def room_busy(room):
        return busy
    monkeypatch.setattr(w, 'room_busy', room_busy)


def receiver_spy(monkeypatch):
    handed = []
    async def hand_over(room_id, user_id, prompt):
        handed.append((room_id, user_id, prompt))
        return 'job1'
    monkeypatch.setattr(rr, 'hand_over', hand_over)
    return handed


def no_turn(monkeypatch):
    import app.agent.cli_runner as cr
    async def runner(**args):
        raise AssertionError('the owner\'s running work must not get the notice as a turn')
        yield {}
    monkeypatch.setattr(cr, 'process_message_cli', runner)


def test_lane(monkeypatch):
    busy_room(monkeypatch, False)
    assert asyncio.run(rr.lane('r')) == 'turn'
    busy_room(monkeypatch, True)
    assert asyncio.run(rr.lane('r')) == 'receiver'
    with rr.background('r'):
        assert asyncio.run(rr.lane('r')) == 'wait'
    assert asyncio.run(rr.lane('r')) == 'receiver'


def test_watch_during_the_owners_work_goes_to_the_receiver(monkeypatch):
    import app.services.followup_poller as fp
    busy_room(monkeypatch, True)
    no_turn(monkeypatch)
    handed = receiver_spy(monkeypatch)
    text, landed = asyncio.run(fp._wake_turn('r', 'u', '[定期見張り] 写真の仕分け'))
    assert landed and handed == [('r', 'u', '[定期見張り] 写真の仕分け')]


def test_watch_in_an_idle_room_is_a_turn_marked_as_background(monkeypatch):
    import app.agent.cli_runner as cr
    import app.services.followup_poller as fp
    busy_room(monkeypatch, False)
    monkeypatch.setattr(fp, '_resolve_project_id', lambda room: None)
    seen = []
    async def runner(**args):
        seen.append(dict(rr._background))
        yield {'type': 'result', 'text': '仕分けました'}
    monkeypatch.setattr(cr, 'process_message_cli', runner)
    assert asyncio.run(fp._wake_turn('r', 'u', '見張り')) == ('仕分けました', True)
    assert 'r' in seen[0] and rr._background == {}


@pytest.mark.parametrize('source', ['inbound', 'followup'])
def test_contact_during_the_owners_work_is_handed_over_and_closed(monkeypatch, source):
    busy_room(monkeypatch, True)
    no_turn(monkeypatch)
    handed = receiver_spy(monkeypatch)
    result = asyncio.run(w.execute(key='k', room_id='r', user_id='u', prompt='中村さんからチャットワーク', source=source))
    assert result == ('', True)
    assert handed == [('r', 'u', '中村さんからチャットワーク')]
    row = w.get('k')
    assert row['status'] == 'done' and 'job1' in row['evidence']


def test_the_rooms_own_work_waits_instead(monkeypatch):
    busy_room(monkeypatch, True)
    no_turn(monkeypatch)
    handed = receiver_spy(monkeypatch)
    assert asyncio.run(w.execute(key='k', room_id='r', user_id='u', prompt='台本の続き', source='event')) == ('', False)
    assert handed == [] and w.get('k')['status'] == 'ready'


def test_dispatch_hands_waiting_contacts_over_but_not_the_rooms_work(monkeypatch):
    busy_room(monkeypatch, True)
    no_turn(monkeypatch)
    handed = receiver_spy(monkeypatch)
    monkeypatch.setattr('app.services.restart_signal.draining', lambda: False)
    w.enqueue(key='c', room_id='r', user_id='u', source='inbound', prompt='連絡')
    w.enqueue(key='e', room_id='r', user_id='u', source='event', prompt='台本の続き')
    async def run():
        await w.dispatch()
        await asyncio.gather(*list(w._tasks.values()))
    asyncio.run(run())
    assert [h[2] for h in handed] == ['連絡']
    assert w.get('c')['status'] == 'done' and w.get('e')['status'] == 'ready'


def test_hand_over_adds_to_the_running_receiver(monkeypatch):
    from app.services import parallel_job_runner as pj
    calls = []
    async def start(room_id, user_id, task, model='', title='', quiet=False, receiver=False):
        calls.append(('start', task, title, receiver))
        return {'id': 'job1'}
    async def control(room_id, user_id, job_id, op, text='', model=''):
        calls.append((op, job_id, text))
    monkeypatch.setattr(pj, 'start', start)
    monkeypatch.setattr(pj, 'control', control)
    active = []
    monkeypatch.setattr(rr, '_active_receiver', lambda room, user: active[0] if active else None)
    assert asyncio.run(rr.hand_over('r', 'u', '1通目')) == 'job1'
    assert calls[0][0] == 'start' and calls[0][3] is True and calls[0][2] == rr.TITLE
    assert '1通目' in calls[0][1] and 'tell_room_work.py' in calls[0][1] and 'WATCH_NO_CHANGE' in calls[0][1]
    active.append({'id': 'job1'})
    asyncio.run(rr.hand_over('r', 'u', '2通目'))
    assert calls[1][0] == 'update' and calls[1][1] == 'job1' and '2通目' in calls[1][2]


def _receiver_deliver(monkeypatch, text):
    from app.services import inbox, parallel_job_runner as pj
    rows = {'j1': {'id': 'j1', 'room_id': 'r', 'user_id': 'u', 'state': 'completed', 'receiver': True}}
    monkeypatch.setattr(pj.state, 'read', lambda job_id: rows[job_id])
    monkeypatch.setattr(pj.state, 'change', lambda job_id, fn: fn(rows[job_id]))
    monkeypatch.setattr(pj, 'wake_room', lambda *a, **k: (_ for _ in ()).throw(AssertionError('no second wake')))
    said = []
    async def say(user_id, room_id, text, push=True):
        said.append((room_id, text))
    monkeypatch.setattr(inbox, 'say', say)
    asyncio.run(pj.deliver('j1', text))
    return said


def test_receiver_answer_is_said_in_the_room_once(monkeypatch):
    assert _receiver_deliver(monkeypatch, '中村さんから感想が2件届きました。') == [('r', '中村さんから感想が2件届きました。')]


def test_receiver_with_nothing_to_tell_says_nothing(monkeypatch):
    assert _receiver_deliver(monkeypatch, 'WATCH_NO_CHANGE') == []


def test_burst_of_one_shot_wakes_is_merged(monkeypatch):
    import app.services.followups as f
    import app.services.followup_poller as fp
    first = {'id': 'a', 'room_id': 'r', 'note': '[チャットワーク受信通知] 1通目', 'fire_at': '2026-11-10T06:17:06+00:00'}
    in_cycle = {'id': 'b', 'room_id': 'r', 'note': '[チャットワーク受信通知] 2通目', 'fire_at': '2026-11-10T06:17:10+00:00'}
    other_room = {'id': 'x', 'room_id': 'q', 'note': '別の部屋', 'fire_at': '2026-11-10T06:17:10+00:00'}
    pending = {'id': 'c', 'room_id': 'r', 'note': '[チャットワーク受信通知] 3通目', 'fire_at': '2026-11-10T06:17:12+00:00'}
    marked = []
    monkeypatch.setattr(f, 'pending_room_rows', lambda room, until: [pending])
    monkeypatch.setattr(f, 'claim_row', lambda rid: True)
    monkeypatch.setattr(f, 'mark_status', lambda rid, st: marked.append((rid, st)))
    cycle = [first, in_cycle, other_room]
    row = asyncio.run(fp._merge_burst(f.decode_watch_row(first), first, cycle))
    note = f.decode_watch_row(row)['plain_note']
    assert '3件' in note and '1通目' in note and '2通目' in note and '3通目' in note
    assert sorted(marked) == [('b', 'done'), ('c', 'done')]
    assert cycle == [first, other_room]


def test_one_shot_wake_waits_for_the_next_one_due_soon(monkeypatch):
    from datetime import datetime, timedelta, timezone
    import app.services.followups as f
    import app.services.followup_poller as fp
    now = datetime.now(timezone.utc)
    row = {'id': 'a', 'room_id': 'r', 'note': '1通目', 'fire_at': (now - timedelta(seconds=5)).isoformat()}
    soon = {'id': 'b', 'room_id': 'r', 'note': '2通目', 'fire_at': (now + timedelta(seconds=20)).isoformat()}
    marked = []
    monkeypatch.setattr(f, 'mark_status', lambda rid, st: marked.append((rid, st)))
    monkeypatch.setattr(f, 'pending_room_rows', lambda room, until: [soon])
    assert asyncio.run(fp._hold_for_burst(f.decode_watch_row(row))) is True and marked == [('a', 'pending')]
    old = {**row, 'fire_at': (now - timedelta(seconds=fp.BURST_LIMIT + 5)).isoformat()}
    assert asyncio.run(fp._hold_for_burst(f.decode_watch_row(old))) is False
    monkeypatch.setattr(f, 'pending_room_rows', lambda room, until: [])
    assert asyncio.run(fp._hold_for_burst(f.decode_watch_row(row))) is False


def test_work_note_reaches_only_a_running_turn(monkeypatch):
    from app.api import chat_routes as cr
    import app.agent.streaming_session as ss
    monkeypatch.setattr(cr, '_require_loopback', lambda request: None)
    got = []
    monkeypatch.setattr(ss, 'submit_room_followup', lambda room, text, received_at=None: got.append((room, text)) or 'session')
    class Req:
        def __init__(self, body): self.body = body
        async def json(self): return self.body
    monkeypatch.setattr(ss, 'is_turn_active_or_preparing', lambda room: False)
    out = asyncio.run(cr.internal_room_work_note('r', Req({'text': '中村さんがテーマを変えたい'})))
    assert out['delivered'] is False and got == []
    monkeypatch.setattr(ss, 'is_turn_active_or_preparing', lambda room: True)
    out = asyncio.run(cr.internal_room_work_note('r', Req({'text': '中村さんがテーマを変えたい'})))
    assert out['delivered'] == 'session' and got[0][0] == 'r'
    assert '中村さんがテーマを変えたい' in got[0][1] and '本人の発言ではありません' in got[0][1]
