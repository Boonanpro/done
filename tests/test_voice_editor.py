"""A call from the editor (voice_editor, 2026-11-17): the work that fixes what the owner said gets where he was in the
editor while he said it, not where the editor is when the work starts; nothing is given while he speaks."""
import asyncio
import json
import time

import pytest

from app.services import voice_editor, voice_router, voice_say
from app.services.voice_sideband import Dialogue


SEQ = {'tracks': [
    {'kind': 'video', 'clips': [{'id': 'v1', 'asset_id': 'a1', 'timeline_start': 0, 'timeline_end': 30}]},
    {'kind': 'caption', 'clips': [{'id': 'cap7', 'text': 'ここが大事', 'timeline_start': 10, 'timeline_end': 14}]},
]}


@pytest.fixture
def room(monkeypatch, tmp_path):
    from app.services import timeline_draft as td, timeline_live as tl
    monkeypatch.setattr(td, '_room_dir', lambda rid: tmp_path / rid)
    (tmp_path / 'assets').mkdir()
    monkeypatch.setattr(tl, 'live_sequence', lambda rid, cid: ({'title': 't'}, SEQ))
    monkeypatch.setattr(tl, '_assets', lambda rid: {'a1': {'filename': 'みきさん 撮り直し.mp4'}})
    return tmp_path / 'assets'


def write_state(d, **over):
    state = {'content_id': 'c1', 'editor': 'editor', 'playhead': 12.3, 'playing': False,
             'selected': [{'id': 'cap7'}], 'source': 'web'}
    state.update(over)
    (d / 'editor_state.json').write_text(json.dumps(state), encoding='utf-8')


def test_each_turn_keeps_where_the_owner_was_while_saying_it(room):
    d = Dialogue()
    d.editor = voice_editor.Moments('assets', 'c1')
    write_state(room, pointer={'x': .5, 'y': .8, 'ids': ['cap7', 'v1'], 'pressed': False, 'inside': True, 'at': time.time()})
    d.add('user', 'ここのテロップ')
    d.editor.read_at = 0
    d.add('user', 'もう少し大きく')            # nothing moved: one moment
    assert len(d.history[0]['editor']) == 1
    d.add('assistant', 'うん')
    time.sleep(.01)
    write_state(room, playhead=20.0, selected=[], pointer=None)   # the playhead moved on while Dan answered
    d.editor.read_at = 0
    d.add('user', 'あとここも')
    m0, m1 = d.history[0]['editor'][0], d.history[2]['editor'][0]
    assert m0['playhead'] == 12.3 and m0['pointer']['ids'] == ['cap7', 'v1'] and m1['playhead'] == 20.0 and 'pointer' not in m1
    text = voice_editor.turns_text(d.history, 'assets', 'c1')
    assert '本人: ここのテロップもう少し大きく' in text
    assert '再生位置 0:12.3' in text and 'テロップ「ここが大事」（cap7' in text and '画面の下真ん中' in text
    assert 'ダン: うん' in text and '再生位置 0:20.0' in text


def test_a_spot_the_mouse_left_long_ago_is_not_pointed_at():
    now = time.time()
    st = {'content_id': 'c1', 'editor': 'editor', 'playhead': 3, 'selected': [],
          'pointer': {'x': .1, 'y': .1, 'ids': ['v1'], 'inside': False, 'at': now - 30}}
    assert 'pointer' not in voice_editor.moment_of(st, 'c1', now)
    st['pointer']['at'] = now - 2
    assert voice_editor.moment_of(st, 'c1', now)['pointer']['ids'] == ['v1']
    assert voice_editor.moment_of({**st, 'content_id': 'other'}, 'c1', now) is None   # another work is open


@pytest.mark.asyncio
async def test_the_work_gets_the_moments_the_frames_and_says_first_what_it_will_fix(monkeypatch, room):
    started = []
    async def execute(params, room_id, user_id, voice_handoff=False):
        started.append(params)
        return {'accepted': True, 'receipt': {'id': 'job-1'}}
    monkeypatch.setattr('app.services.command_center.execute', execute)
    monkeypatch.setattr('app.services.parallel_job_runner.room_model', lambda room: 'opus')
    drawn = []
    monkeypatch.setattr(voice_editor, 'draw_frame', lambda *a: drawn.append(a))
    d = Dialogue()
    d.editor = voice_editor.Moments('assets', 'c1')
    write_state(room, pointer={'x': .5, 'y': .8, 'ids': ['cap7'], 'pressed': True, 'inside': True, 'at': time.time()})
    d.add('user', 'このテロップ赤くして')
    await voice_router.start_chat_dan('u', 'r', d, 'このテロップ赤くして')
    await asyncio.sleep(.05)
    task = started[0]['task']
    assert '〔エディター: 再生位置 0:12.3' in task and '押した所' in task
    assert '【途中】' in task and '直す場所と中身' in task and 'call_frames' in task
    assert drawn and drawn[0][2]['playhead'] == 12.3


@pytest.mark.asyncio
async def test_a_call_not_from_the_editor_is_as_before(monkeypatch):
    started = []
    async def execute(params, room_id, user_id, voice_handoff=False):
        started.append(params)
        return {'accepted': True, 'receipt': {'id': 'job-1'}}
    monkeypatch.setattr('app.services.command_center.execute', execute)
    monkeypatch.setattr('app.services.parallel_job_runner.room_model', lambda room: 'opus')
    d = Dialogue()
    d.add('user', '美容院の空きを見て')
    await voice_router.start_chat_dan('u', 'r', d, '美容院の空きを見て')
    assert '〔エディター' not in started[0]['task'] and '本人: 美容院の空きを見て' in started[0]['task']


@pytest.mark.asyncio
async def test_nothing_is_given_while_the_owner_is_speaking():
    sent, last_word = [], {'at': time.monotonic()}
    async def send(event):
        sent.append((time.monotonic(), event))
    send.owner_speaking = lambda: time.monotonic() - last_word['at'] < .3
    t0 = time.monotonic()
    task = asyncio.ensure_future(voice_say.say(send, 'note', '0:12のテロップを赤にするね'))
    for _ in range(4):                 # he goes on talking for about 0.4 s
        await asyncio.sleep(.1)
        last_word['at'] = time.monotonic()
        assert not sent
    await task
    assert sent and sent[0][0] - t0 >= .6   # given after he had been quiet a moment


@pytest.mark.asyncio
async def test_a_send_without_the_owners_voice_gives_at_once():
    sent = []
    async def send(event): sent.append(event)
    await voice_say.say(send, 'answer', 'はい', None, 'del_1')
    assert sent[0]['delegation_id'] == 'del_1'
