"""Typing on a phone whose uiautomator2 input app cannot be installed goes through the clipboard (2026-10-28).
When that app is not on the phone, send_keys is not even tried: installing it stalls on Play Protect (2026-11-21)."""
import pytest

from app.services import phone_control as pc


class Field:
    def __init__(self, calls):
        self.calls = calls

    def clear_text(self, timeout=None):
        self.calls.append(('clear_field',))


class Dev:
    def __init__(self, fail=False, installed=True):
        self.fail, self.installed, self.calls = fail, installed, []

    def __call__(self, **selector):
        assert selector == {'focused': True}
        return Field(self.calls)

    def is_input_ime_installed(self):
        return self.installed

    def send_keys(self, text, clear=False):
        self.calls.append(('send_keys', text, clear))
        if self.fail:
            raise RuntimeError('INSTALL_FAILED_VERIFICATION_FAILURE')

    def clear_text(self):   # goes through the input app; the paste route must not use it
        self.calls.append(('ime_clear',))

    def set_clipboard(self, text):
        self.calls.append(('clip', text))


@pytest.fixture
def adb(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(pc, '_adb', lambda *a, **k: sent.append(a))
    monkeypatch.setattr(pc, '_paste_only', set())
    monkeypatch.setattr(pc, '_PASTE_FILE', tmp_path / 'phone_paste_only.txt')   # never the real list in ~/.dan
    monkeypatch.setattr(pc.time, 'sleep', lambda s: None)
    return sent


def test_send_keys_when_it_works(adb):
    d = Dev()
    pc._send_text(d, 'S1', 'こんにちは')
    assert d.calls == [('send_keys', 'こんにちは', False)] and adb == []


def test_falls_back_to_paste_and_remembers(adb, tmp_path):
    d = Dev(fail=True)
    pc._send_text(d, 'S2', 'チャットワーク', clear=True)
    assert ('clip', 'チャットワーク') in d.calls and ('clear_field',) in d.calls and ('ime_clear',) not in d.calls
    assert adb[-1] == ('S2', 'shell', 'input', 'keyevent', '279')
    assert (tmp_path / 'phone_paste_only.txt').read_text().split() == ['S2']
    d.calls.clear()
    pc._send_text(d, 'S2', '二回目')
    assert d.calls == [('clip', '二回目')]   # the failing install is not tried again


def test_missing_input_app_pastes_without_trying_send_keys(adb):
    d = Dev(installed=False)   # e.g. the S24 when the remembered list lost its serial
    pc._send_text(d, 'RFCXB0MSSTD', '無料相談希望', clear=True)
    assert not any(c[0] in ('send_keys', 'ime_clear') for c in d.calls)
    assert ('clip', '無料相談希望') in d.calls
    assert adb[-1] == ('RFCXB0MSSTD', 'shell', 'input', 'keyevent', '279')


def test_check_failure_counts_as_missing(adb):
    d = Dev()
    d.is_input_ime_installed = lambda: (_ for _ in ()).throw(RuntimeError('adb gone'))
    pc._send_text(d, 'S3', 'abc')
    assert ('send_keys', 'abc', False) not in d.calls and ('clip', 'abc') in d.calls
