from app.api import production_asset_routes as par


def test_long_job_keeps_assets_registered_meanwhile(tmp_path, monkeypatch):
    monkeypatch.setattr(par, '_index_path', lambda room: tmp_path / 'assets.json')
    par._write_assets('r', [{'id': 'a', 'kind': 'video', 'metadata': {'x': 1}}])
    stale = par._read_assets('r')                      # a long job reads the list
    rows = par._read_assets('r'); rows.append({'id': 'b', 'kind': 'image'}); par._write_assets('r', rows)  # registered meanwhile
    stale[0]['metadata'] = {**stale[0]['metadata'], 'audio_analysis': {'segments': [1]}}
    par._merge_asset_meta('r', stale, {'a'}, ('audio_analysis',))
    got = {r['id']: r for r in par._read_assets('r')}
    assert set(got) == {'a', 'b'}
    assert got['a']['metadata'] == {'x': 1, 'audio_analysis': {'segments': [1]}}


def test_stopped_whisper_run_does_not_write(tmp_path, monkeypatch):
    monkeypatch.setattr(par, '_index_path', lambda room: tmp_path / 'assets.json')
    src = tmp_path / 'v.mp4'; src.write_bytes(b'x')
    par._write_assets('r', [{'id': 'a', 'kind': 'video', 'local_path': str(src), 'metadata': {}}])
    monkeypatch.setattr(par.subprocess, 'run', lambda *a, **k: None)   # the run produced nothing
    rows = par._read_assets('r'); rows.append({'id': 'b'}); par._write_assets('r', rows)
    par._ensure_audio_analysis('r', ['a'])
    assert {r['id'] for r in par._read_assets('r')} == {'a', 'b'}
