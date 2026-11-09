"""A Windows build copied onto the Mac must not be run (it failed every timeline edit)."""
import os
from app.services import timeline_commands as tc, timeline_context as tcx


def test_exe_is_not_runnable_off_windows(tmp_path, monkeypatch):
    exe = tmp_path / 'native_ui.exe'; exe.write_bytes(b'MZ'); exe.chmod(0o755)
    assert tcx.native_runnable(str(exe)) is (os.name == 'nt')
    assert not tcx.native_runnable('')
    monkeypatch.setenv('NATIVE_UI_EXE', str(exe))
    seq = {'tracks': [{'id': 'v', 'type': 'video', 'clips': [
        {'id': 'a', 'text': 'x', 'timeline_start': 0, 'timeline_end': 1}]}]}
    problems = tc.validate_sequence(seq, {}, asset_dir=str(tmp_path))
    if os.name != 'nt':
        assert not any('native validator unavailable' in p for p in problems), problems
