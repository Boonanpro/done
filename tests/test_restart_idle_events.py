import json
import subprocess
import sys
from unittest.mock import Mock

import pytest
from app.services import restart_signal as signal
from scripts import restart_dan_core as restart


@pytest.fixture(autouse=True)
def isolated_leases(tmp_path, monkeypatch):
    monkeypatch.setattr(signal, 'ROOT', tmp_path / 'leases')


def test_notification_and_cleanup():
    assert not signal.draining()
    with signal.waiting(30) as sock:
        assert signal.draining()
        signal.notify()
        sock.settimeout(.5)
        assert sock.recv(128) == b'changed'
    assert not signal.draining()
    assert not list(signal.ROOT.glob('*.json'))


def test_invalid_expired_and_reused_pid_are_not_holds():
    with signal.waiting(30):
        path = next(signal.ROOT.glob('*.json'))
        row = json.loads(path.read_text())
        for changes in ({'expires': 0}, {'started': -1}, {'pid': None}, {'port': 90000}):
            path.write_text(json.dumps({**row, **changes}))
            assert not signal.draining()
            signal.notify()
        path.write_text('null')
        assert not signal.draining()


def test_cleanup_after_exception():
    with pytest.raises(RuntimeError), signal.waiting(30):
        raise RuntimeError('failure')
    assert not signal.draining()


def test_followups_are_left_pending(monkeypatch):
    from app.services import followups
    db = Mock(side_effect=RuntimeError('DB was reached'))
    monkeypatch.setattr(followups, '_sb', db)
    with signal.waiting(30):
        assert followups.claim_due_followups() == []
    db.assert_not_called()
    with pytest.raises(RuntimeError, match='DB was reached'):
        followups.claim_due_followups()


@pytest.fixture
def machine(monkeypatch):
    calls = []
    monkeypatch.setattr(restart, 'earlier_restart', lambda: None)
    monkeypatch.setattr(restart, 'core_started_at', lambda: 1)
    monkeypatch.setattr(restart, 'follow_github', lambda: (True, 'current'))
    monkeypatch.setattr(restart, 'loads', lambda: None)
    def stop():
        assert signal.draining()
        calls.append('stop')
        return True
    def start():
        assert signal.draining()
        calls.append('start')
        return True
    def verify():
        assert not signal.draining()
        calls.append('verify')
        return 'PASSED'
    monkeypatch.setattr(restart, 'stop', stop)
    monkeypatch.setattr(restart, 'start', start)
    monkeypatch.setattr(restart, 'verify', verify)
    monkeypatch.setattr(restart, 'wake', lambda room, note: calls.append(note))
    return calls


def test_finish_wakes_and_hold_covers_switch(monkeypatch, machine):
    states = iter(['active', None, None])
    monkeypatch.setattr(restart, 'busy', lambda: next(states))
    def wait(sock, seconds):
        signal.notify()
        sock.settimeout(.5)
        assert sock.recv(128) == b'changed'
    monkeypatch.setattr(signal, 'wait', wait)
    restart._restart_when_idle('room', 'check', 2)
    assert machine[:3] == ['stop', 'start', 'verify']
    assert 'PASSED' in machine[-1]


def test_timeout_never_kills_or_verifies(monkeypatch, machine):
    monkeypatch.setattr(restart, 'WAIT', 0)
    monkeypatch.setattr(restart, 'busy', lambda: 'active call')
    restart._restart_when_idle('room', '', 2)
    assert len(machine) == 1
    assert 'active call' in machine[0] and '自動再予約はしない' in machine[0]
    assert not signal.draining()


def test_work_started_during_preflight_is_protected(monkeypatch, machine):
    states = iter([None, 'new turn'])
    monkeypatch.setattr(restart, 'busy', lambda: next(states))
    monkeypatch.setattr(restart, 'WAIT', 0)
    restart._restart_when_idle('room', '', 2)
    assert len(machine) == 1 and 'new turn' in machine[0]


def test_pending_core_job_is_not_started(monkeypatch):
    from app.services import command_job_runner as jobs
    monkeypatch.setattr(jobs.state, 'read', lambda key: {'queue_owner': 'core', 'state': 'queued'})
    monkeypatch.setattr(jobs.asyncio, 'create_task', Mock(side_effect=AssertionError('started')))
    with signal.waiting(30):
        assert jobs.dispatch({'id': 'test'}) is None
    jobs.asyncio.create_task.assert_not_called()


def test_notification_from_another_process():
    with signal.waiting(30) as sock:
        code = ('from pathlib import Path; from app.services import restart_signal as s; '
                f's.ROOT=Path({str(signal.ROOT)!r}); s.notify()')
        subprocess.run([sys.executable, '-c', code], check=True, timeout=5)
        sock.settimeout(.5)
        assert sock.recv(128) == b'changed'


def test_stop_refuses_work_that_started_after_idle_check(monkeypatch):
    monkeypatch.setattr(restart, 'announce', lambda: None)
    monkeypatch.setattr(restart, 'listeners', lambda: {})
    monkeypatch.setattr(restart, 'busy', lambda: 'new call')
    monkeypatch.setattr(restart.sys, 'argv', ['restart_dan_core.py'])
    monkeypatch.setattr(restart.psutil, 'wait_procs', Mock(side_effect=AssertionError('killed')))
    with pytest.raises(RuntimeError, match='new call'):
        restart.stop()
    restart.psutil.wait_procs.assert_not_called()
