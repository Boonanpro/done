"""Dan is one person: during a call, what the owner sends to the room's chat goes to the Dan on the call."""
import asyncio
import os

import pytest

from app.services import voice_calls, voice_sideband as S


@pytest.fixture
def calls(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_calls, 'ROOT', tmp_path)
    return tmp_path


def test_a_call_is_active_while_its_process_lives_and_ends_with_it(calls, monkeypatch):
    assert voice_calls.active('room-1') is None
    voice_calls.begin('room-1', 'sess-1')
    assert voice_calls.active('room-1')['session_id'] == 'sess-1'
    voice_calls.end('room-1', 'other-session')          # another call's end does not end this one
    assert voice_calls.active('room-1')
    monkeypatch.setattr('psutil.pid_exists', lambda pid: False)
    assert voice_calls.active('room-1') is None          # its process is gone: a left-over file is not a call
    monkeypatch.undo(); monkeypatch.setattr(voice_calls, 'ROOT', calls)
    voice_calls.end('room-1', 'sess-1')
    assert voice_calls.active('room-1') is None


@pytest.mark.asyncio
async def test_what_the_owner_sends_reaches_the_call_silently_and_the_work_handed_on(calls, monkeypatch):
    voice_calls.begin('room-1', 'sess-1')
    sent, d = [], S.Dialogue()
    async def send(event): sent.append(event)
    feed = asyncio.create_task(S.chat_feed(send, 'room-1', d, lambda *a, **k: None))
    try:
        voice_calls.deliver('room-1', 'https://x.com/someone/status/1')
        await asyncio.sleep(.8)
    finally:
        feed.cancel()
    assert [e['type'] for e in sent] == ['session.thinking.append'] and 'https://x.com/someone/status/1' in sent[0]['content']
    assert d.recent()[-1]['role'] == 'user' and 'x.com/someone' in d.recent()[-1]['text']


def test_the_backend_reads_the_room_conversation_and_has_a_page_reader():
    from app.services.voice_responses import delegation
    config = delegation(records='ユーザー: これ見て https://x.com/a\nDan: 投稿の中身は…')['responses']
    assert 'この部屋のこれまでの会話' in config['instructions'] and '投稿の中身は' in config['instructions']
    names = [t['name'] for t in config['tools']]
    assert 'read_page' in names
    show = next(t for t in config['tools'] if t['name'] == 'show_in_chat')
    assert 'required' not in show['parameters']   # text alone may be shown
