"""A long wake in one room does not hold every other room's watches (2026-11-10: a 20-minute follow-up turn in the dev
room left all due watches pending, because the poller awaited each wake before the next cycle)."""
import asyncio

import pytest

import app.services.followup_poller as fp
import app.services.followups as followups
from app.services import room_receiver as rr


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(fp, '_inflight', {})
    monkeypatch.setattr(rr, '_background', {})

    async def nothing():
        return None
    import app.services.command_job_runner as cjr
    import app.services.work_continuity as w
    monkeypatch.setattr(cjr, 'dispatch_pending', nothing)
    monkeypatch.setattr(w, 'dispatch', nothing)

    async def idle(room):
        return 'turn'
    monkeypatch.setattr(rr, 'lane', idle)


def rows_of(*specs):
    return [{'id': i, 'room_id': room, 'note': '{"w": 1, "kind": "every", "note": "見張り", "spec": {"interval_seconds": 3600}}'}
            for i, room in specs]


def fake_db(monkeypatch, due):
    """claim_due_followups over a list of due rows, honouring skip_rooms; mark_status puts a row back."""
    put_back = []

    def claim(limit=5, skip_rooms=None):
        skip = set(skip_rooms or ())
        got = [r for r in due if r['room_id'] not in skip][:limit]
        for r in got:
            due.remove(r)
        return got

    def mark(row_id, status):
        put_back.append((row_id, status))
    monkeypatch.setattr(followups, 'claim_due_followups', claim)
    monkeypatch.setattr(followups, 'mark_status', mark)
    return put_back


def test_a_long_wake_does_not_hold_other_rooms(monkeypatch):
    release = asyncio.Event()
    fired = []

    async def fire(row):
        fired.append(row['room_id'])
        if row['room_id'] == 'slow':
            await release.wait()
    monkeypatch.setattr(fp, '_fire', fire)
    due = rows_of(('a', 'slow'))
    fake_db(monkeypatch, due)

    async def run():
        await asyncio.wait_for(fp._tick(), 2)       # returns while the slow room's wake is still running
        await asyncio.sleep(0)
        due.extend(rows_of(('b', 'other')))
        await asyncio.wait_for(fp._tick(), 2)
        await asyncio.sleep(0)
        assert fired == ['slow', 'other']
        assert 'slow' in fp._inflight
        release.set()
        await asyncio.sleep(0.05)
        assert 'slow' not in fp._inflight            # forgotten once it ends
    asyncio.run(run())


def test_the_same_room_waits_for_its_running_wake(monkeypatch):
    release = asyncio.Event()
    fired = []

    async def fire(row):
        fired.append(row['id'])
        await release.wait()
    monkeypatch.setattr(fp, '_fire', fire)
    due = rows_of(('a', 'r'), ('b', 'r'))
    put_back = fake_db(monkeypatch, due)

    async def run():
        await asyncio.wait_for(fp._tick(), 2)
        await asyncio.sleep(0)
        assert fired == ['a'] and put_back == [('b', 'pending')]   # two rows of one room in one cycle: one wake
        due.extend(rows_of(('c', 'r')))
        await asyncio.wait_for(fp._tick(), 2)
        await asyncio.sleep(0)
        assert fired == ['a'] and due == rows_of(('c', 'r'))     # not claimed while the room's wake runs
        release.set()
        await asyncio.sleep(0.05)
        await asyncio.wait_for(fp._tick(), 2)
        await asyncio.sleep(0)
        assert fired == ['a', 'c']
        release.set()
    asyncio.run(run())


def test_a_failed_wake_is_logged_and_the_poller_goes_on(monkeypatch):
    async def fire(row):
        raise RuntimeError('boom')
    monkeypatch.setattr(fp, '_fire', fire)
    fake_db(monkeypatch, rows_of(('a', 'r')))

    async def run():
        await asyncio.wait_for(fp._tick(), 2)
        await asyncio.sleep(0.05)
        assert 'r' not in fp._inflight
    asyncio.run(run())


def test_claim_leaves_waking_rooms_and_their_firing_rows_alone(monkeypatch):
    calls = {'update': []}

    class Q:
        def __init__(self, data):
            self.data = data
            self._filters = {}

        def select(self, *a): return self
        def eq(self, k, v): self._filters[k] = v; return self
        def lt(self, *a): return self
        def lte(self, *a): return self
        def order(self, *a, **k): return self
        def limit(self, n): self._limit = n; return self

        def update(self, values):
            calls['update'].append(values)
            return self

        def execute(self):
            return self

    stuck = [{'id': 's1', 'room_id': 'busy'}, {'id': 's2', 'room_id': 'dead'}]
    due = [{'id': 'd1', 'room_id': 'busy'}, {'id': 'd2', 'room_id': 'free'}]
    updated_ids = []

    class SB:
        def table(self, name):
            return T()

    class T:
        def select(self, cols):
            return Sel(cols)

        def update(self, values):
            return Upd(values)

    class Sel(Q):
        def __init__(self, cols):
            super().__init__(None)
            self.cols = cols

        def execute(self):
            self.data = stuck if self._filters.get('status') == 'firing' else due
            return self

    class Upd(Q):
        def __init__(self, values):
            super().__init__([{'ok': 1}])
            self.values = values

        def eq(self, k, v):
            if k == 'id':
                updated_ids.append((v, self.values['status']))
            return self

    monkeypatch.setattr(followups, '_sb', lambda: SB())
    import app.services.restart_signal as rs
    monkeypatch.setattr(rs, 'draining', lambda: False)
    got = followups.claim_due_followups(5, {'busy'})
    assert [r['id'] for r in got] == ['d2']
    assert ('s1', 'pending') not in updated_ids and ('s2', 'pending') in updated_ids
