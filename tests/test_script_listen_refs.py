from app.services import script_listen_refs as R


def test_read_missing_and_save_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(R, 'DIR', tmp_path)
    doc = '1xxfzb0_99_KNNwWZHSjp9eu8LxIqDg3iw'
    assert R.read(doc) == {'refs': []}
    R.save(doc, {'refs': [
        {'who': 'イツキ', 'title': 'a', 'sections': [{'match': '▼一', 'start': 12.7, 'text': ' 文 \n'}, {'match': '▼二', 'text': ''}]},
        {'who': '空', 'sections': []},
    ]})
    got = R.read(doc)
    assert len(got['refs']) == 1
    r = got['refs'][0]
    assert r['id'] == 'ref1' and r['who'] == 'イツキ'
    assert r['sections'][0] == {'match': '▼一', 'start': 12, 'text': '文'}
    assert r['sections'][1]['start'] is None


def test_bad_doc_id(tmp_path, monkeypatch):
    monkeypatch.setattr(R, 'DIR', tmp_path)
    import pytest
    with pytest.raises(ValueError):
        R.read('../etc/passwd')
