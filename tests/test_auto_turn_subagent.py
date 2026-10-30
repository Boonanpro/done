"""担当が自分で始めたターンの読み違え（2026-10-30）。

X顧問の部屋で、担当が返事の直後に裏の手伝い（Agent, run_in_background）を起こした。その
手伝いの出力（parent_tool_use_id つき）を本体が「担当の新しいターン」と数えて _auto_active を
立てたが、本体の result は来ないので解けず、その後の本人の言葉は全部「仕事中への追い連絡」と
して待ち行列に溜まったまま届かなかった。直し: 裏の担当の出力は手が空いている間は無視する／
自分で始めたターンは専用の糸で沈黙を見張り、result が来ないまま黙ったら終わったとみなして
待たせていた言葉を送る。
"""
import time
from unittest.mock import MagicMock

from app.agent import streaming_session as ss


def _session() -> ss.StreamingSession:
    s = ss.StreamingSession("room-auto", lambda: ["x"], {}, "D:/")
    s._write = MagicMock()          # 実プロセスなし
    s.is_alive = lambda: True       # type: ignore[method-assign]
    s.stop = MagicMock()            # type: ignore[method-assign]
    return s


def _assistant(text="はい", parent=None):
    ev = {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}
    if parent:
        ev["parent_tool_use_id"] = parent
    return ev


def _user(parent=None):
    ev = {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}}
    if parent:
        ev["parent_tool_use_id"] = parent
    return ev


def _wait(cond, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def test_subagent_output_while_idle_is_not_a_turn():
    """手が空いている担当の裏の手伝いが喋っても、担当は仕事中にならない。"""
    s = _session()
    seen = []
    s.background_sink = seen.append
    s._dispatch(_assistant("索引を縮めています", parent="toolu_01"))
    s._dispatch(_user(parent="toolu_01"))
    assert s._auto_active is False
    assert s.is_turn_active() is False
    assert seen == []                       # 裏の手伝いの言葉は表に出さない
    # 本人の言葉は追い連絡ではなく、普通のターンとして扱われる
    assert ss.is_turn_active_or_preparing("room-auto") is False


def test_main_agent_wake_still_counts_as_a_turn():
    """担当本体が自分で起きた時（parent 無し）は従来どおり仕事中になり、result で終わる。"""
    s = _session()
    seen = []
    s.background_sink = seen.append
    s._dispatch(_assistant("裏の作業が終わったので続けます"))
    assert s._auto_active is True
    assert s.is_turn_active() is True
    s._dispatch({"type": "result", "is_error": False, "result": "done"})
    assert s._auto_active is False
    assert [e["type"] for e in seen] == ["assistant", "result"]
    assert _wait(lambda: not s._auto_watch_running)


def test_interrupted_auto_turn_without_result_releases_pending_words(monkeypatch):
    """割り込みを送ったのに result が来ない: 短い猶予の後、待たせていた本人の言葉を送る。"""
    monkeypatch.setattr(ss, "_AUTO_INTERRUPT_GRACE", 0.2)
    monkeypatch.setattr(ss, "_AUTO_WATCH_POLL", 0.05)
    s = _session()
    s._dispatch(_assistant("続けます"))
    assert s._auto_active
    s.submit_followup("映しも直せるようにして")
    s.submit_followup("送れるなら送って")
    s._interrupt_sent = True                 # 本人の言葉で割り込みを送った（cli_runner の経路）
    s._last_activity = time.time()           # その後は沈黙
    assert _wait(lambda: s._write.call_count >= 1)
    sent = s._write.call_args_list[-1].args[0]
    assert sent["type"] == "user"
    assert "映しも直せるようにして" in sent["message"]["content"]
    assert "送れるなら送って" in sent["message"]["content"]
    assert s._pending.empty()
    assert s._auto_active is True            # 送った言葉のターンとして見張りは続く
    assert s._interrupt_sent is False
    s._dispatch({"type": "result", "is_error": False, "result": "ok"})
    assert s._auto_active is False


def test_silent_auto_turn_is_given_up_after_the_limit(monkeypatch):
    """割り込み無しでも、固まりの上限を超えて黙れば仕事中が解ける。"""
    monkeypatch.setattr(ss, "_AUTO_TURN_SILENCE_TIMEOUT", 0.2)
    monkeypatch.setattr(ss, "_MODEL_SILENCE_TIMEOUT", 0.2)
    monkeypatch.setattr(ss, "_AUTO_WATCH_POLL", 0.05)
    s = _session()
    s._dispatch(_assistant("続けます"))
    assert s._auto_active
    assert _wait(lambda: not s._auto_active)
    assert s._write.call_count == 0          # 送る言葉が無ければ何も送らない
    assert _wait(lambda: not s._auto_watch_running)


def test_live_auto_turn_is_not_cut_while_it_keeps_talking(monkeypatch):
    monkeypatch.setattr(ss, "_AUTO_TURN_SILENCE_TIMEOUT", 0.3)
    monkeypatch.setattr(ss, "_MODEL_SILENCE_TIMEOUT", 0.3)
    monkeypatch.setattr(ss, "_AUTO_WATCH_POLL", 0.05)
    s = _session()
    s._dispatch(_assistant("続けます"))
    for _ in range(6):
        time.sleep(0.1)
        s._last_activity = time.time()       # 出力が続いている（_read_loop が進める）
        s._dispatch(_assistant("まだ"))
    assert s._auto_active is True
