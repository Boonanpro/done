from app.services import voice_parts, voice_settings, voice_live, voice_responses
import pytest


def test_status_includes_evidence_after_stale_progress():
    result = voice_parts.work_status([{'id': 'j', 'state': 'running', 'events': [
        {'kind': 'progress', 'text': '依頼内容を確認しています', 'at': '2026-10-27T08:20:11Z'},
        {'kind': 'tool', 'text': 'desktop', 'at': '2026-10-27T08:22:51Z'}],
        'current_tool': {'name': 'desktop', 'started_at': '2026-10-27T08:23:00Z'},
        'last_observation': {'text': 'URL: https://example.com/invoice\nタイトル: 請求書', 'at': '2026-10-27T08:22:50Z'}}])
    row = result['work_status'][0]
    assert row['最後の進捗説明']['時刻'] == '2026-10-27T08:20:11Z'
    assert row['直近の操作履歴'][-1]['text'] == 'desktop'
    assert row['実行中の操作']['name'] == 'desktop'
    assert '請求書' in row['最後に読んだ画面']['text']


def test_next_call_reads_settings_without_mutating_existing_call(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_settings, 'PATH', tmp_path / 'settings.json')
    monkeypatch.setattr(voice_responses, 'remembered', lambda: '')
    monkeypatch.setattr(voice_responses, 'catalog', lambda: '')
    voice_settings.save({'backend_model': 'model-one', 'reasoning': 'low'})
    first = voice_live.session_config()
    voice_settings.save({'backend_model': 'model-two', 'reasoning': 'high'})
    second = voice_live.session_config()
    assert first['delegation']['responses']['model'] == 'model-one'
    assert second['delegation']['responses']['model'] == 'model-two'
    assert first['delegation']['responses']['reasoning']['effort'] == 'low'


def test_invalid_setting_preserves_previous_file(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_settings, 'PATH', tmp_path / 'settings.json')
    voice_settings.save({'reasoning': 'medium'})
    with pytest.raises(ValueError):
        voice_settings.save({'reasoning': 'anything'})
    assert voice_settings.snapshot()['reasoning'] == 'medium'
