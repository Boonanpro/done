from datetime import datetime, timezone

import app.services.followups as followups


class _Result:
    count = 0
    data = []


class _Query:
    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def in_(self, *_args, **_kwargs):
        return self

    def insert(self, row):
        self.row = row
        return self

    def execute(self):
        return _Result()


class _Supabase:
    def __init__(self):
        self.query = _Query()

    def table(self, name):
        assert name == "pending_followups"
        return self.query


def test_explicit_followup_remains_available(monkeypatch) -> None:
    """External work can still request a concrete, explicit re-check."""
    db = _Supabase()
    monkeypatch.setattr(followups, "_sb", lambda: db)

    result = followups.schedule_followup(
        "room-1", "https://example.com のデプロイ完了を確認する", 90, "user-1"
    )

    assert result["scheduled"] is True
    assert db.query.row["room_id"] == "room-1"
    assert db.query.row["note"] == "https://example.com のデプロイ完了を確認する"
    assert datetime.fromisoformat(db.query.row["fire_at"]).tzinfo == timezone.utc


def test_text_based_auto_followup_heuristic_is_not_present() -> None:
    """A phrase such as '報告します' must never schedule a wake-up by itself."""
    assert not hasattr(followups, "text_promises_followup")
    assert not hasattr(followups, "maybe_autoschedule_for_promise")


class _Table:
    """In-memory pending_followups: enough of the query builder for status-guarded updates."""

    def __init__(self, rows):
        self.rows = rows
        self._patch = None
        self._filters = []

    def table(self, name):
        assert name == "pending_followups"
        self._patch, self._filters = None, []
        return self

    def update(self, patch):
        self._patch = patch
        return self

    def eq(self, key, value):
        self._filters.append(lambda r: r.get(key) == value)
        return self

    def in_(self, key, values):
        self._filters.append(lambda r: r.get(key) in values)
        return self

    def execute(self):
        hit = [r for r in self.rows if all(f(r) for f in self._filters)]
        for r in hit:
            r.update(self._patch)
        result = _Result()
        result.data = hit
        return result


def test_reschedule_does_not_revive_a_cancelled_watch(monkeypatch) -> None:
    """The wake turn cancelled its own watch; the reschedule that follows must leave it cancelled."""
    rows = [{"id": "w1", "status": "firing", "room_id": "room-1"}]
    monkeypatch.setattr(followups, "_sb", lambda: _Table(rows))

    assert followups.cancel_watch("w1", "room-1") is True
    followups.reschedule_watch("w1", "every", "note", {}, datetime.now(timezone.utc))

    assert rows[0]["status"] == "cancelled"


def test_reschedule_advances_a_live_watch(monkeypatch) -> None:
    rows = [{"id": "w1", "status": "firing", "room_id": "room-1"}]
    monkeypatch.setattr(followups, "_sb", lambda: _Table(rows))
    nxt = datetime(2026, 10, 25, tzinfo=timezone.utc)

    followups.reschedule_watch("w1", "every", "note", {"fire_count": 1}, nxt)

    assert rows[0]["status"] == "pending"
    assert rows[0]["fire_at"] == nxt.isoformat()
