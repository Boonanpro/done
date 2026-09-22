from pathlib import Path
import json
from app.services import editor_activity as activity


def test_transient_windows_lock_does_not_fail_the_tool(tmp_path,monkeypatch):
    real_replace=Path.replace
    attempts=[]
    def locked(path,target):
        attempts.append(path)
        if len(attempts)<3:raise PermissionError('destination held by reader')
        return real_replace(path,target)
    monkeypatch.setattr(Path,'replace',locked)
    monkeypatch.setattr(activity.time,'sleep',lambda _:None)
    path=tmp_path/'activity'/'item.json'
    assert activity.write(path,{'state':'done'}) is True
    assert json.loads(path.read_text())['state']=='done'
    assert len(attempts)==3
    assert not list(path.parent.glob('*.tmp'))


def test_persistent_telemetry_failure_does_not_terminate_production(tmp_path,monkeypatch,caplog):
    def locked(*_):raise PermissionError('locked')
    monkeypatch.setattr(Path,'replace',locked)
    monkeypatch.setattr(activity.time,'sleep',lambda _:None)
    row={'state':'running'}
    activity.finish((tmp_path/'item.json',row))
    assert row['state']=='done'
    assert 'production continues' in caplog.text
    assert not list(tmp_path.glob('*.tmp'))
