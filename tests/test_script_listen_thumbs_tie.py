"""台本のサムネを開いた時、つないだ部品の作品が一瞬読めなくても1枚絵の新しい作品へ付け替えない（2026-11-21）。"""
import json

import pytest

from app.services import script_listen as S
from app.services import script_listen_thumbs as T


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(T, 'DIR', tmp_path)
    monkeypatch.setattr(T.time, 'sleep', lambda s: None)
    (tmp_path / 'doc1.json').write_text(json.dumps({'room': 'r', 'items': [
        {'order': 0, 'object': 'i.0', 'content_id': 'parts-work', 'synced_rev': 92}]}), encoding='utf-8')
    made = []
    monkeypatch.setattr(S, 'fetch', lambda d: made.append('fetch') or (_ for _ in ()).throw(AssertionError('作り直そうとした')))
    return tmp_path, made


def test_tied_work_unreadable_is_not_replaced(store, monkeypatch):
    path, made = store
    monkeypatch.setattr(T, '_rev', lambda room, cid: -1)
    with pytest.raises(S.ListenError):
        T.open_work('doc1', 'i.0', 0)
    assert made == []
    assert json.loads((path / 'doc1.json').read_text())['items'][0]['content_id'] == 'parts-work'


def test_tied_work_readable_after_a_moment(store, monkeypatch):
    path, made = store
    seq = iter([-1, -1, 92])
    monkeypatch.setattr(T, '_rev', lambda room, cid: next(seq, 92))
    assert T.open_work('doc1', 'i.0', 0)['content_id'] == 'parts-work'
    assert made == []


def test_unreadable_ties_file_is_not_read_as_empty(store, monkeypatch):
    path, made = store
    (path / 'doc1.json').write_text('{"room": "r", "ite', encoding='utf-8')
    monkeypatch.setattr(T, '_rev', lambda room, cid: 92)
    with pytest.raises(S.ListenError):
        T.open_work('doc1', 'i.0', 0)
    assert made == []


def test_save_leaves_no_shared_tmp(store):
    path, _ = store
    T._save('doc1', {'room': 'r', 'items': []})
    assert not list(path.glob('*.tmp')) and not list(path.glob('.*.tmp'))
