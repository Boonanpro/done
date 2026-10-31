"""Dan restarts its own core (2026-10-13). Its turn runs inside the core, so the restart is done by a process outside
it, which wakes the asking room with the outcome. Before, Dan could only ask the owner to restart."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('restart_dan_core', Path(__file__).resolve().parents[1] / 'scripts' / 'restart_dan_core.py')
restart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restart)


@pytest.fixture(autouse=True)
def no_release_switching(monkeypatch, tmp_path):
    """The machine running the tests may have release switching on; these tests are about the plain restart."""
    monkeypatch.setattr(restart, 'GENERATIONS', tmp_path / 'not-enabled')


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Everything the outside process touches, recorded in order."""
    from app.services import restart_signal
    did, woke = [], []
    monkeypatch.setattr(restart_signal, 'ROOT', tmp_path / 'leases')   # never hold the real Dan's followups
    monkeypatch.setattr(restart_signal, 'wait', lambda sock, seconds: did.append('wait'))
    state = {'busy': [], 'loads': None, 'stops': True, 'starts': True, 'core_started_at': 0,
             'follows': (True, 'already on GitHub main (536ee4e7)')}
    monkeypatch.setattr(restart, 'busy', lambda: state['busy'].pop(0) if state['busy'] else None)
    monkeypatch.setattr(restart, 'earlier_restart', lambda: None)
    monkeypatch.setattr(restart, 'loads', lambda: did.append('load check') or state['loads'])
    monkeypatch.setattr(restart, 'follow_github', lambda: did.append('follow GitHub') or state['follows'])
    monkeypatch.setattr(restart, 'core_started_at', lambda: state['core_started_at'])
    monkeypatch.setattr(restart, 'stop', lambda: did.append('stop') or state['stops'])
    monkeypatch.setattr(restart, 'start', lambda: did.append('start') or state['starts'])
    monkeypatch.setattr(restart, 'verify', lambda: did.append('verify') or 'PASSED')
    monkeypatch.setattr(restart, 'wake', lambda room, note: woke.append((room, note)))
    monkeypatch.setattr(restart.time, 'sleep', lambda s: did.append('wait'))
    return state, did, woke


def test_it_waits_for_everyone_then_restarts_checks_and_wakes_the_room_that_asked(world):
    state, did, woke = world
    state['busy'] = ['Dan is working in: ダン開発室', 'Dan is working in: ダン開発室']   # the asking turn itself, still ending
    restart.restart_when_idle('room-1', '追い連絡の並びを確かめる', asked=100)
    assert did == ['wait', 'wait', 'follow GitHub', 'load check', 'stop', 'start', 'verify']
    (room, note), = woke
    assert room == 'room-1' and '再起動した' in note and 'PASSED' in note and '追い連絡の並びを確かめる' in note


def test_code_that_does_not_load_is_never_stopped_for(world):
    state, did, woke = world
    state['loads'] = 'ImportError: cannot import name x'
    restart.restart_when_idle('room-1', '', asked=100)
    assert 'stop' not in did and '再起動していない' in woke[0][1] and 'ImportError' in woke[0][1]


def test_work_that_never_ends_is_not_cut_off(world, monkeypatch):
    state, did, woke = world
    state['busy'] = ['a phone call is open'] * 3
    monkeypatch.setattr(restart, 'WAIT', 0)
    restart.restart_when_idle('room-1', '', asked=0)
    assert 'stop' not in did and '空かなかった' in woke[0][1] and 'a phone call is open' in woke[0][1]


def test_a_long_wait_lets_automatic_work_run_and_holds_it_again_for_the_switch(world, monkeypatch):
    """2026-10-30 本人「空いた時に瞬時に・機を逃さない」: it no longer gives up after 5 min. Past the drain time new
    followups run again, and the moment nothing runs the hold comes back before anything is stopped."""
    from app.services import restart_signal
    state, did, woke = world
    state['busy'] = ['Dan is working in: X顧問'] * 3
    monkeypatch.setattr(restart, 'DRAIN', 0)
    monkeypatch.setattr(restart_signal, 'wait', lambda sock, seconds: did.append(('wait', restart_signal.draining(), seconds)))
    monkeypatch.setattr(restart, 'stop', lambda: did.append(('stop', restart_signal.draining())) or True)
    restart.restart_when_idle('room-1', '', asked=100)
    waits = [d for d in did if d[0] == 'wait']
    assert len(waits) == 3 and not any(held for _, held, _ in waits) and all(s <= restart.POLL for *_, s in waits)
    assert ('stop', True) in did and '再起動した' in woke[0][1]


def test_a_core_someone_else_restarted_meanwhile_is_not_stopped_again(world):
    state, did, woke = world
    state['core_started_at'] = 200
    restart.restart_when_idle('room-1', '確かめる', asked=100)
    assert did == ['verify'] and 'もう一度は止めていない' in woke[0][1]


def test_a_core_that_does_not_come_back_is_said_so(world):
    state, did, woke = world
    state['starts'] = False
    restart.restart_when_idle('room-1', '', asked=100)
    assert did[-2:] == ['stop', 'start'] and '起き上がらなかった' in woke[0][1]


def test_a_restart_handed_over_later_waits_for_the_earlier_one(world, monkeypatch):
    """Both saw "nothing is running"; the later one must not stop the core the earlier one just started."""
    state, did, woke = world
    earlier = ['an earlier restart is under way (pid 1)']
    monkeypatch.setattr(restart, 'earlier_restart', lambda: earlier.pop(0) if earlier else None)
    monkeypatch.setattr(restart, 'core_started_at', lambda: 0 if earlier else 200)   # new once the earlier one is done
    restart.restart_when_idle('room-2', '', asked=100)
    assert did == ['wait', 'verify'] and 'もう一度は止めていない' in woke[0][1]


def test_the_folder_follows_github_before_its_code_is_checked_and_loaded(world):
    """A fix pushed from another place is in the folder by the time the core starts (2026-10-14)."""
    state, did, woke = world
    state['follows'] = (True, 'now on GitHub main (1269a7c9) — 1 commits, 3 files GitHub changed: 2 already held here, 1 brought in from GitHub: app/x.py')
    restart.restart_when_idle('room-1', '', asked=100)
    assert did == ['follow GitHub', 'load check', 'stop', 'start', 'verify']
    assert 'フォルダと GitHub' in woke[0][1] and 'app/x.py' in woke[0][1]


def test_a_folder_that_cannot_follow_is_restarted_as_it_is_and_said_so(world):
    """One file holding both uncommitted work and a change it lacks must not keep Dan from restarting."""
    state, did, woke = world
    state['follows'] = (False, "NOT brought up to GitHub main (2 commits behind); nothing was changed.\n  app/y.py: lacks GitHub's change and has uncommitted work in the same file")
    restart.restart_when_idle('room-1', '', asked=100)
    assert did == ['follow GitHub', 'load check', 'stop', 'start', 'verify']
    assert '再起動した' in woke[0][1] and '追いつかせられなかった' in woke[0][1] and 'app/y.py' in woke[0][1]


def test_from_outside_dan_it_follows_checks_then_stops_and_never_stops_for_code_that_does_not_load(world, monkeypatch, capsys):
    state, did, woke = world
    monkeypatch.setattr(restart.sys, 'argv', ['restart_dan_core.py'])
    restart.main()
    assert did == ['follow GitHub', 'load check', 'stop'] and 'folder and GitHub' in capsys.readouterr().out
    del did[:]
    state['loads'] = 'ImportError: cannot import name x'
    with pytest.raises(SystemExit):
        restart.main()
    assert did == ['follow GitHub', 'load check'] and 'does not load' in capsys.readouterr().out


def test_the_asking_room_is_known_without_being_passed(monkeypatch):
    monkeypatch.delenv('DAN_ROOM_ID', raising=False)
    monkeypatch.setenv('DAN_LOCK_OWNER', 'room:38461f5a')   # all a Claude room's long-lived session has
    assert restart.asking_room() == '38461f5a'
    monkeypatch.setenv('DAN_LOCK_OWNER', 'job:abc')
    assert restart.asking_room() == ''
    monkeypatch.setenv('DAN_ROOM_ID', 'r-codex')
    assert restart.asking_room() == 'r-codex'


def test_asking_for_help_does_not_restart(monkeypatch, capsys):
    monkeypatch.setattr(restart, 'busy', lambda: None)
    monkeypatch.setattr(restart, 'stop', lambda: pytest.fail('stopped the core'))
    monkeypatch.setattr(restart.sys, 'argv', ['restart_dan_core.py', '--help'])
    with pytest.raises(SystemExit):
        restart.main()
    assert '--when-idle' in capsys.readouterr().out
    monkeypatch.setattr(restart, 'hand_over', lambda room, then: (room, then))
    monkeypatch.setattr(restart.sys, 'argv', ['restart_dan_core.py', '--when-idle', '--room', 'r', '--then', '-で始まる確認'])
    assert restart.main() == ('r', '-で始まる確認')


def test_a_failure_outside_the_core_is_told_to_the_room_not_dropped(world, monkeypatch):
    """2026-10-24: on the Mac the outside process died at core_started_at() and nobody heard of it."""
    state, did, woke = world
    def boom():
        raise restart.psutil.AccessDenied(26067)
    monkeypatch.setattr(restart, 'core_started_at', boom)
    monkeypatch.setattr(restart, 'ROOT', Path(__file__).resolve().parents[1] / '.tmp' / 'restart-test')
    (restart.ROOT / 'logs').mkdir(parents=True, exist_ok=True)
    restart.restart_when_idle('room-1', '', asked=100)
    assert 'stop' not in did and '失敗した' in woke[0][1] and 'AccessDenied' in woke[0][1]


def test_on_the_mac_listeners_skip_processes_that_refuse(monkeypatch):
    """The system-wide call raises AccessDenied on macOS; each process is asked on its own instead."""
    from collections import namedtuple
    Addr = namedtuple('Addr', 'ip port')
    Row = namedtuple('Row', 'status laddr')

    class Proc:
        def __init__(self, pid, rows):
            self.pid, self.rows = pid, rows

        def net_connections(self, kind):
            if self.rows is None:
                raise restart.psutil.AccessDenied(self.pid)
            return self.rows
    procs = [Proc(1, None), Proc(8120, [Row(restart.psutil.CONN_LISTEN, Addr('127.0.0.1', 9000))]),
             Proc(8126, [Row(restart.psutil.CONN_LISTEN, Addr('127.0.0.1', 8000)), Row('ESTABLISHED', Addr('127.0.0.1', 51000))]),
             Proc(5000, [Row(restart.psutil.CONN_LISTEN, Addr('127.0.0.1', 3000))])]
    monkeypatch.setattr(restart.sys, 'platform', 'darwin')
    monkeypatch.setattr(restart.psutil, 'process_iter', lambda *a, **k: iter(procs))
    monkeypatch.setattr(restart.psutil, 'net_connections', lambda **k: pytest.fail('system-wide call on the Mac'))
    assert restart.listeners() == {8120: {9000}, 8126: {8000}}


def test_on_the_mac_launchd_starts_the_core(monkeypatch):
    ran = []
    monkeypatch.setattr(restart.sys, 'platform', 'darwin')
    monkeypatch.setattr(restart.subprocess, 'run', lambda cmd, **k: ran.append(cmd))
    monkeypatch.setattr(restart, 'healthy', lambda: True)
    assert restart.start()
    assert ran[0][:2] == ['launchctl', 'kickstart'] and ran[0][2].endswith('/com.dan.core') and '-k' not in ran[0]


def test_with_release_switching_on_the_shared_core_is_still_restarted_when_idle(monkeypatch, tmp_path):
    """2026-10-30: chat turns run on the shared core (9000); a release switch alone left fixes to chat waiting for days."""
    import sys, types
    switched = []
    flag = tmp_path / 'enabled'
    flag.write_text('')
    monkeypatch.setattr(restart, 'GENERATIONS', flag)
    monkeypatch.setitem(sys.modules, 'core_release', types.SimpleNamespace(
        prepare=lambda root: {'id': 'r1'}, activate=lambda rid: switched.append(rid)))
    monkeypatch.setattr(restart, 'hand_over', lambda room, then: ('handed', room, then))
    monkeypatch.setattr(restart.sys, 'argv', ['restart_dan_core.py', '--when-idle', '--room', 'r', '--then', 'check'])
    assert restart.main() == ('handed', 'r', 'check') and switched == ['r1']
    switched.clear()
    monkeypatch.setattr(restart.sys, 'argv', ['restart_dan_core.py'])
    monkeypatch.setattr(restart, 'stop', lambda: pytest.fail('stopped the shared core'))
    assert restart.main() is None and switched == ['r1']


def test_health_only_mode_survives_handoff_and_verification(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    monkeypatch.setattr(restart.sys, 'argv', ['restart_dan_core.py', '--when-idle', '--verify-health-only'])
    monkeypatch.setattr(restart, 'loads', lambda: None)
    spawn = Mock(return_value=SimpleNamespace(pid=123))
    monkeypatch.setattr(restart.subprocess, 'Popen', spawn)
    restart.hand_over('room', 'check without jobs')
    assert '--verify-health-only' in spawn.call_args.args[0]
    run = Mock(return_value=SimpleNamespace(stdout='PASSED (health only)'))
    monkeypatch.setattr(restart.subprocess, 'run', run)
    assert restart.verify() == 'PASSED (health only)'
    assert '--health-only' in run.call_args.args[0]
