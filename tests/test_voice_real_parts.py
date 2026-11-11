"""Real-content parts on the call's screen (2026-11-12): what the owner presses reaches the call; a lookup's parts go on
the screen as its answer is handed to the voice; the screen refuses what it cannot draw."""
import asyncio
import uuid

import pytest

from app.services import voice_calls, voice_lookup as L, voice_sideband as S, voice_stage


@pytest.fixture
def calls(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_calls, 'ROOT', tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_what_the_owner_presses_reaches_the_call_as_pointing(calls):
    voice_calls.begin('room-1', 'sess-1')
    sent, d = [], S.Dialogue()
    async def send(event): sent.append(event)
    feed = asyncio.create_task(S.chat_feed(send, 'room-1', d, lambda *a, **k: None))
    try:
        voice_calls.deliver('room-1', '地図 → 1 Personal Care', kind='touch')
        voice_calls.deliver('room-1', 'こんにちは')
        await asyncio.sleep(.8)
    finally:
        feed.cancel()
    words = ' '.join(t['text'] for t in d.recent() if t['role'] == 'user')
    assert '（画面で押した）地図 → 1 Personal Care' in words and '（チャットに送った）こんにちは' in words
    told = ' '.join(str(e.get('content') or '') for e in sent)
    assert '通話の画面で押したもの' in told and 'Personal Care' in told
    assert voice_calls.take('room-1', 0)[0] == ['地図 → 1 Personal Care', 'こんにちは']   # the old reader still reads both


def test_the_answer_and_its_parts_come_apart():
    spoken, parts = L.split_parts('仲江鍼灸院の仲江政史先生です。\n\n```openui-lang\nroot = Quote("院長 仲江 政史", "クリニック案内")\n```')
    assert spoken == '仲江鍼灸院の仲江政史先生です。'
    assert parts == 'root = Quote("院長 仲江 政史", "クリニック案内")'
    assert L.split_parts('部品なし') == ('部品なし', '')


def test_the_stage_shows_parts_at_once_and_refuses_what_it_cannot_draw(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_stage, 'ROOT', tmp_path)
    stage = voice_stage.Stage(str(uuid.uuid4()), 'room-x', S.Dialogue(), lambda *a, **k: None)
    ok = stage.show_parts('```openui-lang\nroot = Map([{label: "仲江鍼灸院", lat: 33.66, lng: 130.84}], "仲江先生の院")\n```', '仲江先生')
    assert ok == {'shown': True}
    assert stage.program.startswith('root = Map(') and stage.caption == '仲江先生'
    bad = stage.show_parts('root = Map(places: [], title: "x")')
    assert bad['shown'] is False
    assert stage.show_parts('root = Choice("q", ["a", "b"])')['shown'] is False   # answers need the chat


def test_a_lookup_is_told_to_show_the_real_thing():
    text = L.instructions()
    assert '```openui-lang' in text and '- Map(' in text and '- Quote(' in text and 'page_clip' in text
    assert '{parts}' not in text
    assert 'page_clip' in L.direct_names()
