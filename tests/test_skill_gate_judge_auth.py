"""スキルの関所の判定役は、ダン本体と同じ長く使える鍵で起動する（2026-10-25: 保管庫のログインが切れて判定できなかった）。"""
import importlib.util
import json
import os
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_gate():
    spec = importlib.util.spec_from_file_location("hook_skill_gate", ROOT / "scripts" / "hook_skill_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake_claude(tmp_path):
    """渡された鍵の有無を答えとして返す偽の claude。"""
    exe = tmp_path / "bin" / "claude"
    exe.parent.mkdir()
    exe.write_text("#!/bin/sh\ncat >/dev/null\n"
                   "if [ -n \"$CLAUDE_CODE_OAUTH_TOKEN\" ]; then P=true; else P=false; fi\n"
                   "printf '{\"result\": \"{\\\\\"pass\\\\\": %s, \\\\\"problems\\\\\": []}\"}' $P\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


def test_judge_gets_the_token_from_the_dan_file(tmp_path, monkeypatch):
    fake_claude(tmp_path)
    home = tmp_path / "home"
    (home / ".dan").mkdir(parents=True)
    (home / ".dan" / "claude_oauth_token").write_text("tok-123\n")
    monkeypatch.setenv("PATH", str(tmp_path / "bin") + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    gate = load_gate()
    ok, why, keep = gate._judge("## 見本\n- 種類: 操作")
    assert ok is True and keep is True, why


def test_judge_without_any_token_is_not_passed(tmp_path, monkeypatch):
    fake_claude(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path / "bin") + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("HOME", str(tmp_path / "empty"))
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    ok, _, _ = load_gate()._judge("## 見本\n- 種類: 操作")
    assert ok is False
