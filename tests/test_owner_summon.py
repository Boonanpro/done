import asyncio
import time

import pytest

from app.services import owner_summon as os_


@pytest.fixture(autouse=True)
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(os_, 'ROOT', tmp_path/'summons')
    monkeypatch.setattr(os_, '_project_of', lambda room: ('proj-1', '部屋'))
    monkeypatch.setattr(os_, '_in_call', lambda user: False)
    yield


def test_answer_by_message_stops_and_call_still_says_it():
    s = os_.create('u', 'room-a', '承認を押してください。番号は483920', 5)
    assert [x['id'] for x in os_.live('u')] == [s['id']]
    assert os_.answer_room('room-b') == 0
    assert os_.answer_room('room-a') == 1
    left = os_.live('u')
    assert left and left[0]['state'] == 'answered'      # a call started now still says it
    os_.mark_spoken(s['id'])
    assert os_.live('u') == []


def test_resolve_and_expire():
    a = os_.create('u', 'room-a', 'a', 5)
    assert os_.resolve(room_id='room-a') == 1 and os_.live('u') == []
    b = os_.create('u', 'room-a', 'b', 5)
    os_._change(b['id'], lambda s: s.update(deadline=time.time() - 1))
    assert os_.live('u') == [] and os_.read(b['id'])['state'] == 'expired'


def test_ring_pushes_until_answered(monkeypatch):
    pushes = []
    async def push(s, ring):
        pushes.append(ring)
        if len(pushes) == 3: os_.answer(s['id'], 'tap')
        return {'sent': 1}
    monkeypatch.setattr(os_, '_push', push)
    monkeypatch.setattr(os_, 'RING_AFTER', (0, 0, 0, 0, 0))
    s = os_.create('u', 'room-a', 'x', 5)
    asyncio.run(os_.ring(s['id']))
    assert pushes == [False, True, True]                  # first an ordinary loud push, then ringing ones
    assert len(os_.read(s['id'])['pushes']) == 3


def test_silent_during_a_call(monkeypatch):
    pushes = []
    async def push(s, ring): pushes.append(ring); return {}
    monkeypatch.setattr(os_, '_push', push)
    monkeypatch.setattr(os_, '_in_call', lambda user: True)
    monkeypatch.setattr(os_, 'RING_AFTER', (0, 0))
    s = os_.create('u', 'room-a', 'x', 5)
    asyncio.run(os_.ring(s['id']))
    assert pushes == []


def test_tool_replaces_the_rooms_open_summons(monkeypatch):
    monkeypatch.setattr(os_, 'start_ringing', lambda i: None)
    r1 = asyncio.run(os_.tool({'reason': '一つ目'}, 'u', 'room-a'))
    r2 = asyncio.run(os_.tool({'reason': '二つ目', 'deadline_minutes': 2}, 'u', 'room-a'))
    assert r1['success'] and r2['success']
    assert [s['reason'] for s in os_.live('u')] == ['二つ目']
    assert not asyncio.run(os_.tool({}, 'u', 'room-a'))['success']
    assert '1件' in asyncio.run(os_.tool({'action': 'resolve'}, 'u', 'room-a'))['output']
