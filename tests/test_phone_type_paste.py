"""Typing on a phone whose uiautomator2 input app cannot be installed goes through the clipboard (2026-10-28)."""
from app.services import phone_control as pc


class Dev:
    def __init__(self, fail):
        self.fail, self.calls = fail, []

    def send_keys(self, text, clear=False):
        self.calls.append(('send_keys', text, clear))
        if self.fail:
            raise RuntimeError('INSTALL_FAILED_VERIFICATION_FAILURE')

    def clear_text(self):
        self.calls.append(('clear',))

    def set_clipboard(self, text):
        self.calls.append(('clip', text))


def test_send_keys_when_it_works(monkeypatch):
    adb = []
    monkeypatch.setattr(pc, '_adb', lambda *a, **k: adb.append(a))
    monkeypatch.setattr(pc, '_paste_only', set())
    d = Dev(fail=False)
    pc._send_text(d, 'S1', 'こんにちは')
    assert d.calls == [('send_keys', 'こんにちは', False)] and adb == []


def test_falls_back_to_paste_and_remembers(monkeypatch):
    adb = []
    monkeypatch.setattr(pc, '_adb', lambda *a, **k: adb.append(a))
    monkeypatch.setattr(pc, '_paste_only', set())
    monkeypatch.setattr(pc.time, 'sleep', lambda s: None)
    d = Dev(fail=True)
    pc._send_text(d, 'S2', 'チャットワーク', clear=True)
    assert ('clip', 'チャットワーク') in d.calls and ('clear',) in d.calls
    assert adb[-1] == ('S2', 'shell', 'input', 'keyevent', '279')
    d.calls.clear()
    pc._send_text(d, 'S2', '二回目')
    assert d.calls == [('clip', '二回目')]   # the failing install is not tried again
