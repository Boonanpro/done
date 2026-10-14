from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from app.services.salonboard_browser_session import (
    LOGIN_URL,
    SalonboardLoginPolicy,
    SalonboardRepeatedLoginBlocked,
    prefill_login_form,
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


class _FakeLocator:
    def __init__(self, page: "_FakePage", selector: str):
        self.page = page
        self.selector = selector

    @property
    def first(self) -> "_FakeLocator":
        return self

    async def count(self) -> int:
        return 0

    async def is_visible(self, timeout: int = 0) -> bool:
        is_login_field = self.selector in ('input[type="text"]', 'input[type="password"]')
        return is_login_field and self.page.url == LOGIN_URL

    async def fill(self, value: str) -> None:
        self.page.filled[self.selector] = value

    async def click(self) -> None:
        self.page.clicked.append(self.selector)

    async def press(self, key: str) -> None:
        self.page.clicked.append(f"{self.selector}:{key}")


class _FakePage:
    def __init__(self, url: str):
        self.url = url
        self.filled: dict[str, str] = {}
        self.clicked: list[str] = []

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self, selector)

    async def goto(self, url: str, **_: object) -> None:
        self.url = url

    async def wait_for_timeout(self, _: int) -> None:
        return None


def test_prefill_login_form_fills_without_submitting() -> None:
    page = _FakePage("https://salonboard.com/somewhere/")

    result = asyncio.run(
        prefill_login_form(page, {"login_id": "id-1", "password": "pw-1"})
    )

    assert result == "prefilled"
    assert page.url == LOGIN_URL
    assert page.filled == {
        'input[type="text"]': "id-1",
        'input[type="password"]': "pw-1",
    }
    assert page.clicked == []


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
