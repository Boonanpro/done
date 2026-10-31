import pytest
from app.services import collab_dan_service as assist


def test_direct_question_reports_unavailable_instead_of_silent_skip(monkeypatch):
    monkeypatch.setattr(assist, '_try_anthropic', lambda *args: None)
    monkeypatch.setattr(assist, '_try_gemini', lambda *args: None)
    with pytest.raises(RuntimeError, match='unavailable'):
        assist.get_dan_response('room', None, [], {'content': 'Help?'}, system_override='Direct question')
    assert assist.get_dan_response('room', None, [], {'content': '明日の予定を調整してください'}) is None


def test_direct_question_uses_available_fallback(monkeypatch):
    monkeypatch.setattr(assist, '_try_anthropic', lambda *args: None)
    monkeypatch.setattr(assist, '_try_gemini', lambda *args: '明日は15時に変更できますか。')
    assert assist.get_dan_response('room', None, [], {'content': 'Help?'}, system_override='Direct question') == '明日は15時に変更できますか。'
