"""サムネは動画とひと組（2026-11-21 本人「サムネイルは必ず動画のエディター、動画とセットで基本的に作る」
「今あるサムネを直しているだけなのに、なんでサムネが増えていくんだ」）。"""
import io
import json
import shutil
import uuid

import pytest
from PIL import Image

from app.api import production_asset_routes as par
from app.services import script_listen as S
from app.services import script_listen_thumbs as T
from app.services import thumbnail_doc as td


@pytest.fixture()
def room(tmp_path, monkeypatch):
    rid = f"pytest-thumbvid-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(T, 'DIR', tmp_path)
    par._room_dir(rid)
    yield rid
    shutil.rmtree(par.ASSET_ROOT / rid, ignore_errors=True)


def _video(room_id, title='動画', **extra):
    c = {'id': str(uuid.uuid4()), 'room_id': room_id, 'title': title, 'format': '16:9', 'status': 'draft',
         'asset_ids': [], 'outputs': [], 'timeline': {'sequence': {'tracks': []}},
         'created_at': '2026-11-21T00:00:00', 'updated_at': '2026-11-21T00:00:00', **extra}
    rows = par._read_contents(room_id)
    rows.append(c)
    par._write_contents(room_id, rows)
    return c


DOC = {'width': 1920, 'height': 1080, 'parts': []}


def test_create_needs_a_real_video(room):
    with pytest.raises(ValueError):
        td.create(room, 'サムネ', DOC, video_id='nothing')
    v = _video(room)
    c = td.create(room, 'サムネ', DOC, video_id=v['id'])
    assert c['video_id'] == v['id']
    assert [t['id'] for t in td.thumbnails_of(room, v['id'])] == [c['id']]


def test_attach_archive_and_order(room):
    v = _video(room)
    a = td.create(room, 'B', DOC)
    b = td.create(room, 'A', DOC)
    td.attach(room, a['id'], v['id'], order=1)
    td.attach(room, b['id'], v['id'], order=0)
    assert [t['title'] for t in td.thumbnails_of(room, v['id'])] == ['A', 'B']
    td.archive(room, a['id'])
    assert [t['title'] for t in td.thumbnails_of(room, v['id'])] == ['A']
    # 隠しただけで消していない
    assert any(c['id'] == a['id'] and c['archived'] for c in par._read_contents(room))
    with pytest.raises(ValueError):
        td.attach(room, a['id'], b['id'])     # サムネをサムネにはつながない


def test_video_for_doc_finds_or_makes_one(room):
    v = _video(room, script_doc='doc1')
    assert td.video_for_doc(room, 'doc1') == v['id']
    made = td.video_for_doc(room, 'doc2', 'ローンチ2本目')
    again = td.video_for_doc(room, 'doc2', 'ローンチ2本目')
    assert made == again and made != v['id']
    vids = [c for c in par._read_contents(room) if not td.is_thumbnail(c)]
    assert len(vids) == 2


def test_opening_an_untied_doc_picture_makes_one_thumb_on_the_doc_video(room, monkeypatch):
    v = _video(room, script_doc='doc1')
    T._save('doc1', {'room': room, 'items': []})
    buf = io.BytesIO()
    Image.new('RGB', (64, 36), 'red').save(buf, 'PNG')

    class R:
        content = buf.getvalue()
        def raise_for_status(self): pass
    monkeypatch.setattr(T.httpx, 'get', lambda *a, **k: R())
    monkeypatch.setattr(S, 'fetch', lambda d: {'title': '台本'})
    monkeypatch.setattr(T, 'top_images', lambda doc: [{'object': 'i.0', 'src': 'x', 'para': 1}])
    first = T.open_work('doc1', 'i.0', 0)
    # 何度開いても、直しても、同じ1枚を開く（新しい作品は増えない）
    for _ in range(3):
        assert T.open_work('doc1', 'i.0', 0)['content_id'] == first['content_id']
    thumbs = [c for c in par._read_contents(room) if td.is_thumbnail(c)]
    assert len(thumbs) == 1 and thumbs[0]['video_id'] == v['id']
    assert [t['id'] for t in td.thumbnails_of(room, v['id'])] == [first['content_id']]


def test_route_create_returns_the_existing_thumb(room):
    v = _video(room)
    first = par.create_video_thumbnail(v['id'], room_id=room, current_user=None)
    second = par.create_video_thumbnail(v['id'], room_id=room, current_user=None)
    assert first['id'] == second['id'] and first['video_id'] == v['id']
    assert len([c for c in par._read_contents(room) if td.is_thumbnail(c)]) == 1


def test_content_model_keeps_the_pair_fields():
    m = par.ProductionContent(id='t', room_id='r', title='t', created_at='', updated_at='', video_id='v', archived=True)
    assert m.model_dump()['video_id'] == 'v' and m.model_dump()['archived'] is True
