"""家の中の直通が、入口（8100）を通さずその時のサンドボックスへ直接つなぎ、だめなら入口へ回す。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import lan_media_server as L  # noqa: E402


def test_direct_first_then_gateway(monkeypatch):
    monkeypatch.delenv('DAN_LAN_MEDIA_UPSTREAM', raising=False)
    monkeypatch.setattr(L, 'gateway_base', lambda: 'http://127.0.0.1:8100')
    import app.core.gateway as gw
    seen = {}
    def fake(scope, path, payload=None):
        seen['port'] = scope['server'][1]; seen['path'] = path
        return 8224
    monkeypatch.setattr(gw, 'destination', fake)
    assert L.upstreams('/api/v1/production-assets/media') == ['http://127.0.0.1:8224', 'http://127.0.0.1:8100']
    assert seen == {'port': 8100, 'path': '/api/v1/production-assets/media'}  # 入口のサンドボックス側と同じ決まり


def test_unknown_route_goes_through_gateway(monkeypatch):
    monkeypatch.delenv('DAN_LAN_MEDIA_UPSTREAM', raising=False)
    monkeypatch.setattr(L, 'gateway_base', lambda: 'http://127.0.0.1:8100')
    import app.core.gateway as gw
    def broken(*a, **k):
        raise OSError('no routing file')
    monkeypatch.setattr(gw, 'destination', broken)
    assert L.upstreams('/api/v1/video-review/media') == ['http://127.0.0.1:8100']


def test_override_and_no_generations(monkeypatch):
    monkeypatch.setenv('DAN_LAN_MEDIA_UPSTREAM', 'http://127.0.0.1:9999')
    assert L.upstreams('/api/v1/video-review/media') == ['http://127.0.0.1:9999']
    monkeypatch.delenv('DAN_LAN_MEDIA_UPSTREAM')
    monkeypatch.setattr(L, 'gateway_base', lambda: 'http://127.0.0.1:8000')
    assert L.upstreams('/api/v1/video-review/media') == ['http://127.0.0.1:8000']
