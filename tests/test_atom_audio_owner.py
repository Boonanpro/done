import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('atom_audio_owner', Path(__file__).resolve().parents[1] / 'devices/atom-echo-s3r/audio_owner.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_phone_ownership_survives_bridge_restart(tmp_path):
    path=tmp_path/'owner.json'
    owner=module.AudioOwner(path)
    assert owner.mode=='pc'
    owner.select('phone',busy=False)
    assert module.AudioOwner(path).mode=='phone'
    owner.select('phone',busy=True)  # Idempotent lookup does not interrupt a call.
    with pytest.raises(RuntimeError): owner.select('pc',busy=True)
    assert module.AudioOwner(path).mode=='phone'
    owner.select('pc',busy=False)
    assert module.AudioOwner(path).mode=='pc'


def test_busy_or_bad_owner_never_changes_state(tmp_path):
    path=tmp_path/'owner.json'
    owner=module.AudioOwner(path)
    with pytest.raises(RuntimeError):owner.select('phone',busy=True)
    with pytest.raises(ValueError):owner.select('unknown',busy=False)
    assert not path.exists() and owner.mode=='pc'
    path.write_text('{"mode":"broken"}')
    with pytest.raises(ValueError):module.AudioOwner(path)
