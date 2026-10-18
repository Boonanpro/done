"""A site's _server is swapped in place when its files change, without restarting the sandbox (2026-10-18)."""
import textwrap
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import artifact_backends as ab


def write(base, slug, body, extra=None):
    d = base/slug/'_server'
    d.mkdir(parents=True, exist_ok=True)
    (d/'__init__.py').write_text('', encoding='utf-8')
    (d/'routes.py').write_text(textwrap.dedent(body), encoding='utf-8')
    for name, text in (extra or {}).items():
        (d/name).write_text(text, encoding='utf-8')


ROUTE = '''
from fastapi import APIRouter
router = APIRouter(prefix='/{slug}')
@router.get('/v')
def v():
    return {{'v': {v}}}
'''

THREADED = '''
import threading, time
from fastapi import APIRouter
router = APIRouter(prefix='/{slug}')
STOP = threading.Event()
@router.get('/v')
def v():
    return {{'v': {v}, 'threads': sum(1 for t in threading.enumerate() if t.name == '{slug}-patrol')}}
def _run():
    while not STOP.wait(0.05):
        pass
if not any(t.name == '{slug}-patrol' for t in threading.enumerate()):
    threading.Thread(target=_run, name='{slug}-patrol', daemon=True).start()
{unload}
'''

UNLOAD = '''
def dan_unload():
    STOP.set()
    for t in threading.enumerate():
        if t.name == '{slug}-patrol':
            t.join(5)
'''


@pytest.fixture()
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(ab, 'ARTIFACTS', tmp_path)
    monkeypatch.setattr(ab, 'STATE_FILE', tmp_path/'state.json')
    monkeypatch.setattr(ab, '_mounted', {})
    monkeypatch.setattr(ab, '_state', {})
    monkeypatch.setattr(ab, '_loop', None)
    yield tmp_path
    for name in [k for k in list(__import__('sys').modules) if k.startswith('dan_artifact_t')]:
        __import__('sys').modules.pop(name, None)


def app_with(site):
    app = FastAPI()
    ab.mount(app, prefix='/api/v1')

    @app.get('/api/v1/{rest:path}')
    def fallback(rest: str):   # a catch-all after the sites: swapped routes must stay in front of it
        return {'fallback': rest}
    return app


def test_swap_in_place(site):
    write(site, 'ta', ROUTE.format(slug='ta', v=1))
    app = app_with(site)
    c = TestClient(app)
    assert c.get('/api/v1/ta/v').json() == {'v': 1}
    write(site, 'ta', ROUTE.format(slug='ta', v=2))
    st = ab.reload('ta')
    assert st['state'] == 'current' and st['loaded'] == ab.fingerprint('ta')
    assert c.get('/api/v1/ta/v').json() == {'v': 2}
    # still exactly one route for the site, and in front of the catch-all
    paths = [getattr(r, 'path', '') for r in app.router.routes]
    assert paths.count('/api/v1/ta/v') == 1
    assert paths.index('/api/v1/ta/v') < paths.index('/api/v1/{rest:path}')


def test_syntax_error_keeps_old_code(site):
    write(site, 'tb', ROUTE.format(slug='tb', v=1))
    c = TestClient(app_with(site))
    write(site, 'tb', 'def broken(:\n')
    st = ab.reload('tb')
    assert st['state'] == 'failed' and st['reason'] == 'syntax-error'
    assert st['loaded'] != st['files']
    assert c.get('/api/v1/tb/v').json() == {'v': 1}


def test_import_error_keeps_old_code(site):
    write(site, 'tc', ROUTE.format(slug='tc', v=1))
    c = TestClient(app_with(site))
    write(site, 'tc', 'import no_such_module_dan\n')
    st = ab.reload('tc')
    assert st['state'] == 'failed' and st['reason'] == 'load-error'
    assert c.get('/api/v1/tc/v').json() == {'v': 1}
    write(site, 'tc', ROUTE.format(slug='tc', v=3))
    assert ab.reload('tc')['state'] == 'current'
    assert c.get('/api/v1/tc/v').json() == {'v': 3}


def test_thread_without_unload_needs_restart(site):
    write(site, 'td', THREADED.format(slug='td', v=1, unload=''))
    c = TestClient(app_with(site))
    write(site, 'td', THREADED.format(slug='td', v=2, unload=''))
    st = ab.reload('td')
    assert st['state'] == 'needs-restart' and st['reason'] == 'background-thread'
    assert c.get('/api/v1/td/v').json()['v'] == 1
    for t in threading.enumerate():
        if t.name == 'td-patrol':
            __import__('sys').modules['dan_artifact_td.routes'].STOP.set()


def test_thread_with_unload_restarts_once(site):
    write(site, 'te', THREADED.format(slug='te', v=1, unload=UNLOAD.format(slug='te')))
    c = TestClient(app_with(site))
    assert c.get('/api/v1/te/v').json() == {'v': 1, 'threads': 1}
    write(site, 'te', THREADED.format(slug='te', v=2, unload=UNLOAD.format(slug='te')))
    assert ab.reload('te')['state'] == 'current'
    assert c.get('/api/v1/te/v').json() == {'v': 2, 'threads': 1}
    __import__('sys').modules['dan_artifact_te.routes'].dan_unload()


def test_fingerprint_ignores_cache_and_sees_data_files(site):
    write(site, 'tf', ROUTE.format(slug='tf', v=1), {'template.md': 'a'})
    a = ab.fingerprint('tf')
    (site/'tf'/'_server'/'__pycache__').mkdir()
    (site/'tf'/'_server'/'__pycache__'/'x.pyc').write_bytes(b'x')
    assert ab.fingerprint('tf') == a
    (site/'tf'/'_server'/'template.md').write_text('b', encoding='utf-8')
    assert ab.fingerprint('tf') != a


def test_watcher_reloads_and_writes_state(site, monkeypatch):
    import json
    write(site, 'tg', ROUTE.format(slug='tg', v=1))
    app = app_with(site)
    c = TestClient(app)
    monkeypatch.setattr(ab, 'SCAN_S', 0.1)
    monkeypatch.setattr(ab, '_started', False)
    monkeypatch.setenv('DAN_ARTIFACT_RELOAD', '1')
    assert ab.start_watcher()
    write(site, 'tg', ROUTE.format(slug='tg', v=5))
    deadline = time.time() + 5
    while time.time() < deadline and c.get('/api/v1/tg/v').json().get('v') != 5:
        time.sleep(0.1)
    assert c.get('/api/v1/tg/v').json() == {'v': 5}
    time.sleep(0.3)
    state = json.loads((site/'state.json').read_text(encoding='utf-8'))
    assert state['sites']['tg']['state'] == 'current'
    assert state['sites']['tg']['loaded'] == ab.fingerprint('tg')
