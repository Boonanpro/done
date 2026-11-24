"""エディターのタイムラインに書いた指示・効果音の一覧・作品ごとの編集の順番待ち（app/services/editor_instructions.py）。"""
import json
import threading
import time
from pathlib import Path

import pytest


@pytest.fixture
def asset_root(tmp_path, monkeypatch):
    from app.api import production_asset_routes as par
    from app.services import timeline_draft as td
    monkeypatch.setattr(par, 'ASSET_ROOT', tmp_path)
    monkeypatch.setattr(td, 'UPLOAD_ROOT', tmp_path)
    return tmp_path


def _room(root: Path, room: str, assets, contents=()):
    d = root / room
    d.mkdir(parents=True, exist_ok=True)
    (d / 'assets.json').write_text(json.dumps(list(assets), ensure_ascii=False), encoding='utf-8')
    (d / 'contents.json').write_text(json.dumps(list(contents), ensure_ascii=False), encoding='utf-8')
    return d


def _sfx(root, room, aid, name, dur=0.5):
    f = root / room / f'{aid}.wav'
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b'RIFF0000WAVE')
    return {'id': aid, 'kind': 'audio', 'filename': f'SE {name}', 'local_path': str(f), 'metadata': {'duration': dur}}


def test_task_carries_place_shape_words_and_image():
    from app.services.editor_instructions import build_task
    ann = {'id': 'a1', 'kind': 'marker', 'intent': 'comment', 'start': 83.4, 'end': 84.4,
           'note': 'ここに和太鼓のドン', 'data': {'point': {'x': 0.25, 'y': 0.5}}}
    text = build_task(ann, 'スヤさん1本目', '/tmp/x.png')
    assert '1:23.4〜1:24.4' in text and '83.40〜84.40' in text
    assert '左から25%・上から50%' in text
    assert '「ここに和太鼓のドン」' in text and '/tmp/x.png' in text
    find = build_task({'kind': 'note', 'intent': 'generate', 'start': 10, 'end': 15, 'note': '札束',
                       'data': {'mode': 'find'}}, 't', None)
    assert '5.0秒' in find and 'AIで作らない' in find


def test_marks_are_drawn_on_the_frame(tmp_path):
    from PIL import Image
    from app.services.editor_instructions import _draw_marks
    src = tmp_path / 'f.png'
    Image.new('RGB', (320, 180), (0, 0, 0)).save(src)
    out = tmp_path / 'o.png'
    assert _draw_marks(src, out, {'kind': 'freehand', 'data': {'points': [{'x': 0.1, 'y': 0.1}, {'x': 0.9, 'y': 0.9}]}})
    img = Image.open(out)
    assert img.getpixel((160, 90))[0] > 200          # 線の真ん中が赤
    assert not _draw_marks(src, out, {'kind': 'note', 'data': {}})


def test_sfx_library_ranks_by_use_and_prefers_this_room(asset_root):
    a = _sfx(asset_root, 'roomA', 'a1', '和太鼓でドン')
    b = _sfx(asset_root, 'roomA', 'a2', 'シャキーン1')
    seq = {'tracks': [{'id': 't', 'type': 'audio', 'clips': [{'asset_id': 'a2'}, {'asset_id': 'a2'}, {'asset_id': 'a1'}]}]}
    _room(asset_root, 'roomA', [a, b], [{'id': 'c1', 'timeline': {'sequence': seq}}])
    c = _sfx(asset_root, 'roomB', 'b1', '和太鼓でドン')
    _room(asset_root, 'roomB', [c, {'id': 'v', 'kind': 'video', 'filename': 'SE 映像は入れない'}])
    from app.services.editor_instructions import sfx_library
    lib = sfx_library('roomB')
    assert [r['name'] for r in lib] == ['シャキーン1', '和太鼓でドン']
    don = lib[1]
    assert don['in_room_asset_id'] == 'b1' and don['source_room_id'] == 'roomB'
    assert lib[0]['in_room_asset_id'] is None and lib[0]['uses'] == 2


def test_use_sfx_copies_once_into_the_room(asset_root):
    a = _sfx(asset_root, 'roomA', 'a1', 'チリン', 3.1)
    _room(asset_root, 'roomA', [a])
    _room(asset_root, 'roomB', [])
    from app.services.editor_instructions import use_sfx
    row = use_sfx('roomB', 'roomA', 'a1')
    assert row['filename'] == 'SE チリン' and Path(row['local_path']).exists()
    assert Path(row['local_path']).parent == asset_root / 'roomB'
    again = use_sfx('roomB', 'roomA', 'a1')
    assert again['id'] == row['id']
    assert len(json.loads((asset_root / 'roomB' / 'assets.json').read_text())) == 1


def test_content_edit_lock_serialises_two_dans(asset_root):
    from app.services import timeline_draft as td
    (asset_root / 'r').mkdir()
    order = []

    def step(name):
        with td.content_edit_lock('r', 'c1') as got:
            assert got
            order.append(name + '+')
            time.sleep(0.2)
            order.append(name + '-')

    ts = [threading.Thread(target=step, args=(n,)) for n in 'ab']
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert order in (['a+', 'a-', 'b+', 'b-'], ['b+', 'b-', 'a+', 'a-'])


@pytest.fixture
def job_root(tmp_path, monkeypatch):
    from app.services import command_job_state as state
    root = tmp_path / 'jobs'
    root.mkdir()
    monkeypatch.setattr(state, 'ROOT', root)
    return root


J1 = '11111111-1111-4111-8111-111111111111'
J2 = '22222222-2222-4222-8222-222222222222'


def _job(root, jid, **kw):
    s = {'id': jid, 'user_id': 'u1', 'room_id': 'r1', 'engine': 'parallel', 'state': 'completed',
         'created_at': '2026-11-01T00:00:00+00:00', 'updated_at': '2026-11-01T00:00:00+00:00'}
    s.update(kw)
    (root / f'{jid}.json').write_text(json.dumps(s, ensure_ascii=False), encoding='utf-8')


def test_resent_instruction_carries_the_previous_try(job_root):
    """11/17 本人「直して返してきたものが十分じゃなくて、もう少しこうしなきゃいけない時」→ 書き直して送ると前の回を土台に直す。"""
    from app.services.editor_instructions import _previous, build_task
    first = build_task({'kind': 'marker', 'start': 3, 'note': 'ここで寄る'}, 't', None)
    _job(job_root, J1, task=first, result='3秒で120%に寄せました。')
    ann = {'kind': 'marker', 'start': 3, 'note': 'もっと強く寄って', 'data': {'job_id': J1}}
    prev = _previous('u1', ann)
    assert prev == {'note': 'ここで寄る', 'result': '3秒で120%に寄せました。'}
    text = build_task(ann, 't', None, prev)
    assert '「ここで寄る」' in text and '120%' in text and '「もっと強く寄って」' in text
    assert _previous('someone-else', ann) is None
    assert _previous('u1', {'kind': 'marker', 'start': 3, 'note': 'x'}) is None


def test_room_work_text_keeps_the_whole_history_of_the_work(job_root):
    from app.services.editor_instructions import room_work_text
    _job(job_root, J1, title='ピン 0:03 寄る', result='寄せました')   # 2週間以上前でも履歴に残る
    _job(job_root, J2, room_id='r2', title='別の作品')
    text = room_work_text('r1')
    assert 'ピン 0:03 寄る' in text and '寄せました' in text and '別の作品' not in text
    assert 'チャットには出していない' in text


def test_send_starts_quiet(asset_root, job_root, monkeypatch):
    """結果は指示の欄にだけ出し、横のチャットに報告しない（11/17 本人）。"""
    import asyncio
    from app.services import editor_instructions as ei, editor_rooms, parallel_job_runner
    _room(asset_root, 'lib', [], [{'id': 'c1', 'title': 't'}])
    seen = {}

    async def fake_room(user_id, asset_room_id, content_id):
        return {'room_id': 'work-room'}

    async def fake_start(room_id, user_id, task, **kw):
        seen.update(kw, room_id=room_id, task=task)
        return {'id': 'j9', 'state': 'queued'}

    monkeypatch.setattr(editor_rooms, 'ensure_room', fake_room)
    monkeypatch.setattr(parallel_job_runner, 'start', fake_start)
    monkeypatch.setattr(ei, 'frame_path', lambda *a: None)
    out = asyncio.run(ei.send('u1', 'lib', 'c1', {'id': 'a', 'kind': 'marker', 'start': 1, 'note': '音を足して'}))
    assert out['job_id'] == 'j9' and seen['quiet'] is True and seen['room_id'] == 'work-room'
    assert 'チャットには出ない' in seen['task']


def test_clip_comment_tells_dan_which_clips_and_earlier_comments(asset_root, job_root, monkeypatch):
    """11/25 本人「ピンという項目いらない。クリップを選択したらそれに対してコメントできるようにして修正指示が出せるように」。
    選んだクリップの中身（id・段・文字・素材の区間）と、同じクリップに前に送ったコメントの結果が作業に渡る。"""
    import asyncio
    from app.services import editor_instructions as ei, editor_rooms, parallel_job_runner
    seq = {'tracks': [
        {'id': 't0', 'type': 'video', 'clips': [{'id': 'v1', 'asset_id': 'a1', 'timeline_start': 10, 'timeline_end': 14,
                                                'source_start': 2, 'source_end': 6}]},
        {'id': 't1', 'type': 'caption', 'clips': [{'id': 'c9', 'text': '24歳の夏', 'timeline_start': 20, 'timeline_end': 21.5}]},
    ]}
    old = {'id': 'cc_old', 'kind': 'clip', 'intent': 'comment', 'start': 20, 'end': 21.5, 'note': '明朝体にして',
           'data': {'clip_ids': ['c9'], 'job_id': J1}}
    other = {'id': 'cc_other', 'kind': 'clip', 'note': '別のクリップ', 'data': {'clip_ids': ['v1']}}
    _room(asset_root, 'lib', [{'id': 'a1', 'kind': 'video', 'filename': 'S24録画.mp4'}],
          [{'id': 'c1', 'title': 't', 'timeline': {'sequence': seq, 'annotations': [old, other]}}])
    _job(job_root, J1, task=ei.build_task(old, 't', None), result='明朝体に戻しました。')
    seen = {}

    async def fake_room(user_id, asset_room_id, content_id):
        return {'room_id': 'work-room'}

    async def fake_start(room_id, user_id, task, **kw):
        seen.update(kw, task=task)
        return {'id': 'j9', 'state': 'queued'}

    monkeypatch.setattr(editor_rooms, 'ensure_room', fake_room)
    monkeypatch.setattr(parallel_job_runner, 'start', fake_start)
    monkeypatch.setattr(ei, 'frame_path', lambda *a: None)
    ann = {'id': 'cc_new', 'kind': 'clip', 'intent': 'comment', 'start': 20, 'end': 21.5, 'note': 'もっと大きく',
           'data': {'clip_ids': ['c9'], 'at': 20.6}}
    asyncio.run(ei.send('u1', 'lib', 'c1', ann))
    task = seen['task']
    assert '選んだクリップへのコメント' in task and '「もっと大きく」' in task
    assert 'id=c9' in task and '24歳の夏' in task
    assert '「明朝体にして」→ 明朝体に戻しました。' in task and '別のクリップ' not in task
    assert seen['title'].startswith('コメント')
    # 動画のクリップは素材の名前と使っている区間まで渡る
    lines = ei.clip_lines('lib', {'timeline': {'sequence': seq}}, {'data': {'clip_ids': ['v1', 'gone']}})
    assert 'S24録画.mp4' in lines[0] and '2.00〜6.00秒' in lines[0] and '見当たらない' in lines[1]


def test_clip_comment_frame_is_saved_without_marks(tmp_path):
    from PIL import Image
    from app.services.editor_instructions import _draw_marks
    src = tmp_path / 'f.png'
    Image.new('RGB', (32, 18), (10, 20, 30)).save(src)
    out = tmp_path / 'o.png'
    assert _draw_marks(src, out, {'kind': 'clip', 'data': {'clip_ids': ['x']}})
    assert Image.open(out).getpixel((5, 5)) == (10, 20, 30)
