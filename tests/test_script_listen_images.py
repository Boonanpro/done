"""台本の答えはサムネの絵を中に入れず住所だけを渡し、絵は初めて頼まれた時に取ってきて残す（2026-11-21 本人「台本読み上げページも遅い」）。"""
import io

from PIL import Image

from app.services import script_listen as S


class _Resp:
    def __init__(self, content):
        self.content = content
        self.headers = {'content-type': 'image/png'}

    def raise_for_status(self):
        pass


def _png():
    out = io.BytesIO()
    Image.new('RGB', (1600, 900), (200, 30, 30)).save(out, 'PNG')
    return out.getvalue()


def test_doc_answer_carries_addresses_and_picture_is_fetched_once(tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'IMAGES', tmp_path)
    monkeypatch.setattr(S, '_image_cache', {})
    monkeypatch.setattr(S, '_image_links', {})
    monkeypatch.setattr(S.threading, 'Thread', lambda **k: type('T', (), {'start': lambda self: None})())
    calls = []
    monkeypatch.setattr(S.httpx, 'get', lambda url, **k: calls.append(url) or _Resp(_png()))
    units = [{'kind': 'image', 'src': 'https://lh7-rt.googleusercontent.com/docsz/AAA?key=1'}, {'kind': 'say', 'text': 'x'}]
    S._inline_images(units)
    src = units[0]['src']
    assert src.startswith('/api/v1/script-listen/img/') and 'googleusercontent' not in src
    name = src.rsplit('/', 1)[1]
    assert calls == []                       # the answer does not wait for Google
    p = S.image_path(name)
    assert p and p.suffix == '.jpg'
    assert Image.open(p).width == S.IMAGE_WIDTH
    assert S.image_path(name) == p and len(calls) == 1   # kept: asked again, not fetched again
    # A restart forgets the links in memory; the address still opens (links.json).
    monkeypatch.setattr(S, '_image_links', {})
    p.unlink()
    assert S.image_path(name) and len(calls) == 2
    # Same picture with a new query part: same name.
    again = [{'kind': 'image', 'src': 'https://lh7-rt.googleusercontent.com/docsz/AAA?key=2'}]
    S._inline_images(again)
    assert again[0]['src'] == src


def test_unknown_or_odd_names_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'IMAGES', tmp_path)
    monkeypatch.setattr(S, '_image_links', {})
    assert S.image_path('0' * 40) is None
    assert S.image_path('../.salt') is None
    assert S.image_path('') is None
