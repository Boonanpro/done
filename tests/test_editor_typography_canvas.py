from PIL import Image

from app.services import editor_media, timeline_draft


def test_full_canvas_keeps_text_anchor_after_edit(tmp_path, monkeypatch):
    monkeypatch.setattr(timeline_draft, 'UPLOAD_ROOT', tmp_path / 'rooms')
    image = Image.new('RGBA', (100, 80))
    image.paste((255, 0, 0, 255), (30, 40, 70, 52))
    source = tmp_path / 'caption.png'
    image.save(source)
    actual = editor_media.import_media('sample', source, preserve_canvas=True)
    assert actual['ok']
    with Image.open(actual['path']) as saved:
        assert saved.size == image.size
        assert saved.getbbox() == image.getbbox()
