"""2回目の修正（確かめる役の指摘）: ストリーミング経路の起き直しにも dan-compact が付く／
ターン終了の compaction 同期は今のセッションの transcript 1 ファイルだけ。

- 生きているセッションのモデルが変わって起き直す時も --plugin-dir と env が付く（基準5）
- 同じモデルを再利用するターンでも build_cmd / env にプラグインが入る（予熱ローテーション・
  stale-resume の作り直しは、そのターンの build_cmd / env で替えを起こすため）
- 鍵が無ければ起動オプション・env は今までどおり（完全一致）
- ターンが閉じた後（sentinel の後）に sync_compaction_summaries(paths=[今の transcript]) だけが呼ばれる（基準8）
"""
import queue
import threading

import pytest

from app.agent import cli_runner as cr
from app.services import work_locks as _work_locks
from tests.test_dan_compact_launch import KEY, isolate  # noqa: F401  (fixture を共有)


def test_launch_log_false_keeps_the_decision_and_only_silences_the_log(monkeypatch, isolate):
    monkeypatch.setattr(cr, "_typesafe_api_key_sync", lambda uid: KEY)
    loud = cr._dan_compact_launch("user")
    isolate.logs.clear()
    quiet = cr._dan_compact_launch("user", log=False)
    assert quiet == loud
    assert isolate.logs == [], "再利用ターンの解決はログを出さない"


def test_streaming_session_is_fresh_includes_model_switch():
    class S:
        def __init__(self, alive, model):
            self._alive, self.model = alive, model

        def is_alive(self):
            return self._alive

    assert cr._streaming_session_is_fresh(None, "fable") is True
    assert cr._streaming_session_is_fresh(S(False, "fable"), "fable") is True, "死んでいる"
    assert cr._streaming_session_is_fresh(S(True, "fable"), "fable") is False, "生きていて同じモデル＝再利用"
    assert cr._streaming_session_is_fresh(S(True, "opus"), "fable") is True, "生きていてもモデルが違えば起き直し"
    assert cr._streaming_session_is_fresh(S(True, None), "fable") is True


def _fake_sync(monkeypatch):
    calls: list = []
    done = threading.Event()

    def fake(paths=None):
        calls.append(list(paths) if paths is not None else None)
        done.set()
        return 1

    from app.services import compaction_sync
    monkeypatch.setattr(compaction_sync, "sync_compaction_summaries", fake)
    return calls, done


def test_sync_compaction_for_session_passes_only_that_transcript(monkeypatch, isolate, tmp_path):
    calls, _ = _fake_sync(monkeypatch)
    transcript = tmp_path / "sid-1.jsonl"
    monkeypatch.setattr(cr, "_session_transcript_path", lambda sid: transcript if sid == "sid-1" else None)

    assert cr._sync_compaction_for_session("sid-1", "room-1") == 1
    assert calls == [[transcript]], "全走査（paths=None）ではなく今のセッションの 1 ファイルだけ"
    assert any("compaction sync: mirrored 1 from sid-1.jsonl" in line for line in isolate.logs)

    assert cr._sync_compaction_for_session(None, "room-1") == 0
    assert cr._sync_compaction_for_session("unknown", "room-1") == 0
    assert calls == [[transcript]], "transcript が見つからなければ呼ばない"


def test_sync_compaction_for_session_swallows_errors(monkeypatch, isolate, tmp_path):
    monkeypatch.setattr(cr, "_session_transcript_path", lambda sid: tmp_path / "x.jsonl")

    def boom(paths=None):
        raise RuntimeError("disk gone")

    from app.services import compaction_sync
    monkeypatch.setattr(compaction_sync, "sync_compaction_summaries", boom)
    assert cr._sync_compaction_for_session("sid-1", "room-1") == 0
    assert any("compaction sync skipped (non-fatal): RuntimeError: disk gone" in line for line in isolate.logs)


class _FakeSession:
    """streaming_session.StreamingSession の、プロセスを起こさない代役。"""

    def __init__(self, model, events=None):
        self.model = model
        self.events = events or []
        self.stopped = False
        self.sent: list = []
        self._pending: "queue.Queue[str]" = queue.Queue()
        self._interrupt_sent = False
        self._user_cancelled = False
        self._discard_turn = None
        self._turn = None
        self.last_turn_hung = False
        self.background_sink = None

    def is_alive(self):
        return not self.stopped

    def is_turn_active(self):
        return False

    def stop(self):
        self.stopped = True

    def run_turn(self, content, sink, timeout=600.0):
        self.sent.append(content)
        res = None
        for ev in self.events:
            sink(ev)
            if ev.get("type") == "result":
                res = ev
        return res


_TURN = [{"type": "system", "session_id": "sid-1"}, {"type": "result", "result": "ok"}]
# 本番のストリーミング起動の引数（この並びが変わらないことを完全一致で固定する）
_BASE_STREAMING_CMD = [
    "claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
    "--dangerously-skip-permissions", "--model", "fable", "--mcp-config", "mcp.json",
    "--append-system-prompt", "SYS", "--disallowedTools", "ExitPlanMode,AskUserQuestion",
    "--settings", _work_locks.hook_settings(),   # main の並行作業（ファイルの順番待ちフック）
    "--resume", "sid-1",
]


def _wire_streaming(monkeypatch, *, existing, created, transcript):
    """_process_via_streaming_session を、DB・プロセス無しで1ターン回せるようにする。"""
    from app.agent import streaming_session as ss
    monkeypatch.setattr(cr, "_resolve_claude_cli", lambda: ("claude", None))
    monkeypatch.setattr(cr, "_resolve_cli_model", lambda room_id=None: "fable")
    monkeypatch.setattr(ss, "get_session", lambda room_id: existing)
    captured: dict = {}

    def fake_get_or_create(room_id, build_cmd, env, cwd, *, model=None):
        captured.update(room_id=room_id, cmd=build_cmd(), env=dict(env), model=model)
        if existing is not None and existing.is_alive() and existing.model == model:
            return existing
        return created

    monkeypatch.setattr(ss, "get_or_create_session", fake_get_or_create)
    launches: list = []

    def fake_launch(user_id, *, log=True):
        launches.append((user_id, log))
        return ["--plugin-dir", "P"], {"CLAUDE_CODE_ENABLE_FUNCTION_HOOKS": "1", "TYPESAFE_API_KEY": KEY}

    monkeypatch.setattr(cr, "_dan_compact_launch", fake_launch)
    for name in ("_save_session", "_update_run_sync", "_clear_cli_session", "_save_ai_message_sync", "_save_execution_event_sync"):
        monkeypatch.setattr(cr, name, lambda *a, **k: None)
    monkeypatch.setattr(cr, "_notify_achievement_poller", lambda: None)
    monkeypatch.setattr(cr, "_transcript_exceeds_limit", lambda sid: False)
    monkeypatch.setattr(cr, "_transcript_soft_exceeded", lambda sid: False)
    monkeypatch.setattr(cr, "_compact_transcript_images", lambda sid, keep_recent=None: True)
    monkeypatch.setattr(cr, "_build_reseed_context", lambda room_id, project_id=None: "")
    monkeypatch.setattr(cr, "_session_transcript_path", lambda sid: transcript if sid == "sid-1" else None)
    sync_calls, sync_done = _fake_sync(monkeypatch)
    return captured, launches, sync_calls, sync_done


async def _run_turn(room="room-1", user="user-1"):
    return [
        ev async for ev in cr._process_via_streaming_session(
            room, user, "hello", "SYS", "mcp.json", None, None, True, None, resume_session_id="sid-1",
        )
    ]


@pytest.mark.asyncio
async def test_streaming_model_switch_restart_gets_plugin_and_syncs_only_its_transcript(monkeypatch, isolate, tmp_path):
    """基準5: 生きているセッションのモデルが変わって起き直す時も --plugin-dir と env が付く。
    基準8: ターンが閉じた後に、今のセッションの transcript 1 ファイルだけが同期に渡る。"""
    transcript = tmp_path / "sid-1.jsonl"
    transcript.write_text("", encoding="utf-8")
    existing = _FakeSession("opus")
    created = _FakeSession("fable", events=_TURN)
    captured, launches, sync_calls, sync_done = _wire_streaming(monkeypatch, existing=existing, created=created, transcript=transcript)

    events = await _run_turn()

    assert existing.stopped, "モデルが違う生きたセッションは止めて起こし直す"
    assert captured["model"] == "fable"
    assert captured["cmd"] == _BASE_STREAMING_CMD + ["--plugin-dir", "P"], "既存の引数はそのまま、末尾に付くだけ"
    assert captured["env"]["TYPESAFE_API_KEY"] == KEY
    assert captured["env"]["CLAUDE_CODE_ENABLE_FUNCTION_HOOKS"] == "1"
    assert launches == [("user-1", True)], "起き直しのターンはログ付きで解決"
    assert created.sent == ["hello"]
    assert [ev for ev in events if ev.get("type") == "result"][0]["text"] == "ok"
    assert sync_done.wait(5), "ターン終了後に同期が呼ばれる"
    assert sync_calls == [[transcript]], "全走査ではなく今のセッションの transcript だけ"


@pytest.mark.asyncio
async def test_streaming_reused_session_keeps_plugin_in_cmd_and_env_for_later_restarts(monkeypatch, isolate, tmp_path):
    """同じモデルの生きたセッションを再利用するターンでも build_cmd / env にプラグインが入る
    （予熱ローテーションと stale-resume の作り直しは、このターンの build_cmd / env で替えを起こす）。"""
    transcript = tmp_path / "sid-1.jsonl"
    transcript.write_text("", encoding="utf-8")
    existing = _FakeSession("fable", events=_TURN)
    captured, launches, sync_calls, sync_done = _wire_streaming(monkeypatch, existing=existing, created=None, transcript=transcript)

    events = await _run_turn()

    assert not existing.stopped
    assert existing.sent == ["hello"]
    assert launches == [("user-1", False)], "再利用ターンはログ無しで解決"
    assert captured["cmd"] == _BASE_STREAMING_CMD + ["--plugin-dir", "P"]
    assert captured["env"]["TYPESAFE_API_KEY"] == KEY
    assert [ev for ev in events if ev.get("type") == "result"][0]["text"] == "ok"
    assert sync_done.wait(5)
    assert sync_calls == [[transcript]]


@pytest.mark.asyncio
async def test_streaming_without_plugin_leaves_cmd_and_env_exactly_as_before(monkeypatch, isolate, tmp_path):
    """鍵が無い（_dan_compact_launch が ([], {})）なら、起動オプションも env も今までどおり。"""
    existing = _FakeSession("opus")
    created = _FakeSession("fable", events=_TURN)
    captured, _, _, sync_done = _wire_streaming(monkeypatch, existing=existing, created=created, transcript=None)
    monkeypatch.setattr(cr, "_dan_compact_launch", lambda user_id, *, log=True: ([], {}))

    await _run_turn()

    assert captured["cmd"] == _BASE_STREAMING_CMD
    assert "TYPESAFE_API_KEY" not in captured["env"]
    assert "CLAUDE_CODE_ENABLE_FUNCTION_HOOKS" not in captured["env"]
    assert captured["env"]["NO_COLOR"] == "1" and captured["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert captured["env"]["DAN_LOCK_OWNER"] == "room:room-1", "main の並行作業の持ち主の印もそのまま"
    assert not sync_done.wait(0.5), "transcript が見つからなければ同期は呼ばれない"
