from pathlib import Path
from types import SimpleNamespace
import pytest
from app.services import lifelog
from scripts import lifelog_worker as worker
from scripts.recover_lifelog import recover


@pytest.fixture
def audio(tmp_path, monkeypatch):
    monkeypatch.setattr(lifelog, 'AUDIO_ROOT', tmp_path / 'audio')
    monkeypatch.setattr(lifelog, 'INDEX_ROOT', tmp_path / 'index')
    monkeypatch.setattr(worker, 'LOG', tmp_path / 'worker.log')
    p = lifelog.AUDIO_ROOT / '2026-10-30' / '123456_000_owner.ogg'
    p.parent.mkdir(parents=True)
    p.write_bytes(b'original')
    return p


class Model:
    def transcribe(self, *a, **kw):
        return [SimpleNamespace(start=0, end=1, text='会議は明日')], SimpleNamespace(duration=1)


def test_storage_failure_remains_pending_and_recovers(audio, monkeypatch):
    completed, retries = set(), {}
    original = Path.write_text
    def fail(p, *a, **kw):
        if p.name.endswith('.json.tmp'):
            raise OSError('NAS offline')
        return original(p, *a, **kw)
    with monkeypatch.context() as m:
        m.setattr(Path, 'write_text', fail)
        worker.run_pass(Model(), completed, retries)
    assert not completed and str(audio) in retries
    assert audio.read_bytes() == b'original'
    retries.clear()
    worker.run_pass(Model(), completed, retries)
    assert str(audio) in completed
    assert lifelog.read_day('2026-10-30')[0]['text'] == '会議は明日'


def test_index_recovery_deduplicates(audio):
    worker.process_audio(audio, Model())
    worker.process_audio(audio, Model())
    assert len(lifelog.read_day('2026-10-30')) == 1
    lifelog.index_file('2026-10-30').unlink()
    worker.process_audio(audio, None)
    assert len(lifelog.read_day('2026-10-30')) == 1


def test_recovery_preserves_sources_and_detects_conflicts(tmp_path):
    root = tmp_path / 'release'
    src = root / 'windows-dan-lifelog' / '2026-10-30' / 'a.ogg'
    src.parent.mkdir(parents=True); src.write_bytes(b'a')
    target = tmp_path / 'permanent'
    assert recover([root], target) == 1
    assert recover([root], target) == 0
    assert src.read_bytes() == b'a'
    src.write_bytes(b'b')
    with pytest.raises(RuntimeError): recover([root], target)
