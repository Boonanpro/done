import json

from app.services import gdoc_events as E
from app.services import script_share as SS


def test_copy_of_picks_newest_copy_of_that_working_doc(tmp_path, monkeypatch):
    monkeypatch.setattr(E, 'ROOT', tmp_path)
    for cid, work, when in (('a', 'W', '2026-11-01'), ('b', 'W', '2026-11-05'), ('c', 'X', '2026-11-09')):
        (tmp_path / 'client' / cid).mkdir(parents=True)
        (tmp_path / 'client' / cid / 'meta.json').write_text(json.dumps({'work': work, 'client': cid, 'delivered_at': when}))
    assert SS._copy_of('W')['client'] == 'b'
    assert SS._copy_of('X')['client'] == 'c'
    assert SS._copy_of('none') is None
