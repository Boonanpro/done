"""追い連絡で割り込まれたターンの置き場所（2026-10-13）。

追い連絡の前にした作業の記録は、追い連絡の直前（元のメッセージの下）に置く。
そのための目印（追い連絡のサーバー受信時刻）の持ち方と、1ミリ秒前を作る補助を確かめる。
"""
from unittest.mock import MagicMock

from app.agent import cli_runner as cr
from app.agent import streaming_session as ss

T1 = "2026-10-13T05:50:43.694969+00:00"
T2 = "2026-10-13T05:51:00+00:00"


def _session(turn_active: bool) -> ss.StreamingSession:
    s = ss.StreamingSession("room-x", lambda: ["x"], {}, "D:/")
    s._write = MagicMock()          # 実プロセスなし
    s.is_alive = lambda: True       # type: ignore[method-assign]
    s._turn = object() if turn_active else None
    return s


def test_anchor_is_kept_only_while_a_turn_is_active():
    idle = _session(turn_active=False)
    idle.submit_followup("a", received_at=T1)
    assert idle.take_followup_anchor() is None      # 待ち中に届いた分は次のターンそのもの。目印は要らない

    busy = _session(turn_active=True)
    busy.submit_followup("a", received_at=T1)
    busy.submit_followup("b", received_at=T2)        # 2通目が来ても最初の受信時刻を保つ
    assert busy.take_followup_anchor() == T1
    assert busy.take_followup_anchor() is None       # 読んだら消える
    assert busy._pending.qsize() == 2                # 本文はどちらも待ち行列に残る


def test_starting_a_new_turn_drops_the_anchor():
    s = _session(turn_active=True)
    s.submit_followup("a", received_at=T1)
    s._send_user("a")                                # 次のターンが始まる = 目印は持ち越さない
    assert s.take_followup_anchor() is None


def test_submit_without_time_keeps_old_behaviour():
    s = _session(turn_active=True)
    s.submit_followup("a")
    assert s._pending.get_nowait() == "a"
    assert s.take_followup_anchor() is None


def test_just_before_iso():
    assert cr._just_before_iso(T1) == "2026-10-13T05:50:43.693969+00:00"
    assert cr._just_before_iso("2026-10-13T05:50:43Z") == "2026-10-13T05:50:42.999000+00:00"
    assert cr._just_before_iso("garbage") is None
    assert cr._just_before_iso("") is None


def test_just_before_iso_accepts_trimmed_fraction_from_db():
    # PostgREST は秒の小数の末尾の 0 を省いて返す。Python 3.10 ではそのままだと読めない（2026-10-13 実測）。
    assert cr._just_before_iso("2026-10-13T08:38:16.1801+00:00") == "2026-10-13T08:38:16.179100+00:00"
    assert cr._just_before_iso("2026-10-13T08:38:16.18+00:00") == "2026-10-13T08:38:16.179000+00:00"
    assert cr._just_before_iso("2026-10-13T08:38:16.1801Z") == "2026-10-13T08:38:16.179100+00:00"
