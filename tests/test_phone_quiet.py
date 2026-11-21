"""Dan's phone calls turn the media volume to 0 first; sound=True brings back the level from before (2026-11-21)."""
from app.services import phone_control as pc


def test_quiet_mutes_then_sound_restores(monkeypatch):
    state = {'v': 6}
    def adb(serial, *args, **kw):
        if '--get' in args:
            return f"volume is {state['v']} in range [0..15]"
        if '--set' in args:
            state['v'] = int(args[-1])
        return ''
    monkeypatch.setattr(pc, '_adb', adb)
    pc._media_before.clear()
    pc._quiet('X')
    assert state['v'] == 0 and pc._media_before['X'] == 6
    pc._quiet('X')                      # already quiet: the remembered level stays
    assert pc._media_before['X'] == 6
    pc._quiet('X', sound=True)
    assert state['v'] == 6
    pc._quiet('X')
    assert state['v'] == 0


def test_quiet_never_breaks_the_call(monkeypatch):
    def boom(*a, **k):
        raise OSError('adb gone')
    monkeypatch.setattr(pc, '_adb', boom)
    pc._quiet('X')
