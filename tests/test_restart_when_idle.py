"""Dan restarts its own core (2026-10-13). Its turn runs inside the core, so the restart is done by a process outside
it, which wakes the asking room with the outcome. Before, Dan could only ask the owner to restart."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('restart_dan_core', Path(__file__).resolve().parents[1] / 'scripts' / 'restart_dan_core.py')
restart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restart)


@pytest.fixture
def world(monkeypatch):
    """Everything the outside process touches, recorded in order."""
    did, woke = [], []
    state = {'busy': [], 'loads': None, 'stops': True, 'starts': True, 'core_started_at': 0}
    monkeypatch.setattr(restart, 'busy', lambda: state['busy'].pop(0) if state['busy'] else None)
    monkeypatch.setattr(restart, 'earlier_restart', lambda: None)
    monkeypatch.setattr(restart, 'loads', lambda: state['loads'])
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
    assert did == ['wait', 'wait', 'stop', 'start', 'verify']
    (room, note), = woke
    assert room == 'room-1' and '再起動した' in note and 'PASSED' in note and '追い連絡の並びを確かめる' in note


def test_code_that_does_not_load_is_never_stopped_for(world):
    state, did, woke = world
    state['loads'] = 'ImportError: cannot import name x'
    restart.restart_when_idle('room-1', '', asked=100)
    assert did == [] and '再起動していない' in woke[0][1] and 'ImportError' in woke[0][1]


def test_work_that_never_ends_is_not_cut_off(world, monkeypatch):
    state, did, woke = world
    state['busy'] = ['a phone call is open'] * 3
    clock = iter([0, 10, restart.WAIT + 11, restart.WAIT + 12])
    monkeypatch.setattr(restart.time, 'time', lambda: next(clock))
    restart.restart_when_idle('room-1', '', asked=0)
    assert 'stop' not in did and '再起動していない' in woke[0][1] and 'a phone call is open' in woke[0][1]


def test_a_core_someone_else_restarted_meanwhile_is_not_stopped_again(world):
    state, did, woke = world
    state['core_started_at'] = 200
    restart.restart_when_idle('room-1', '確かめる', asked=100)
    assert did == ['verify'] and 'もう一度は止めていない' in woke[0][1]


def test_a_core_that_does_not_come_back_is_said_so(world):
    state, did, woke = world
    state['starts'] = False
    restart.restart_when_idle('room-1', '', asked=100)
    assert did == ['stop', 'start'] and '起き上がらなかった' in woke[0][1]


def test_a_restart_handed_over_later_waits_for_the_earlier_one(world, monkeypatch):
    """Both saw "nothing is running"; the later one must not stop the core the earlier one just started."""
    state, did, woke = world
    earlier = ['an earlier restart is under way (pid 1)']
    monkeypatch.setattr(restart, 'earlier_restart', lambda: earlier.pop(0) if earlier else None)
    monkeypatch.setattr(restart, 'core_started_at', lambda: 0 if earlier else 200)   # new once the earlier one is done
    restart.restart_when_idle('room-2', '', asked=100)
    assert did == ['wait', 'verify'] and 'もう一度は止めていない' in woke[0][1]


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
