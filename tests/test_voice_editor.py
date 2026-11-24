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
async def test_work_gets_verbatim_request_pointer_and_frame(monkeypatch, room):
    started = []
    async def execute(params, room_id, user_id, voice_handoff=False, internal_check=False):
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
    assert task.count('このテロップ赤くして') == 1 and 'call_frames' in task
    assert drawn and drawn[0][2]['playhead'] == 12.3


@pytest.mark.asyncio
async def test_a_call_not_from_the_editor_is_as_before(monkeypatch):
    monkeypatch.setattr(voice_editor, 'call_editor', lambda room_id: None)
    started = []
    async def execute(params, room_id, user_id, voice_handoff=False, internal_check=False):
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


@pytest.mark.asyncio
async def test_work_handed_over_by_the_general_backend_still_gets_the_moments(monkeypatch, room):
    """start_work (the general backend) passes the call's turns, not the call: the room tells it is a work's room."""
    started = []
    async def execute(params, room_id, user_id, voice_handoff=False, internal_check=False):
        started.append(params)
        return {'accepted': True, 'receipt': {'id': 'job-1'}}
    monkeypatch.setattr('app.services.command_center.execute', execute)
    monkeypatch.setattr('app.services.parallel_job_runner.room_model', lambda room: 'opus')
    monkeypatch.setattr(voice_editor, 'call_editor', lambda room_id: {'asset_room_id': 'assets', 'content_id': 'c1'})
    monkeypatch.setattr(voice_editor, 'draw_frame', lambda *a: None)
    d = Dialogue()
    d.editor = voice_editor.Moments('assets', 'c1')
    write_state(room)
    d.add('user', 'この字幕直して')
    await voice_router.start_chat_dan('u', 'r', [dict(t) for t in d.history], 'この字幕直して')
    assert '〔エディター: 再生位置 0:12.3' in started[0]['task'] and started[0]['task'].count('この字幕直して') == 1


@pytest.mark.asyncio
async def test_where_the_call_is_goes_with_the_question_of_where_a_request_goes(monkeypatch, room):
    from tests.test_voice_router import Judge, answer, router
    d_place = []
    j = Judge({'route': answer('make', .9), 'calendar': answer('other', .9)})
    r, sent, log = router(monkeypatch, j, said=['この字幕、直して'])
    r.dialogue.editor = voice_editor.Moments('assets', 'c1')
    got = await r.route()
    assert got[0] == 'make' and 'エディター' in j.asked[-1][0]['call_place']


def test_a_place_in_the_video_is_said_in_minutes_and_seconds():
    assert voice_say.speakable('note', '0:55.8のテロップを消すね') == '55秒のテロップを消すね'
    assert voice_say.speakable('note', '3:47.2の札') == '3分47秒の札'
    assert voice_say.speakable('answer', '14:05に始めた') == '14:05に始めた'   # a time of day stays


def test_the_speech_model_knows_the_call_is_from_the_editor(monkeypatch, room):
    from app.services import voice_live
    monkeypatch.setattr(voice_editor, 'call_editor', lambda room_id: {'asset_room_id': 'assets', 'content_id': 'c1'} if room_id == 'work' else None)
    assert 'エディター' in voice_live.session_config(room_id='work', user_id='u')['instructions']
    assert 'エディター' not in voice_live.session_config(room_id='chat', user_id='u')['instructions'].split('通話を始めた日')[1]


@pytest.mark.asyncio
async def test_one_call_moves_between_timelines_and_each_request_goes_where_it_was_said(monkeypatch, room):
    """11/24 本人: 1回の通話で、タイムラインを移りながらまとめて直しを頼みたい。頼みは言った時に見ていた作品の部屋へ行き、
    報告は通話の部屋へ戻る（origin）。動画Aで言った位置は、動画Bの頼みに混ざらない。"""
    started = []
    async def execute(params, room_id, user_id, voice_handoff=False, internal_check=False):
        started.append((params, room_id))
        return {'accepted': True, 'receipt': {'id': f'job-{len(started)}'}}
    monkeypatch.setattr('app.services.command_center.execute', execute)
    monkeypatch.setattr('app.services.parallel_job_runner.room_model', lambda room: 'opus')
    monkeypatch.setattr(voice_editor, 'draw_frame', lambda *a: None)
    works = {'room-a': {'asset_room_id': 'assets', 'content_id': 'c1'}, 'room-b': {'asset_room_id': 'assets', 'content_id': 'c2'}}
    monkeypatch.setattr(voice_editor, 'call_editor', lambda room_id: works.get(room_id))
    d = Dialogue()
    d.home_room = 'room-a'
    assert d.set_focus('room-a')                     # the call is placed from work A
    write_state(room)
    d.add('user', 'このテロップ赤くして')
    await voice_router.start_chat_dan('u', 'room-a', d, 'このテロップ赤くして')
    d.add('assistant', 'うん、赤にするね')
    assert d.set_focus('room-b') and d.editor.content_id == 'c2'   # he opens work B in the same window, the call goes on
    write_state(room, content_id='c2', playhead=40.0, selected=[{'id': 'v1'}])
    d.add('user', 'ここのBGM下げて')
    await voice_router.start_chat_dan('u', 'room-a', d, 'ここのBGM下げて')
    (first, origin1), (second, origin2) = started
    assert 'target_room_id' not in first and origin1 == 'room-a'
    assert second['target_room_id'] == 'room-b' and origin2 == 'room-a'
    assert '作品: c2' in second['task'] and '0:40.0' in second['task'] and '0:12.3' not in second['task']
    assert voice_router.work_room(d, 'room-a') == 'room-b'


def test_a_chat_room_on_the_screen_is_the_place_and_the_target(monkeypatch):
    monkeypatch.setattr(voice_editor, 'call_editor', lambda room_id: None)
    monkeypatch.setattr('app.services.prompt_store.fill', lambda pid, **kw: f"{pid}:{kw.get('title')}")
    d = Dialogue()
    d.home_room = 'home'
    d.set_focus('home')
    assert d.place() == ''
    d.set_focus('room-x', '中村さん')
    d.add('user', 'この部屋の件、返信の下書き作って')
    assert d.editor is None and d.place() == 'call/focus-room:中村さん'
    assert voice_router.work_room(d, 'home') == 'room-x'


def test_the_room_of_a_request_is_where_he_finished_saying_it():
    d = Dialogue()
    d.focus_room = 'a'
    d.add('user', 'まず')
    d.focus_room = 'b'
    d.add('user', 'これ直して')
    assert d.history[-1]['room'] == 'b'
    assert voice_router.work_room([{'role': 'user', 'text': 'x'}], 'call') == 'call'


def test_playing_playhead_is_carried_on_from_the_last_report():
    """While playing the editor tells the playhead every 0.5 s; Dan reads where it is now, not where it was told
    (11/24 the owner: 「見えてる時もリアルタイムや正確ではなく、ちょっとズレてた」)."""
    now = 1000.0
    st = {'content_id': 'c1', 'editor': 'editor', 'playhead': 12.0, 'playing': True, 'at': now - 0.4, 'selected': []}
    assert voice_editor.moment_of(st, 'c1', now)['playhead'] == 12.4
    assert voice_editor.moment_of({**st, 'at': now - 60}, 'c1', now)['playhead'] == 15.0   # the tab stopped telling: at most 3 s
    assert voice_editor.moment_of({**st, 'playing': False}, 'c1', now)['playhead'] == 12.0   # stopped: as told
    assert voice_editor.moment_of({k: v for k, v in st.items() if k != 'at'}, 'c1', now)['playhead'] == 12.0
