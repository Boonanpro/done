from unittest.mock import patch
from app.tools import browser


def test_inspection_browser_is_silent(tmp_path):
    with patch.object(browser.subprocess, 'Popen') as spawn:
        browser._spawn_detached_browser('/chrome', str(tmp_path), 12345)
    assert '--mute-audio' in spawn.call_args.args[0]
