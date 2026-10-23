"""Parallel job reports as a one-line card, the room's Dan woken to answer, and names for unnamed jobs (2026-10-23)."""
from datetime import datetime, timedelta, timezone

from app.services import parallel_job_runner as runner


def test_placeholder_name_is_not_the_head_of_the_instruction() -> None:
    task = 'あなたはダン開発室の付箋「chat-short-reply（返事を人の短さに）」を確かめるダン。直さない。気づいたことを一覧にする'
    assert runner.placeholder_name(task) == 'chat-short-reply（返事を人の短さに）'
    assert runner.placeholder_name('Opusでこの部屋のログを全部読んで、問題点を洗い出して報告して') == '作業'


def test_report_card() -> None:
    s = {'id': 'j1', 'title': '返事の短さの点検', 'task': 'x', 'model': 'astra'}
    assert runner.report_card(s, False) == {'job_id': 'j1', 'title': '返事の短さの点検', 'state': 'done', 'model_label': 'GPT-6'}
    assert runner.report_card({**s, 'title': ''}, True)['state'] == 'stopped'


def test_wake_room_once(monkeypatch) -> None:
    from app.services import followups
    made = []
    monkeypatch.setattr(followups, 'create_watch', lambda *a, **k: made.append((a, k)) or {'scheduled': True})
    s = {'id': 'j1', 'room_id': 'r1', 'user_id': 'u1', 'title': '点検', 'task': 'x'}
    soon = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    monkeypatch.setattr(followups, 'list_watches', lambda room: [{'kind': 'at', 'fire_at': soon}])
    assert runner.wake_room(s, False) is None and not made          # a wake-up is already due: that turn reads the report
    monkeypatch.setattr(followups, 'list_watches', lambda room: [])
    runner.wake_room(s, True)
    (args, kw), = made
    assert args[0] == 'r1' and args[2] == 'at' and kw['delay_seconds'] == 3
    assert '「点検」が止まった' in args[3] and '短く1通だけ' in args[3]
