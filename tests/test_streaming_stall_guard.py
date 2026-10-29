"""固まった担当（CLI）の立て直し（2026-10-29）。

X顧問の部屋で、担当が 14:41 から道具の結果の後に何も出さず固まった。30分黙ったら立て直す
仕組みはあったが、15:09 の追い連絡が沈黙の数えを最初に戻していたので、催促するほど立て直しが
遅れた。直し: 追い連絡は数えを戻さない／モデルの返事待ちの沈黙は10分で見切る（道具の実行中は
従来の30分）／固まっている間に届いた追い連絡は新しい担当へ渡し直す。
"""
import time
from unittest.mock import MagicMock

from app.agent import streaming_session as ss


def _session() -> ss.StreamingSession:
    s = ss.StreamingSession("room-x", lambda: ["x"], {}, "D:/")
    s._write = MagicMock()          # 実プロセスなし
    s.is_alive = lambda: True       # type: ignore[method-assign]
    s.stop = MagicMock()            # type: ignore[method-assign]
    return s


def _assistant(tool: bool):
    content = [{"type": "tool_use", "name": "Bash", "input": {}}] if tool else [{"type": "text", "text": "はい"}]
    return {"type": "assistant", "message": {"role": "assistant", "content": content}}


def _tool_result():
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}}


def test_followup_does_not_push_back_the_hang_clock():
    s = _session()
    s._turn = ss._Turn(sink=None)
    s._last_activity = time.time() - 100
    s.submit_followup("まだ？", received_at="2026-10-29T06:09:05+00:00")
    assert time.time() - s._last_activity >= 99     # CLI の沈黙はそのまま数え続ける
    assert s.idle_seconds() < 1                      # 手が空いているかの判定には入力も数える


def test_tool_state_follows_cli_events():
    s = _session()
    s._turn = ss._Turn(sink=None)
    s._dispatch(_assistant(tool=True))
    assert s._tool_in_flight
    s._dispatch(_tool_result())
    assert not s._tool_in_flight
    s._dispatch(_assistant(tool=False))
    assert not s._tool_in_flight
    s._dispatch(_assistant(tool=True))
    s._send_user("次")                                # 新しいターン = 道具は動いていない
    assert not s._tool_in_flight


def test_silence_limit_is_shorter_while_waiting_for_the_model(monkeypatch):
    monkeypatch.setattr(ss, "_MODEL_SILENCE_TIMEOUT", 600.0)
    s = _session()
    assert s.silence_limit(1800) == 600
    s._tool_in_flight = True
    assert s.silence_limit(1800) == 1800
    s._tool_in_flight = False
    assert s.silence_limit(300) == 300               # 短い方の上限が来ていればそれ


def test_run_turn_gives_up_on_model_silence_and_keeps_followups(monkeypatch):
    monkeypatch.setattr(ss, "_MODEL_SILENCE_TIMEOUT", 0.3)
    monkeypatch.setattr(ss, "_RUN_TURN_POLL_SECONDS", 0.05)
    s = _session()

    def write(obj):                                   # 本文を書いた直後に追い連絡が届く。CLI は何も返さない
        if obj.get("type") == "user":
            s.submit_followup("まだ？")
    s._write = write                                  # type: ignore[method-assign]

    t0 = time.time()
    res = s.run_turn("やって", sink=None, timeout=5.0)
    assert res is None and s.last_turn_hung
    assert time.time() - t0 < 2.0                     # 5分でも30分でもなく、モデル待ちの上限で見切る
    assert s.take_pending_followups() == "まだ？"     # 追い連絡は捨てずに渡し直せる
    assert s.take_pending_followups() is None


def test_run_turn_waits_the_long_limit_while_a_tool_runs(monkeypatch):
    monkeypatch.setattr(ss, "_MODEL_SILENCE_TIMEOUT", 0.2)
    monkeypatch.setattr(ss, "_RUN_TURN_POLL_SECONDS", 0.05)
    s = _session()

    def write(obj):                                   # CLI が道具を実行中のまま黙る
        if obj.get("type") == "user":
            s._dispatch(_assistant(tool=True))
    s._write = write                                  # type: ignore[method-assign]

    t0 = time.time()
    res = s.run_turn("やって", sink=None, timeout=0.8)
    assert res is None and s.last_turn_hung
    assert time.time() - t0 >= 0.75                   # 道具の実行中は長い方の上限まで待つ
