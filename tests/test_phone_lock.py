"""Phone lock: the PIN entry runs from this Mac, and nothing here may break the rest of the phone tool."""
from app.services import phone_control


def test_unlocked_phone_is_left_alone(monkeypatch):
    monkeypatch.setattr(phone_control, '_keyguard_locked', lambda serial: False)
    calls = []
    monkeypatch.setattr(phone_control, '_adb', lambda serial, *a, **k: calls.append(a) or '')
    assert phone_control.unlock('SERIAL') is False
    assert calls == []


def test_missing_pin_stays_locked_without_touching_the_phone(monkeypatch):
    monkeypatch.setattr(phone_control, '_keyguard_locked', lambda serial: True)
    monkeypatch.setattr(phone_control, '_stored_pin', lambda: '')
    calls = []
    monkeypatch.setattr(phone_control, '_adb', lambda serial, *a, **k: calls.append(a) or '')
    assert phone_control.unlock('SERIAL') is False
    assert calls == []


def test_ensure_unlocked_swallows_errors(monkeypatch):
    def boom(serial, tries=2):
        raise RuntimeError('no device')
    monkeypatch.setattr(phone_control, 'unlock', boom)
    phone_control._lock_ok.clear()
    phone_control._ensure_unlocked('SERIAL')  # must not raise
