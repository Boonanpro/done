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
