"""Proactive session rotation (prewarm) — move the fresh-session reseed cost off
the send critical path. 2026-09-11.

The felt "送っても動かない" latency was the reseed prefill (~15-23s) firing at
send time once a room's transcript crossed the hard limit. Rotation prewarms a
replacement at turn end instead. These tests pin the orchestration logic with
mocks (no real model): trigger threshold, successful swap, busy-abort, prewarm
failure, the in-flight guard, and the disable flag.
"""
import threading
from unittest.mock import MagicMock, patch

import pytest

from app.agent import cli_runner as cr


@pytest.fixture(autouse=True)
def _run_threads_inline(monkeypatch):
    """Make _schedule_prewarm_rotation's daemon thread run synchronously so the
    test can assert on its effects without sleeping."""
    class _Inline:
        def __init__(self, target=None, daemon=None, **kw):
            self._t = target

        def start(self):
            if self._t:
                self._t()

    monkeypatch.setattr(cr.threading, "Thread", _Inline)
    cr._prewarm_inflight.clear()


@pytest.fixture(autouse=True)
def _enable_flag(monkeypatch):
    monkeypatch.setattr(cr, "_PREWARM_ROTATE", True)


def _fake_replacement(alive=True):
    s = MagicMock()
    s.is_alive.return_value = alive
    s.is_turn_active.return_value = False
    s.prewarm.return_value = alive
    s.model = None
    return s


def _patch_env(monkeypatch, replacement, reseed="<conversation_so_far>x</conversation_so_far>"):
    monkeypatch.setattr(cr, "_build_reseed_context", lambda room_id, project_id=None: reseed)
    made = {}

    def _ctor(room_id, build_cmd, env, cwd):
        made["session"] = replacement
        return replacement

    monkeypatch.setattr("app.agent.streaming_session.StreamingSession", _ctor)
    installed = {}

    def _install(room_id, session):
        installed["room_id"] = room_id
        installed["session"] = session
        return installed.get("old")

    monkeypatch.setattr("app.agent.streaming_session.install_session", _install)
    monkeypatch.setattr(cr, "_save_session", lambda room_id, sid: installed.setdefault("saved", (room_id, sid)))
    return installed


def _run(old_session=None, installed=None):
    old = old_session or MagicMock()
    if old_session is None:
        old.is_turn_active.return_value = False
    # install_session returns the previously-registered session (the old one).
    if installed is not None:
        installed["old"] = old
    cr._schedule_prewarm_rotation(
        "room-abcd1234", "proj", old, build_cmd=lambda: ["claude"],
        env={}, run_cwd=".", model="fable",
    )
    return old


def test_soft_threshold(tmp_path, monkeypatch):
    f = tmp_path / "t.jsonl"
    f.write_bytes(b"x" * 1000)
    monkeypatch.setattr(cr, "_session_transcript_path", lambda sid: f)
    monkeypatch.setattr(cr, "_TRANSCRIPT_SOFT_BYTES", 500)
    monkeypatch.setattr(cr, "_TRANSCRIPT_RESET_BYTES", 2000)
    assert cr._transcript_soft_exceeded("sid") is True
    monkeypatch.setattr(cr, "_TRANSCRIPT_SOFT_BYTES", 5000)
    assert cr._transcript_soft_exceeded("sid") is False
    assert cr._transcript_soft_exceeded(None) is False


def test_successful_prewarm_swaps_and_saves(monkeypatch):
    repl = _fake_replacement(alive=True)
    # prewarm captures a session_id via the discard sink
    def _prewarm(priming, sink, timeout=0):
        sink({"type": "system", "session_id": "new-sid-123"})
        sink({"type": "result"})
        return True
    repl.prewarm.side_effect = _prewarm
    installed = _patch_env(monkeypatch, repl)
    old = _run(installed=installed)
    assert installed["session"] is repl
    assert installed["room_id"] == "room-abcd1234"
    assert installed["saved"] == ("room-abcd1234", "new-sid-123")
    old.stop.assert_called_once()
    repl.stop.assert_not_called()


def test_busy_old_session_aborts_swap(monkeypatch):
    repl = _fake_replacement(alive=True)
    installed = _patch_env(monkeypatch, repl)
    old = MagicMock()
    old.is_turn_active.return_value = True  # a new user turn started during prewarm
    _run(old_session=old)
    assert "session" not in installed  # never installed
    repl.stop.assert_called_once()      # replacement discarded
    old.stop.assert_not_called()        # the in-use session survives


def test_prewarm_failure_leaves_old_session(monkeypatch):
    repl = _fake_replacement(alive=False)
    repl.prewarm.return_value = False
    installed = _patch_env(monkeypatch, repl)
    old = _run()
    assert "session" not in installed
    repl.stop.assert_called_once()
    old.stop.assert_not_called()


def test_empty_reseed_is_noop(monkeypatch):
    repl = _fake_replacement()
    installed = _patch_env(monkeypatch, repl, reseed="")
    _run()
    assert "session" not in installed
    repl.prewarm.assert_not_called()


def test_inflight_guard_blocks_double(monkeypatch):
    repl = _fake_replacement()
    calls = {"n": 0}

    def _prewarm(priming, sink, timeout=0):
        calls["n"] += 1
        # while we are "priming", a second schedule must be ignored
        cr._schedule_prewarm_rotation("room-abcd1234", "proj", MagicMock(), lambda: [], {}, ".", "fable")
        sink({"type": "result"})
        return True
    repl.prewarm.side_effect = _prewarm
    _patch_env(monkeypatch, repl)
    _run()
    assert calls["n"] == 1  # the nested schedule was blocked by the in-flight guard


def test_disabled_flag_is_noop(monkeypatch):
    monkeypatch.setattr(cr, "_PREWARM_ROTATE", False)
    repl = _fake_replacement()
    installed = _patch_env(monkeypatch, repl)
    _run()
    assert "session" not in installed
    repl.prewarm.assert_not_called()
