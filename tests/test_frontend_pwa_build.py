import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    'frontend_prod', Path(__file__).parents[1] / 'scripts/frontend_prod.py')
prod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prod)


def test_rejects_skipped_or_stale_worker(tmp_path):
    with pytest.raises(RuntimeError, match='not generated'):
        prod._validate_pwa(tmp_path)
    (tmp_path / 'pwa').mkdir()
    (tmp_path / 'pwa/sw.js').write_text('{url:"/_next/static/chunks/old.js"}')
    with pytest.raises(RuntimeError, match='missing asset'):
        prod._validate_pwa(tmp_path)


def test_publishes_complete_worker_without_removing_previous_dependencies(tmp_path, monkeypatch):
    monkeypatch.setattr(prod, 'FRONTEND', tmp_path)
    public = tmp_path / 'public'
    public.mkdir()
    (public / 'worker-old.js').write_text('old')
    build = tmp_path / '.next-prod-test'
    (build / 'pwa').mkdir(parents=True)
    (build / 'static/chunks').mkdir(parents=True)
    (build / 'static/chunks/new.js').write_text('chunk')
    worker = '{url:"/_next/static/chunks/new.js"}'
    (build / 'pwa/sw.js').write_text(worker)
    (build / 'pwa/worker-new.js').write_text('push')
    prod._publish_pwa(build)
    assert (public / 'sw.js').read_text() == worker
    assert (public / 'worker-new.js').read_text() == 'push'
    assert (public / 'worker-old.js').read_text() == 'old'
