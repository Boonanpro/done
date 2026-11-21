"""台本の会話のダンが、開いているサムネと選んだ部品を「これ」として受け取る（2026-11-21 本人「このサムネとかって言っても通じるのか？」）。"""
from app.services import script_rooms as R


def _lines(monkeypatch, tmp_path, state):
    monkeypatch.setattr(R, 'STATE', tmp_path)
    monkeypatch.setattr(R, 'room_info', lambda room_id: {'doc_id': 'DOC', 'origin_room_id': 'ORIGIN', 'title': 't', 'parent_title': 'p'})
    R.put_state('DOC', state)
    return '\n'.join(R.context_lines('ROOM'))


def test_open_thumbnail_and_picked_part_reach_dan(monkeypatch, tmp_path):
    text = _lines(monkeypatch, tmp_path, {
        'thumb': '1枚目', 'thumb_room': 'WROOM', 'thumb_content': 'CID-1',
        'thumb_part': '部品 t2（文字「今までありがとう」）', 'sentence': '台本の文', 'para': 3,
    })
    assert 'content_id=CID-1' in text and 'WROOM' in text
    assert '部品 t2（文字「今までありがとう」）' in text
    assert '「このサムネ」' in text and '「この文字」' in text
    # サムネを開いている間は、台本のカーソルの文を「ここ」にしない
    assert 'カーソルの文' not in text


def test_script_place_when_no_thumbnail(monkeypatch, tmp_path):
    text = _lines(monkeypatch, tmp_path, {'sentence': '台本の文', 'para': 3})
    assert 'カーソルの文「台本の文」' in text
    assert 'content_id=' not in text.split('台本の上のサムネ')[0]


def test_put_state_keeps_thumbnail_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(R, 'STATE', tmp_path)
    R.put_state('DOC', {'thumb': '2枚目', 'thumb_content': 'C', 'thumb_room': 'W', 'thumb_part': 'P', 'junk': 'x'})
    st = R.get_state('DOC')
    assert st['thumb_content'] == 'C' and st['thumb_room'] == 'W' and st['thumb_part'] == 'P' and 'junk' not in st
