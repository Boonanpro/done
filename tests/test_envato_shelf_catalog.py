import json

from app.services import envato_shelf


def test_editor_removals_survive_catalog_refresh(tmp_path, monkeypatch):
    monkeypatch.setattr(envato_shelf, 'SHELF', tmp_path)
    catalog = tmp_path / 'catalog.json'
    catalog.write_text(json.dumps([{'id': 'a-1'}, {'id': 'b-2'}]))
    assert [row['id'] for row in envato_shelf.catalog()] == ['a-1', 'b-2']

    removed = tmp_path / 'removed'
    removed.mkdir()
    (removed / 'a-1').touch()
    catalog.write_text(json.dumps([{'id': 'c-3'}, {'id': 'a-1'}, {'id': 'b-2'}]))
    assert [row['id'] for row in envato_shelf.catalog()] == ['c-3', 'b-2']
