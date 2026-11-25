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


def test_text_style_is_validated_and_converted():
    import pytest
    from app.services import envato_shelf
    assert envato_shelf.resolve_style() == (1.0, None, None)
    scale, color, outline = envato_shelf.resolve_style(3, '#e0241b', 'ffffff')
    assert scale == 3.0 and outline == [1.0, 1.0, 1.0]
    assert color == [round(0xe0 / 255, 4), round(0x24 / 255, 4), round(0x1b / 255, 4)]
    with pytest.raises(ValueError):
        envato_shelf.resolve_style(9)
    with pytest.raises(ValueError):
        envato_shelf.resolve_style(1, 'red')
