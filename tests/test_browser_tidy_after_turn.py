"""After Dan answers, its browser keeps only the tab it worked on and leaves the owner's screen (2026-10-16).

Checked against a real Chrome when written (launch off screen, a screenshot off screen, hold shows, release hides,
tidy keeps one tab); here the rule itself runs against a recorded browser.
"""
import asyncio

import pytest

from app.services import browser_lifecycle as bl


class FakeBrowser:
    def __init__(self, tabs):
        self.tabs = list(tabs)
        self.calls = []

    async def call(self, method, **params):
        self.calls.append((method, params))
        if method == "Target.getTargets":
            return {"targetInfos": [{"targetId": t, "type": "page"} for t in self.tabs]}
        if method == "Browser.getWindowForTarget":
            return {"windowId": 1}
        if method == "Target.closeTarget":
            self.tabs.remove(params["targetId"])
        return {}


@pytest.fixture
def room(tmp_path, monkeypatch):
    profile = tmp_path / "browser_data--room"
    profile.mkdir()
    fake = FakeBrowser(["a", "b", "c"])
    monkeypatch.setattr(bl, "profile_for_room", lambda room_id: profile)
    monkeypatch.setattr(bl, "_saved_port", lambda p: 51000)
    monkeypatch.setattr(bl, "_cdp_ready", lambda port: True)
    monkeypatch.setattr(bl, "_owns_port", lambda p, port: True)
    monkeypatch.setattr(bl, "_with_cdp", lambda port, work: asyncio.run(work(fake.call)))
    monkeypatch.setattr("app.tools.browser._write_browser_recovery_log", lambda *a, **k: None)
    return profile, fake


def test_keeps_the_working_tab_closes_the_rest_and_leaves_the_screen(room):
    profile, fake = room
    (profile / bl.CURRENT_TAB_FILE).write_text("b", encoding="utf-8")
    result = bl.tidy_after_turn("room")
    assert fake.tabs == ["b"] and result["tabs_closed"] == 2
    moved = [p["bounds"] for m, p in fake.calls if m == "Browser.setWindowBounds" and "left" in p["bounds"]]
    assert moved == [{"left": bl.OFF_SCREEN[0], "top": bl.OFF_SCREEN[1]}]


def test_a_browser_handed_to_the_owner_is_left_alone(room):
    profile, fake = room
    (profile / bl.CURRENT_TAB_FILE).write_text("b", encoding="utf-8")
    (profile / bl.STATE_FILE).write_text('{"holds": {"user": "sign in"}}', encoding="utf-8")
    assert bl.tidy_after_turn("room")["skipped"] == "held"
    assert fake.tabs == ["a", "b", "c"] and fake.calls == []


def test_without_a_known_working_tab_no_tab_is_closed(room):
    profile, fake = room
    bl.tidy_after_turn("room")
    assert fake.tabs == ["a", "b", "c"]
    assert any(m == "Browser.setWindowBounds" for m, _ in fake.calls)


def test_dan_browsers_open_off_the_screen(monkeypatch):
    from app.tools import browser
    launched = []
    monkeypatch.setattr(browser.subprocess, "Popen", lambda args, **kw: launched.append(args))
    browser._spawn_detached_browser("chrome.exe", "C:/profile", 51000)
    assert f"--window-position={bl.OFF_SCREEN[0]},{bl.OFF_SCREEN[1]}" in launched[0]
