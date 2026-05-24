from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services.salonboard_browser_session import (
    SalonboardLoginPolicy,
    SalonboardRepeatedLoginBlocked,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION_MODULE = Path("app/services/salonboard_browser_session.py")
POLICY_SCRIPT = Path("scripts/check_salonboard_browser_policy.py")
THIS_TEST = Path("tests/test_salonboard_browser_policy.py")


def _tracked_python_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def test_salonboard_login_policy_blocks_repeated_login() -> None:
    policy = SalonboardLoginPolicy(max_login_attempts=1)
    policy.reserve_login_attempt()
    with pytest.raises(SalonboardRepeatedLoginBlocked):
        policy.reserve_login_attempt()


def test_salonboard_browser_login_is_centralized() -> None:
    forbidden = [
        "https://salonboard.com/login/",
        "launch_persistent_context(",
    ]

    violations: list[str] = []
    for path in _tracked_python_files():
        if path in {SESSION_MODULE, POLICY_SCRIPT, THIS_TEST}:
            continue
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        if "salonboard" not in text.lower():
            continue
        for needle in forbidden:
            if needle in text:
                violations.append(f"{path}: direct use of {needle!r}")

    assert violations == []
