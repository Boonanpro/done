"""A maintenance restart must be able to respect the owner's test stop."""
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock
import sys


def test_health_only_never_starts_a_job(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location('verify_health_check', Path(__file__).parents[1] / 'scripts/verify_dan.py')
    module = importlib.util.module_from_spec(spec)
    # The CLI changes stdout encoding at import time.
    class Output:
        def reconfigure(self, **kwargs): pass
    with monkeypatch.context() as patch:
        patch.setattr(sys, 'stdout', Output())
        spec.loader.exec_module(module)
    monkeypatch.setattr(sys, 'argv', ['verify_dan.py', '--health-only'])
    monkeypatch.setattr(module, 'health', lambda: [])
    job = AsyncMock()
    monkeypatch.setattr(module, 'voice_work', job)
    module.main()
    job.assert_not_called()
    assert 'work path not tested' in capsys.readouterr().out
