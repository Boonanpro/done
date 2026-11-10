"""The CLIs follow new models, the picker says what the next turn really runs, and a live room session
moves to an updated CLI at its next turn (2026-11-10: Fable 5.2 was shown, 5.1 ran)."""
import json
import os
import stat
import sys
import time

import pytest

from app.agent import cli_versions as cv
from app.agent import model_catalog as mc
from app.agent import streaming_session as ss


def _fake_claude(tmp_path, monkeypatch, ids):
    path = tmp_path / "claude"
    path.write_bytes(b"\x00junk " + b" ".join(i.encode() for i in ids) + b" \x00")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(cv.shutil, "which", lambda name: str(path) if name == "claude" else None)
    monkeypatch.setattr(cv, "_scan_cache", {"fp": None, "models": {}})
    return path


OLD_CLI = ["claude-fable-5-1", "claude-opus-5-5", "claude-opus-4-20250514", "claude-sonnet-5-5", "claude-haiku-3-55"]


def test_reads_newest_model_of_each_family_from_the_binary(tmp_path, monkeypatch):
    _fake_claude(tmp_path, monkeypatch, OLD_CLI)
    known = cv.claude_cli_models()
    assert known["fable"] == ((5, 1), "claude-fable-5-1")
    assert known["opus"] == ((5, 5), "claude-opus-5-5")     # a dated 4-20250514 is not read as 4.20
    assert cv.label_for_id("claude-fable-5-2") == "Claude Fable 5.2"
    assert cv.label_for_id("claude-opus-6") == "Claude Opus 6"


def _api(fable="claude-fable-5-2"):
    return {"fable": {"id": fable, "label": "Claude Fable " + fable.split("-", 2)[2].replace("-", ".")},
            "opus": {"id": "claude-opus-5-5", "label": "Claude Opus 5.5"},
            "sonnet": {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5"}}


def test_picker_shows_what_the_installed_cli_runs(tmp_path, monkeypatch):
    path = _fake_claude(tmp_path, monkeypatch, OLD_CLI)
    families = _api()
    # Anthropic lists Fable 5.2, the CLI only knows 5.1: the room runs 5.1, so 5.1 is shown
    assert mc.alias_label("fable", families) == "Claude Fable 5.1"
    assert mc.alias_label("opus", families) == "Claude Opus 5.5"
    assert cv.cli_behind(families)
    # after the update the CLI knows 5.2
    time.sleep(0.01)
    path.write_bytes(b" ".join(i.encode() for i in OLD_CLI + ["claude-fable-5-2"]))
    assert mc.alias_label("fable", families) == "Claude Fable 5.2"
    assert not cv.cli_behind(families)


def test_update_runs_daily_or_sooner_for_an_unknown_model(tmp_path, monkeypatch):
    monkeypatch.setattr(cv, "_STATE", tmp_path / "cli_update.json")
    now = time.time()
    assert cv.due(False, now)                                      # never checked
    cv._write_state({"checked_at": now - 7 * 3600})
    assert not cv.due(False, now) and cv.due(True, now)            # 7h ago: not daily yet, but a new model is waiting
    cv._write_state({"checked_at": now - 25 * 3600})
    assert cv.due(False, now)
    monkeypatch.setenv("DAN_CLI_AUTO_UPDATE", "0")
    assert not cv.ensure_current_in_background(True)


def test_update_installs_newer_versions_from_npm(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    for pkg, ver in (("@anthropic-ai/claude-code", "2.1.303"), ("@openai/codex", "0.167.0")):
        (root / pkg).mkdir(parents=True)
        (root / pkg / "package.json").write_text(json.dumps({"version": ver}))
    log = tmp_path / "npm.log"
    npm = tmp_path / "npm"
    npm.write_text(f"""#!{sys.executable}
import json, sys, pathlib
args = sys.argv[1:]
open({str(log)!r}, "a").write(" ".join(args) + "\\n")
root = pathlib.Path({str(root)!r})
latest = {{"@anthropic-ai/claude-code": "2.1.321", "@openai/codex": "0.167.0"}}
if args[:2] == ["root", "-g"]: print(root)
elif args[0] == "view": print(latest[args[1]])
elif args[:2] == ["install", "-g"]:
    pkg, ver = args[2].rsplit("@", 1)
    (root / pkg / "package.json").write_text(json.dumps({{"version": ver}}))
""")
    npm.chmod(0o755)
    monkeypatch.setattr(cv, "_npm", lambda: str(npm))
    monkeypatch.setattr(cv, "_STATE", tmp_path / "cli_update.json")
    monkeypatch.setattr(cv, "_LOCK", tmp_path / "cli_update.lock")
    out = cv.update_clis("test")
    assert out["packages"]["claude"] == {"before": "2.1.303", "latest": "2.1.321", "after": "2.1.321"}
    assert out["packages"]["codex"] == {"before": "0.167.0", "latest": "0.167.0"}    # already newest: not reinstalled
    assert "install -g @anthropic-ai/claude-code@2.1.321" in log.read_text()
    assert "@openai/codex@" not in log.read_text()
    assert json.loads((tmp_path / "cli_update.json").read_text())["reason"] == "test"


@pytest.fixture
def fake_cli(tmp_path):
    """A stand-in CLI that stays alive reading stdin (like claude -p --input-format stream-json)."""
    path = tmp_path / "fakecli"
    path.write_text(f"#!{sys.executable}\nimport sys\nfor _ in sys.stdin: pass\n")
    path.chmod(0o755)
    return path


def _replace(path):
    """npm install replaces the file (new inode), it does not edit it."""
    new = path.with_suffix(".new")
    new.write_text(path.read_text() + "# updated\n")
    new.chmod(0o755)
    os.replace(new, path)


def test_idle_room_session_restarts_on_the_updated_cli(fake_cli, monkeypatch):
    monkeypatch.setattr(ss, "_sessions", {})
    first = ss.get_or_create_session("room-a", lambda: [str(fake_cli)], dict(os.environ), str(fake_cli.parent), model="fable")
    try:
        assert ss.get_or_create_session("room-a", lambda: [str(fake_cli)], dict(os.environ), str(fake_cli.parent), model="fable") is first
        _replace(fake_cli)
        assert first.binary_changed()
        second = ss.get_or_create_session("room-a", lambda: [str(fake_cli)], dict(os.environ), str(fake_cli.parent), model="fable")
        assert second is not first and not first.is_alive() and second.is_alive()
        assert not second.binary_changed()
    finally:
        for s in list(ss._sessions.values()):
            s.stop()


def test_a_running_turn_keeps_its_process_until_it_ends(fake_cli, monkeypatch):
    monkeypatch.setattr(ss, "_sessions", {})
    first = ss.get_or_create_session("room-b", lambda: [str(fake_cli)], dict(os.environ), str(fake_cli.parent), model="fable")
    try:
        first._turn = ss._Turn()            # a turn is running
        _replace(fake_cli)
        assert ss.get_or_create_session("room-b", lambda: [str(fake_cli)], dict(os.environ), str(fake_cli.parent), model="fable") is first
        assert first.is_alive()
        first._turn = None                  # the turn ended
        assert ss.get_or_create_session("room-b", lambda: [str(fake_cli)], dict(os.environ), str(fake_cli.parent), model="fable") is not first
    finally:
        for s in list(ss._sessions.values()):
            s.stop()
