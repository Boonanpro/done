"""artifact_seen.py reports the server code and the published copy, not only the open screens (2026-10-18)."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1]/'scripts'/'artifact_seen.py'


@pytest.fixture()
def seen(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('artifact_seen_t', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    art = tmp_path/'artifacts'
    (art/'demo'/'_server').mkdir(parents=True)
    (art/'demo'/'_server'/'routes.py').write_text('router = None\n', encoding='utf-8')
    (art/'demo'/'page.tsx').write_text('x', encoding='utf-8')
    monkeypatch.setattr(mod.artifact_backends, 'ARTIFACTS', art)
    monkeypatch.setattr(mod.artifact_backends, 'STATE_FILE', tmp_path/'backends.json')
    monkeypatch.setattr(mod.artifact_freshness, 'ARTIFACTS_ROOT', art)
    monkeypatch.setattr(mod.artifact_freshness, 'SNAPSHOT', tmp_path/'releases.json')
    mod.artifact_freshness._cache.clear()
    return mod, tmp_path


def now(delta=0):
    return (datetime.now(timezone.utc) - timedelta(seconds=delta)).isoformat(timespec='seconds')


def test_backend_unknown_before_restart(seen):
    mod, _ = seen
    ok, line = mod.backend_line('demo')
    assert not ok and '再起動' in line


def test_backend_current_and_behind(seen):
    mod, tmp = seen
    fp = mod.artifact_backends.fingerprint('demo')
    (tmp/'backends.json').write_text(json.dumps({'heartbeat': now(), 'sites': {'demo': {'loaded': fp, 'state': 'current'}}}), encoding='utf-8')
    assert mod.backend_line('demo')[0]
    (tmp/'backends.json').write_text(json.dumps({'heartbeat': now(), 'sites': {'demo': {'loaded': 'old', 'state': 'needs-restart', 'error': 'thread'}}}), encoding='utf-8')
    ok, line = mod.backend_line('demo')
    assert not ok and '再起動が要る' in line
    (tmp/'backends.json').write_text(json.dumps({'heartbeat': now(600), 'sites': {'demo': {'loaded': fp}}}), encoding='utf-8')
    assert not mod.backend_line('demo')[0]


def test_no_server_no_backend_line(seen):
    mod, tmp = seen
    (tmp/'artifacts'/'plain').mkdir()
    assert mod.backend_line('plain') is None


def test_release_current_and_updating(seen):
    mod, tmp = seen
    fp = mod.artifact_freshness.source_fingerprint('demo')[0]
    row = {'status': 'ready', 'shared_url': 'https://x.vercel.app', 'job_status': {'source_fingerprint': fp}, 'deploying': False}
    (tmp/'releases.json').write_text(json.dumps({'at': now(), 'sites': {'demo': row}}), encoding='utf-8')
    assert mod.release_line('demo')[0]
    row['job_status']['source_fingerprint'] = 'old'
    (tmp/'releases.json').write_text(json.dumps({'at': now(), 'sites': {'demo': row}}), encoding='utf-8')
    ok, line = mod.release_line('demo')
    assert not ok and 'スマホ' in line
    (tmp/'releases.json').write_text(json.dumps({'at': now(), 'sites': {}}), encoding='utf-8')
    assert mod.release_line('demo') is None
