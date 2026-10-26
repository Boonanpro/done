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


def test_wake_room_hands_the_report_to_the_rooms_dan(monkeypatch) -> None:
    """10-25: 報告の札＋まとめの2通をやめ、報告は部屋のダンに渡して日本語の1通（または何も無し）にする。"""
    from app.services import followups
    made = []
    monkeypatch.setattr(followups, 'create_watch', lambda *a, **k: made.append((a, k)) or {'scheduled': True})
    s = {'id': 'j1', 'room_id': 'r1', 'user_id': 'u1', 'title': '点検', 'task': 'x'}
    runner.wake_room(s, True, 'The changes are complete.')
    (args, kw), = made
    assert args[0] == 'r1' and args[2] == 'at' and kw['delay_seconds'] == 3
    note = args[3]
    assert '「点検」が止まった' in note and '1通だけ' in note and '日本語' in note
    assert 'The changes are complete.' in note and 'WATCH_NO_CHANGE' in note


def _deliver_env(monkeypatch, state_row):
    import asyncio
    from app.services import voice_calls
    from app.services.chat_service import ChatService
    rows = {'j1': dict(state_row)}
    monkeypatch.setattr(runner.state, 'read', lambda job_id: rows[job_id])
    monkeypatch.setattr(runner.state, 'change', lambda job_id, fn: fn(rows[job_id]))
    monkeypatch.setattr(voice_calls, 'active', lambda room: False)

    async def named(job_id, wait=30):
        return None
    monkeypatch.setattr(runner, 'ensure_named', named)

    async def no_post(*a, **k):
        raise AssertionError('the report must not be posted in the chat')
    monkeypatch.setattr(ChatService, 'send_message', no_post)
    woke = []
    monkeypatch.setattr(runner, 'wake_room', lambda s, failed, report='': woke.append(report))
    return rows, woke, lambda text: asyncio.run(runner.deliver('j1', text))


def test_deliver_posts_nothing_and_wakes_the_room_once(monkeypatch) -> None:
    rows, woke, deliver = _deliver_env(monkeypatch, {'id': 'j1', 'room_id': 'r1', 'user_id': 'u1', 'title': '点検', 'state': 'completed'})
    assert deliver('The changes are complete.') is None
    assert woke == ['The changes are complete.'] and rows['j1']['delivered_revision'] == 0


def test_deliver_of_a_silent_report_does_nothing(monkeypatch) -> None:
    for text in ('WATCH_NO_CHANGE', '  WATCH_NO_CHANGE\n', '```\nWATCH_NO_CHANGE\n```'):
        rows, woke, deliver = _deliver_env(monkeypatch, {'id': 'j1', 'room_id': 'r1', 'user_id': 'u1', 'title': '点検', 'state': 'completed'})
        deliver(text)
        assert woke == []
