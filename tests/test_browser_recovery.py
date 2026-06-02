import json
from pathlib import Path
from unittest.mock import patch

from app.tools import browser


def test_process_scan_returns_only_dedicated_profile_browser(tmp_path):
    profile = tmp_path / "browser_data"
    rows = [
        {
            "ProcessId": 101,
            "ParentProcessId": 1,
            "Name": "chrome.exe",
            "CommandLine": rf'chrome.exe --user-data-dir="{profile}"',
        },
        {
            "ProcessId": 202,
            "ParentProcessId": 1,
            "Name": "chrome.exe",
            "CommandLine": r'chrome.exe --user-data-dir="C:\Users\Owner\AppData\Local\Google\Chrome\User Data"',
        },
        {
            "ProcessId": 303,
            "ParentProcessId": 1,
            "Name": "headless_shell.exe",
            "CommandLine": rf'headless_shell.exe --user-data-dir="{profile}"',
        },
    ]
    completed = type("Completed", (), {"stdout": json.dumps(rows)})()

    with (
        patch.object(browser, "_executor_profile_dir", return_value=profile),
        patch.object(browser.subprocess, "run", return_value=completed),
    ):
        processes, scan_ok = browser._list_dedicated_browser_processes()

    assert scan_ok is True
    assert processes == [
        {"pid": 101, "parent_pid": 1, "name": "chrome.exe"},
        {"pid": 303, "parent_pid": 1, "name": "headless_shell.exe"},
    ]


def test_recovery_does_nothing_when_cdp_is_available(tmp_path):
    profile = tmp_path / "browser_data"
    profile.mkdir()
    lock = profile / "lockfile"
    lock.touch()

    with (
        patch.object(browser, "_executor_profile_dir", return_value=profile),
        patch.object(browser, "_is_executor_cdp_available", return_value=True),
        patch.object(browser, "_list_dedicated_browser_processes", return_value=([], True)),
        patch.object(browser, "_write_browser_recovery_log"),
    ):
        recovered = browser._recover_stale_executor_profile()

    assert recovered is False
    assert lock.exists()


def test_recovery_removes_stale_lock_when_no_dedicated_browser_exists(tmp_path):
    profile = tmp_path / "browser_data"
    profile.mkdir()
    lock = profile / "lockfile"
    lock.touch()

    with (
        patch.object(browser, "_executor_profile_dir", return_value=profile),
        patch.object(browser, "_is_executor_cdp_available", return_value=False),
        patch.object(browser, "_list_dedicated_browser_processes", return_value=([], True)),
        patch.object(browser, "_write_browser_recovery_log"),
    ):
        recovered = browser._recover_stale_executor_profile()

    assert recovered is True
    assert not lock.exists()


def test_recovery_terminates_only_verified_dedicated_browser_then_removes_lock(tmp_path):
    profile = tmp_path / "browser_data"
    profile.mkdir()
    lock = profile / "lockfile"
    lock.touch()
    dedicated = [{"pid": 303, "parent_pid": 1, "name": "chrome.exe"}]

    with (
        patch.object(browser, "_executor_profile_dir", return_value=profile),
        patch.object(browser, "_is_executor_cdp_available", return_value=False),
        patch.object(
            browser,
            "_list_dedicated_browser_processes",
            side_effect=[(dedicated, True), ([], True)],
        ),
        patch.object(
            browser,
            "_terminate_dedicated_browser_processes",
            return_value=[303],
        ) as terminate,
        patch.object(browser.time, "sleep"),
        patch.object(browser, "_write_browser_recovery_log"),
    ):
        recovered = browser._recover_stale_executor_profile()

    assert recovered is True
    terminate.assert_called_once_with(dedicated)
    assert not lock.exists()


def test_recovery_keeps_lock_when_process_scan_fails(tmp_path):
    profile = tmp_path / "browser_data"
    profile.mkdir()
    lock = profile / "lockfile"
    lock.touch()

    with (
        patch.object(browser, "_executor_profile_dir", return_value=profile),
        patch.object(browser, "_is_executor_cdp_available", return_value=False),
        patch.object(browser, "_list_dedicated_browser_processes", return_value=([], False)),
        patch.object(browser, "_write_browser_recovery_log"),
    ):
        recovered = browser._recover_stale_executor_profile()

    assert recovered is False
    assert lock.exists()
