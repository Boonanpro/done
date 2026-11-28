"""The call of 2026-11-27 23:41–23:50 from Suya's second video in the editor.

- 23:41–23:44: the owner asked for a plain summary, the background blurred behind a white panel, the text flowing in, and
  the orange 「アイデアは」 caption gone, while Dan said 「うん」 some twenty times. The work got only the last sentence
  (「オレンジのテロップを消して」): only that was fixed. A request from the editor now carries every word of it.
- 23:44–23:46: the title top left, the font, the last video's thumbnail. Dan said 「聞いてるよ。今やってるからね」 and handed
  nothing, while the ear judged it work all along. The router now hands such words itself."""
import asyncio
import json
import time

import pytest

from app.services import voice_editor, voice_router
from app.services.voice_sideband import Dialogue


SEQ = {'tracks': [{'kind': 'caption', 'clips': [{'id': 'cap1', 'text': 'アイデアは', 'timeline_start': 44, 'timeline_end': 47}]}]}

SUMMARY_CALL = [
    ('user', '前回の動画から始まった企画っていうのは、こういう感じで作るんじゃなくて、もっとシンプルにしてほしい'),
    ('assistant', 'うん'),
    ('user', '前回のあらすじみたいに普通に文字で表現してくれた方がいいのと、背景を全部紺色にするんじゃなくて'),
    ('assistant', 'うん'),
    ('user', '画面の背景は映ってるけどぼかされてて、真ん中に白い背景があって、そこに文字が流れてくる感じ'),
    ('assistant', 'あー'),
    ('user', 'あと、アイデアはっていうオレンジのテロップを消して'),
]


@pytest.fixture(autouse=True)
def router_on(monkeypatch):
    monkeypatch.setenv('DAN_VOICE_ROUTER', '1')
    monkeypatch.setenv('DAN_VOICE_PLAIN', '1')
    monkeypatch.setattr('app.services.command_job_state.list_owned', lambda user, room: [])


@pytest.fixture
def room(monkeypatch, tmp_path):
    from app.services import timeline_draft as td, timeline_live as tl
    monkeypatch.setattr(td, '_room_dir', lambda rid: tmp_path / rid)
    (tmp_path / 'assets').mkdir()
    monkeypatch.setattr(tl, 'live_sequence', lambda rid, cid: ({'title': 'スヤさん2本目'}, SEQ))
    monkeypatch.setattr(tl, '_assets', lambda rid: {})
    monkeypatch.setattr(voice_editor, 'call_editor', lambda room_id: {'asset_room_id': 'assets', 'content_id': 'c1'})
    monkeypatch.setattr(voice_editor, 'draw_frame', lambda *a: None)
    return tmp_path / 'assets'


def write_state(d, playhead):
    (d / 'editor_state.json').write_text(json.dumps({'content_id': 'c1', 'editor': 'editor', 'playhead': playhead,
                                                     'playing': False, 'selected': [], 'source': 'web'}), encoding='utf-8')


def router(dialogue, quiet=5.0):
    sent, log = [], []
    async def send(event): sent.append(event)
    now = time.monotonic()
    dialogue.heard_at = now - quiet
    dialogue.delegated_at = now - 120
    r = voice_router.Router('s', 'u', 'room-suya', dialogue, send, lambda phase, **f: log.append((phase, f)),
                            {'dan_words': now - 3}, backend={'model': 'm'}, observe_only=True)
    return r, sent, log


@pytest.mark.asyncio
async def test_a_request_from_the_editor_carries_every_word_said_between_dans_uns(monkeypatch, room):
    started = []
    async def execute(params, room_id, user_id, voice_handoff=False, internal_check=False):
        started.append(params)
        return {'accepted': True, 'receipt': {'id': 'job-1'}}
    monkeypatch.setattr('app.services.command_center.execute', execute)
    monkeypatch.setattr('app.services.parallel_job_runner.room_model', lambda room: 'opus')
    d = Dialogue()
    d.editor = voice_editor.Moments('assets', 'c1', room_id='room-suya')
    for i, (role, text) in enumerate(SUMMARY_CALL):
        write_state(room, 44.0 + i)
        d.editor.read_at = 0
        d.add(role, text)
    r, _, _ = router(d)
    r.look = True   # Jev said the request needs where he was on the screen
    await r.run('make', '', '', 'del_1', time.monotonic())
    await asyncio.sleep(.05)
    task = started[0]['task']
    request = task.split('作品: c1')[0]   # the request, before the transcript and the notes
    for words in ('もっとシンプルに', '普通に文字で', '紺色にするんじゃなくて', 'ぼかされて', '白い背景', 'オレンジのテロップを消して'):
        assert words in request, words
    assert '再生位置 0:44.0' in request and '再生位置 0:50.0' in request   # where he was at the first and the last words


@pytest.mark.asyncio
async def test_the_general_backend_hands_the_whole_request_too(monkeypatch, room):
    """luna's start_work used to pass the owner's last turn; it passes the request the router is working on."""
    from app.services import voice_responses
    got = []
    async def start(user_id, room_id, dialogue, words, carried='', internal_check=False):
        got.append(words)
        return {'accepted': True, 'receipt': {'id': 'job-1'}}
    monkeypatch.setattr(voice_router, 'start_chat_dan', start)
    monkeypatch.setattr(voice_router, 'enabled', lambda: True)
    d = Dialogue()
    for role, text in SUMMARY_CALL:
        d.add(role, text)
    d.request_words = voice_router.Router('s', 'u', 'r', d, None, lambda *a, **k: None, {}, observe_only=True).request_words()
    out = await voice_responses.run_function('start_work', {'task': '消す'}, 'u', 'r', d)
    assert out.get('accepted') and 'もっとシンプルに' in got[0] and 'オレンジのテロップを消して' in got[0]


HEARD_CALL = [
    ('user', 'で、左上に企画名をずっと出しておいてほしい'),
    ('assistant', 'うん'),
    ('user', 'あとフォントは全部小塚ゴシックのHにして、前回のサムネも左上に出して'),
    ('assistant', '聞いてるよ。今やってるからね'),
]


def heard(d, route='make', probability=.9, at=None):
    d.routing_events.append(dict(words='…', turn=2, preliminary=True, route=route, probability=probability,
                                 at=time.monotonic() - 6 if at is None else at))


@pytest.mark.asyncio
async def test_words_the_ear_heard_as_work_are_handed_when_dan_hands_nothing():
    d = Dialogue()
    for role, text in HEARD_CALL:
        d.add(role, text)
    r, _, log = router(d)
    heard(d)
    assert r.unrouted_request()
    routed = []
    async def route(): return 'make', '', '', .9, 120
    async def to_chat_dan(words, route, delegation_id, created, carried=''): routed.append((delegation_id, words))
    r.route, r.to_chat_dan = route, to_chat_dan
    r.watching = asyncio.ensure_future(r.watch_promises())
    try:
        await asyncio.sleep(1.0)
        assert len(routed) == 1 and routed[0][0].startswith('auto-')
        assert '企画名' in routed[0][1] and '小塚ゴシック' in routed[0][1]   # both of his turns
        assert ('promise_unrouted', {'why': 'heard'}) in log
        assert not r.unrouted_request()   # once
        r.delegated('del_late')   # the speech model hands the same words late: not a second job
        await asyncio.sleep(.2)
        assert len(routed) == 1 and any(p == 'route_already_handed' for p, _ in log)
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_nothing_is_handed_when_it_was_not_work_or_was_handed_or_he_is_still_talking():
    cases = [dict(route='status'), dict(route='other'), dict(probability=.3), dict(at=time.monotonic() - 300)]
    for kw in cases:
        d = Dialogue()
        for role, text in HEARD_CALL:
            d.add(role, text)
        r, _, _ = router(d)
        r.marked_at = time.monotonic() - 60   # the last delegation came after the judgment of at=-300
        heard(d, **kw)
        try: assert not r.unrouted_request(), kw
        finally: await r.close()
    d = Dialogue()
    for role, text in HEARD_CALL:
        d.add(role, text)
    r, _, _ = router(d, quiet=1.0)   # he paused only a second
    heard(d)
    assert not r.unrouted_request()
    r, _, _ = router(d)
    d.delegated_at = d.heard_at + .1   # Dan handed it
    heard(d)
    assert not r.unrouted_request()
    await r.close()
