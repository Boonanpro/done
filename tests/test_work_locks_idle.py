import json
import time

from app.services import work_locks as wl


def test_device_is_free_after_idle_but_files_stay(tmp_path, monkeypatch):
    monkeypatch.setattr(wl, 'ROOT', tmp_path)
    monkeypatch.setattr(wl, 'LOCKS', tmp_path/'locks')
    (tmp_path/'j1.json').write_text(json.dumps({'state': 'running'}))
    assert wl.try_acquire('device:phone', 'job:j1', 'LINE') is None
    assert wl.try_acquire('file:/x', 'job:j1', 'LINE') is None
    assert wl.try_acquire('device:phone', 'job:j2', 'other')['owner'] == 'job:j1'    # in use: the other waits
    for key in ('device:phone', 'file:/x'):
        path = wl._path(key); rec = json.loads(path.read_text()); rec['touched'] = time.time() - wl.DEVICE_IDLE - 1
        path.write_text(json.dumps(rec))
    assert wl.try_acquire('device:phone', 'job:j2', 'other') is None                  # idle: free again
    assert wl.try_acquire('file:/x', 'job:j2', 'other')['owner'] == 'job:j1'          # a file is held to the end
