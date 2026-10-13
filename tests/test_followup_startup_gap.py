"""起動待ちの間に届いた追い連絡（2026-10-14）。

1通目の送信から run_turn が最初の本文を書くまでの数秒（文脈の組み立て・CLI 起動）に
届いた発言は、「方針変更」で前のターンを止めるのではなく、追い連絡として待たせる。
待たせた分は最初の本文を書いた直後に待ち行列へ移り、受信時刻の目印も運ばれる。
"""
import threading
import time
from unittest.mock import MagicMock

import pytest

from app.agent import streaming_session as ss

ROOM = "room-startup-gap"
T1 = "2026-10-14T00:00:10.000000+00:00"


@pytest.fixture(autouse=True)
def _clean_registry():
    with ss._prep_lock:
        ss._prep_claims.pop(ROOM, None)
        ss._pre_queue.pop(ROOM, None)
    with ss._registry_lock:
        ss._sessions.pop(ROOM, None)
    yield
    with ss._prep_lock:
        ss._prep_claims.pop(ROOM, None)
        ss._pre_queue.pop(ROOM, None)
    with ss._registry_lock:
        ss._sessions.pop(ROOM, None)


def _fake_session() -> ss.StreamingSession:
    """実プロセスなし。_write は記録だけ、start は何もしない。"""
    s = ss.StreamingSession(ROOM, lambda: ["x"], {}, "D:/")
    s._write = MagicMock()
    s.start = lambda: None                 # type: ignore[method-assign]
    s.is_alive = lambda: True              # type: ignore[method-assign]
    with ss._registry_lock:
        ss._sessions[ROOM] = s
    return s


def test_no_session_and_no_claim_is_idle():
    assert ss.is_turn_active_or_preparing(ROOM) is False


def test_claim_makes_the_room_look_busy_until_released():
    token = ss.claim_turn(ROOM)
    assert ss.is_turn_active_or_preparing(ROOM) is True
    ss.release_turn_claim(ROOM, token)
    assert ss.is_turn_active_or_preparing(ROOM) is False
    ss.release_turn_claim(ROOM, token)      # 二度外しても壊れない


def test_stale_claim_expires():
    token = ss.claim_turn(ROOM)
    with ss._prep_lock:
        ss._prep_claims[ROOM][token] = time.time() - ss._CLAIM_TTL - 1
    assert ss.is_turn_active_or_preparing(ROOM) is False


def test_followup_during_preparation_waits_in_the_room_queue():
    ss.claim_turn(ROOM)                     # セッションはまだ無い
    assert ss.submit_room_followup(ROOM, "追い", received_at=T1) == "pre_queue"
    assert ss.pending_pre_queue(ROOM) == 1


def test_followup_before_first_write_waits_even_if_the_session_exists():
    s = _fake_session()
    s._turn = object()                      # run_turn に入ったが、まだ本文を書いていない
    assert ss.submit_room_followup(ROOM, "追い", received_at=T1) == "pre_queue"
    assert s._pending.qsize() == 0


def test_followup_after_first_write_goes_straight_to_the_session():
    s = _fake_session()
    s._turn = object()
    s._turn_sent = True
    assert ss.submit_room_followup(ROOM, "追い", received_at=T1) == "session"
    assert s._pending.qsize() == 1
    assert s.take_followup_anchor() == T1


def test_followup_during_autonomous_turn_goes_to_the_session():
    s = _fake_session()
    s._auto_active = True
    assert ss.submit_room_followup(ROOM, "追い", received_at=T1) == "session"
    assert s._pending.qsize() == 1


def test_run_turn_moves_waiting_followups_into_the_queue_with_the_anchor():
    """1通目の準備中に追い連絡 → run_turn が本文を書いた直後に待ち行列へ移り、
    目印（受信時刻）は _send_user の後に立つので消えない。印も外れる。"""
    token = ss.claim_turn(ROOM)
    s = _fake_session()
    assert ss.submit_room_followup(ROOM, "追い", received_at=T1) == "pre_queue"

    seen = {}

    def fake_send_user(text):
        # 本文を書く瞬間: まだ待ち行列は空で、目印も無い
        seen["pending_at_send"] = s._pending.qsize()
        seen["anchor_at_send"] = s._followup_anchor
        s._followup_anchor = None
        # 書いた直後にターンを終わらせる（CLI の result 相当）
        def finish():
            time.sleep(0.05)
            turn = s._turn
            # 待ち行列に移った追い連絡を次ターンとして送らせない: ここで空にする
            seen["pending_after_send"] = s._pending.qsize()
            seen["anchor_after_send"] = s._followup_anchor
            seen["claim_after_send"] = ss.is_turn_active_or_preparing(ROOM)
            seen["turn_sent"] = s._turn_sent
            while not s._pending.empty():
                s._pending.get_nowait()
            turn.result = {"type": "result", "is_error": False}
            turn.done.set()
        threading.Thread(target=finish, daemon=True).start()

    s._send_user = fake_send_user            # type: ignore[method-assign]
    res = s.run_turn("1通目", sink=lambda ev: None, timeout=5)
    assert res == {"type": "result", "is_error": False}
    assert seen["pending_at_send"] == 0 and seen["anchor_at_send"] is None
    assert seen["pending_after_send"] == 1
    assert seen["anchor_after_send"] == T1
    assert seen["turn_sent"] is True
    assert seen["claim_after_send"] is True   # ターン実行中（_turn あり）
    assert ss.pending_pre_queue(ROOM) == 0
    with ss._prep_lock:
        assert ROOM not in ss._prep_claims    # 印は本文を書いた時点で外れている
    assert s._turn_sent is False               # 終わったら戻る
    ss.release_turn_claim(ROOM, token)


def test_concurrent_run_turn_is_routed_not_none():
    """同じセッションで別の run_turn が走っている時、2つ目は None でなく
    routed_as_followup を返す（None だと呼び出し側がセッションを止め直していた）。"""
    s = _fake_session()
    s._running = True
    res = s.run_turn("2通目", sink=lambda ev: None, timeout=1)
    assert res == {"type": "result", "subtype": "routed_as_followup", "is_error": False}
    assert s._pending.qsize() == 1
