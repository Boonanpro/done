# -*- coding: utf-8 -*-
"""Unit tests for the behavioral-loop guard in app.agent.cli_runner.

These cover the pure logic that detects N consecutive identical tool calls
(the streaming-path "open the same URL forever" failure). The sink/run wiring
that consumes them lives in dan core and is verified by reading; this locks the
detection logic itself.
"""
from app.agent.cli_runner import _LoopGuard, _tool_call_signature


def test_signature_stable_for_identical_calls():
    a = _tool_call_signature("browser", {"action": "open", "url": "https://manager.line.biz"})
    b = _tool_call_signature("browser", {"url": "https://manager.line.biz", "action": "open"})
    # key order must not matter
    assert a == b


def test_signature_differs_on_different_input():
    a = _tool_call_signature("browser", {"action": "open", "url": "https://manager.line.biz"})
    b = _tool_call_signature("browser", {"action": "open", "url": "https://example.com"})
    assert a != b


def test_signature_differs_on_different_tool():
    a = _tool_call_signature("browser", {"action": "open"})
    b = _tool_call_signature("read_url", {"action": "open"})
    assert a != b


def test_signature_handles_unserializable_input():
    # Must never raise even if input is weird; default=str keeps it stable.
    sig = _tool_call_signature("x", {"obj": object()})
    assert isinstance(sig, str) and sig.startswith("x|")


def test_loop_fires_exactly_at_threshold():
    g = _LoopGuard(threshold=5)
    sig = _tool_call_signature("browser", {"action": "open", "url": "u"})
    results = [g.record(sig) for _ in range(5)]
    assert results == [False, False, False, False, True]


def test_loop_does_not_fire_below_threshold():
    g = _LoopGuard(threshold=5)
    sig = _tool_call_signature("browser", {"action": "open", "url": "u"})
    assert [g.record(sig) for _ in range(4)] == [False] * 4


def test_alternating_calls_never_loop():
    g = _LoopGuard(threshold=3)
    a = _tool_call_signature("browser", {"action": "open", "url": "a"})
    b = _tool_call_signature("browser", {"action": "open", "url": "b"})
    # a,b,a,b,... never reaches 3-in-a-row of the same signature
    seq = [a, b, a, b, a, b, a, b]
    assert not any(g.record(s) for s in seq)


def test_changed_signature_resets_run():
    g = _LoopGuard(threshold=3)
    a = _tool_call_signature("browser", {"action": "open", "url": "a"})
    b = _tool_call_signature("browser", {"action": "open", "url": "b"})
    # two a's, then a b (resets), then it takes three more b's to fire
    assert g.record(a) is False
    assert g.record(a) is False
    assert g.record(b) is False  # run reset to 1
    assert g.record(b) is False  # 2
    assert g.record(b) is True   # 3 -> fires


def test_reset_clears_run():
    g = _LoopGuard(threshold=3)
    sig = _tool_call_signature("browser", {"action": "open", "url": "u"})
    g.record(sig)
    g.record(sig)
    g.reset()
    # after reset it takes a full threshold run again
    assert [g.record(sig) for _ in range(3)] == [False, False, True]


def test_threshold_zero_disables_guard():
    g = _LoopGuard(threshold=0)
    sig = _tool_call_signature("browser", {"action": "open", "url": "u"})
    assert not any(g.record(sig) for _ in range(50))


def test_negative_threshold_disables_guard():
    g = _LoopGuard(threshold=-1)
    sig = "x|{}"
    assert not any(g.record(sig) for _ in range(50))
