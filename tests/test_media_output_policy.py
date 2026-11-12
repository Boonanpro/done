from unittest.mock import patch
from app.tools import browser


def test_inspection_browser_is_silent(tmp_path):
    with patch.object(browser.subprocess, 'Popen') as spawn:
        browser._spawn_detached_browser('/chrome', str(tmp_path), 12345)
    assert '--mute-audio' in spawn.call_args.args[0]


def test_shared_context_requires_muting_native_players(monkeypatch):
    from app.agent import bootstrap_context
    monkeypatch.setattr(bootstrap_context, 'load_bootstrap_file', lambda _: '')
    context = bootstrap_context.load_all_bootstrap_files()
    assert 'Mac mini・Mac・Windows 共通' in context
    assert '実際のミュート状態を読み返す' in context
    assert '本人の画面のプレーヤーを使う' in context
    assert '通話・発信の許可ではない' in context


def test_legacy_worker_is_silent():
    from app.tools import browser_worker
    with patch.object(browser_worker, '_page', None), patch.object(browser_worker, 'sync_playwright') as pw:
        browser_worker.ensure_browser()
        launch = pw.return_value.start.return_value.chromium.launch
        assert '--mute-audio' in launch.call_args.kwargs['args']
