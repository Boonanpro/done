"""The sandbox gets its own process group on POSIX: stop() ends it with killpg, and a sandbox left in the core's group
took the core down with every sandbox restart (2026-10-27, Mac)."""
import subprocess
import sys

import pytest

from app.core import sandbox_manager as sm


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_spawn_starts_its_own_session(tmp_path, monkeypatch):
    seen = {}

    class FakeProc:
        pid = 4242

    def fake_popen(cmd, **kw):
        seen.update(kw)
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    m = sm.SandboxManager(port=18999, cwd=tmp_path, log_path=tmp_path / "sandbox.log")
    assert m._spawn().pid == 4242
    assert seen.get("start_new_session") is True
