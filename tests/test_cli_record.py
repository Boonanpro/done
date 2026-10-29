"""担当（CLI の子プロセス）が自分の側に残す記録（2026-10-29）。

X顧問の部屋で担当が 14:41 に固まった時、担当の詳しい記録は無く、JSON 以外で出した言葉も本体が
捨てていたので、凍る直前に何を見たかが分からなかった。直し: 担当を起こす時に --debug-file で
部屋ごと・起動ごとの記録を渡す／JSON 以外の行（stderr を含む）は部屋の記録へ残す／古い記録は消す。
"""
import io
import os
import time
from unittest.mock import MagicMock

import pytest

from app.agent import cli_record


@pytest.fixture
def records(tmp_path, monkeypatch):
    monkeypatch.setenv("DAN_CLI_RECORDS_DIR", str(tmp_path / "rec"))
    monkeypatch.setattr(cli_record, "_last_prune_at", 0.0)
    return tmp_path / "rec"


def test_debug_file_is_per_room_and_per_launch(records):
    a = cli_record.debug_file_path("room-abcdefgh-xyz")
    b = cli_record.debug_file_path("room-abcdefgh-xyz")
    assert a != b                                            # 同じ秒に 2 回起こしても別の名前
    assert os.path.dirname(a) == str(records / "room-abc")   # 部屋の先頭 8 桁
    assert os.path.basename(a).startswith("claude_")
    assert cli_record.debug_file_path("r", backend="job_12345678").endswith(".log")


def test_stray_line_keeps_backend_source_and_truncates(records):
    cli_record.stray_line("room-1", "claude", "API error (attempt 3/11): fetch failed", source="stderr")
    cli_record.stray_line("room-1", "codex", "x" * 5000)
    cli_record.stray_line("room-1", "claude", "   ")          # 空行は書かない
    files = list((records / "room-1").glob("stray_*.log"))
    assert len(files) == 1
    body = files[0].read_text(encoding="utf-8")
    lines = body.splitlines()
    assert len(lines) == 2
    assert "[claude:stderr] API error (attempt 3/11): fetch failed" in lines[0]
    assert "[codex:stdout] " in lines[1] and len(lines[1]) < 2100 and lines[1].endswith("…")


def test_prune_removes_old_files_and_caps_a_room(records, monkeypatch):
    monkeypatch.setattr(cli_record, "_KEEP_DAYS", 7.0)
    monkeypatch.setattr(cli_record, "_ROOM_CAP_BYTES", 30)
    d = records / "room-2"
    d.mkdir(parents=True)
    now = time.time()
    old = d / "claude_old.log"; old.write_text("old")
    os.utime(old, (now - 8 * 86400, now - 8 * 86400))
    big1 = d / "claude_a.log"; big1.write_text("a" * 20)
    os.utime(big1, (now - 3000, now - 3000))
    big2 = d / "claude_b.log"; big2.write_text("b" * 20)
    os.utime(big2, (now - 2000, now - 2000))
    keep = d / "stray_today.log"; keep.write_text("k")
    removed = cli_record.prune(force=True, now=now)
    assert removed == 2
    assert not old.exists()                     # 7 日より古い
    assert not big1.exists() and big2.exists()  # 上限超えは古い順に消す
    assert keep.exists()
    # 1 時間に 1 回しか歩かない
    gone = d / "claude_c.log"; gone.write_text("c")
    os.utime(gone, (now - 9 * 86400, now - 9 * 86400))
    assert cli_record.prune(now=now + 10) == 0
    assert cli_record.prune(now=now + 3601) == 1


def test_latest_debug_file(records):
    assert cli_record.latest_debug_file("none") is None
    p1 = cli_record.debug_file_path("room-3")
    open(p1, "w").close()
    time.sleep(0.01)
    p2 = cli_record.debug_file_path("room-3")
    open(p2, "w").close()
    os.utime(p2, None)
    assert str(cli_record.latest_debug_file("room-3")) == p2


def test_build_cli_cmd_passes_debug_file_only_when_given():
    from app.agent import cli_runner as cr
    base = cr._build_cli_cmd("claude", None, "mcp.json", "SYS", None, model="fable")
    assert "--debug-file" not in base
    with_file = cr._build_cli_cmd("claude", None, "mcp.json", "SYS", None, model="fable", debug_file="/tmp/x.log")
    assert with_file[:-2] == base and with_file[-2:] == ["--debug-file", "/tmp/x.log"]


def test_streaming_session_records_non_json_lines(records):
    from app.agent import streaming_session as ss
    s = ss.StreamingSession("room-4", lambda: ["x"], {}, "D:/")
    seen = []
    s._dispatch = lambda ev: seen.append(ev)   # type: ignore[method-assign]
    proc = MagicMock()
    proc.stdout = io.StringIO('{"type": "system", "session_id": "s1"}\nError: fetch failed (attempt 2/11)\n\n')
    s._proc = proc
    s._read_loop()
    assert seen == [{"type": "system", "session_id": "s1"}]
    body = next((records / "room-4").glob("stray_*.log")).read_text(encoding="utf-8")
    assert "[claude:stdout] Error: fetch failed (attempt 2/11)" in body


def test_streaming_build_cmd_includes_debug_file(records):
    """常駐の担当を起こす命令にも記録の指定が付く（build_cmd は起こすたびに呼ばれる）。"""
    from app.agent import cli_runner as cr
    import inspect
    src = inspect.getsource(cr.process_message_cli_streaming) if hasattr(cr, "process_message_cli_streaming") else ""
    if not src:
        pytest.skip("streaming entry not found by name")
    assert "--debug-file" in src and "_cli_record.debug_file_path(room_id)" in src
