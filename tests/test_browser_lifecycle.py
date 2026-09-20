import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI

from app.services import browser_lifecycle as lifecycle
from app.tools import browser


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(lifecycle.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(lifecycle, "_core_token", "test-token-" * 4)
    monkeypatch.setattr(lifecycle, "_cdp_ready", lambda port: bool(port))
    monkeypatch.setattr(lifecycle, "_owns_port", lambda profile, port: bool(port))
    monkeypatch.setattr(browser, "_port_listening", lambda port: bool(port))
    monkeypatch.setattr(browser, "_write_browser_recovery_log", Mock())
    return tmp_path


def make_profile(room):
    profile = lifecycle.profile_for_room(room)
    profile.mkdir(parents=True, exist_ok=True)
    (profile / browser._PORT_FILE_NAME).write_text("54321", encoding="utf-8")
    (profile / browser._LAST_USE_FILE_NAME).write_text(str(time.time() - 7200), encoding="utf-8")
    return profile


def test_user_hold_survives_process_memory_reset_and_idle_cleanup(isolated, monkeypatch):
    held = make_profile("waiting-room")
    unused = make_profile("finished-room")
    result = lifecycle.manage_session("hold", "waiting-room", "Waiting for login")
    assert result["state"] == "held"
    lifecycle._locks.clear()  # The state must not depend on in-process memory.
    (held / browser._LAST_USE_FILE_NAME).write_text("1", encoding="utf-8")
    close = Mock(return_value=(True, True))
    monkeypatch.setattr(lifecycle, "_close_profile", close)
    closed = lifecycle.reap_idle(1800, set())
    assert [row["profile"] for row in closed] == [unused.name]
    close.assert_called_once_with(unused, 54321)
    assert lifecycle.manage_session("status", "waiting-room")["holds"]["user"] == "Waiting for login"


def test_release_keeps_browser_open_and_restarts_idle_grace(isolated, monkeypatch):
    profile = make_profile("room")
    lifecycle.manage_session("hold", "room")
    close = Mock(return_value=(True, True))
    monkeypatch.setattr(lifecycle, "_close_profile", close)
    result = lifecycle.manage_session("release", "room")
    assert result["state"] == "open" and result["holds"] == {}
    assert lifecycle.reap_idle(1800, set()) == []
    close.assert_not_called()
    (profile / browser._LAST_USE_FILE_NAME).write_text("1", encoding="utf-8")
    assert len(lifecycle.reap_idle(1800, set())) == 1


def test_auth_release_does_not_release_user_hold(isolated):
    make_profile("room")
    lifecycle.manage_session("hold_auth", "room")
    lifecycle.manage_session("hold", "room", "User is entering data")
    result = lifecycle.manage_session("release_auth", "room")
    assert result["holds"] == {"user": "User is entering data"}


def test_failed_close_preserves_hold(isolated, monkeypatch):
    make_profile("room")
    lifecycle.manage_session("hold", "room")
    monkeypatch.setattr(lifecycle, "_close_profile", lambda *_: (False, False))
    with pytest.raises(RuntimeError, match="hold state was preserved"):
        lifecycle.manage_session("close", "room")
    assert lifecycle.is_held(lifecycle.profile_for_room("room"))


def test_status_does_not_launch_and_hold_does_not_claim_dead_browser(isolated, monkeypatch):
    spawn = Mock()
    monkeypatch.setattr(browser, "_spawn_detached_browser", spawn)
    assert lifecycle.manage_session("status", "never-opened")["state"] == "closed"
    with pytest.raises(RuntimeError, match="No live browser"):
        lifecycle.manage_session("hold", "never-opened")
    spawn.assert_not_called()


def test_watch_and_damaged_hold_state_fail_closed(isolated, monkeypatch):
    watched = make_profile("watch")
    damaged = make_profile("damaged")
    (damaged / lifecycle.STATE_FILE).write_text("{broken", encoding="utf-8")
    close = Mock()
    monkeypatch.setattr(lifecycle, "_close_profile", close)
    assert lifecycle.reap_idle(1800, {watched.name}) == []
    close.assert_not_called()


def test_cleanup_skips_when_watch_database_unavailable(monkeypatch):
    from app.services import followups
    monkeypatch.setattr(followups, "held_room_ids", Mock(side_effect=RuntimeError("offline")))
    reap = Mock()
    monkeypatch.setattr(lifecycle, "reap_idle", reap)
    assert asyncio.run(browser.close_idle_browsers()) == []
    reap.assert_not_called()


def test_same_room_ensure_is_serialized(isolated, monkeypatch):
    active = 0
    peak = 0

    def ensure(room, profile):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        profile.mkdir(parents=True, exist_ok=True)
        time.sleep(.03)
        active -= 1
        return 54321

    monkeypatch.setattr(lifecycle, "_ensure_browser", ensure)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: lifecycle.manage_session("ensure", "same"), range(2)))
    assert peak == 1
    assert all(result["port"] == 54321 for result in results)


def test_room_paths_are_confined_and_distinct(isolated):
    assert lifecycle.profile_for_room("../a/b").parent == isolated / ".ai_secretary"
    assert lifecycle.profile_for_room("a/b") != lifecycle.profile_for_room("ab")


def test_stale_port_cannot_close_another_rooms_browser(isolated, monkeypatch):
    profile = make_profile("old-room")
    monkeypatch.setattr(lifecycle, "_owns_port", lambda *_: False)
    graceful = AsyncMock()
    monkeypatch.setattr(browser, "_graceful_close_cdp", graceful)
    assert lifecycle._close_profile(profile, 54321) == (True, True)
    graceful.assert_not_called()
    assert lifecycle.manage_session("status", "old-room")["state"] == "closed"


def test_unavailable_core_never_falls_back_to_local_spawn(isolated, monkeypatch):
    monkeypatch.setenv("DAN_SESSION_ID", "test-room")
    monkeypatch.setattr(browser, "_seed_profile_from_master", lambda *_: None)
    monkeypatch.setattr(lifecycle, "request_session", Mock(side_effect=RuntimeError("Core offline")))
    spawn = Mock()
    monkeypatch.setattr(browser, "_spawn_detached_browser", spawn)
    pw = Mock(stop=AsyncMock())
    from playwright import async_api
    monkeypatch.setattr(async_api, "async_playwright", lambda: Mock(start=AsyncMock(return_value=pw)))
    with pytest.raises(RuntimeError, match="Core offline"):
        asyncio.run(browser._executor_worker())
    spawn.assert_not_called()
    assert "Core offline" in browser._executor_start_error


def test_login_observation_automatically_holds_browser(isolated, monkeypatch):
    from app.agent.v2 import tools
    make_profile("auth-room")
    monkeypatch.setattr(browser, "_browser_room_id", lambda: "auth-room")
    monkeypatch.setattr(lifecycle, "request_session", lifecycle.manage_session)
    page = Mock()
    page.url = "https://example.test/login"
    page.wait_for_load_state = AsyncMock()
    page.screenshot_base64 = AsyncMock(return_value=None)
    page.get_interactive_elements = AsyncMock(return_value=[{"type": "password"}])
    page.get_page_context = AsyncMock(return_value={})
    page.evaluate = AsyncMock(return_value="Login")
    result = asyncio.run(tools._get_browser_state_impl(page))
    assert result["browser_session"]["state"] == "held"
    assert lifecycle.is_held(lifecycle.profile_for_room("auth-room"))


def test_lifecycle_tool_does_not_create_a_page(isolated, monkeypatch):
    from app.agent.v2 import tools
    make_profile("tool-room")
    monkeypatch.setattr(browser, "_browser_room_id", lambda: "tool-room")
    monkeypatch.setattr(lifecycle, "request_session", lifecycle.manage_session)
    get_page = AsyncMock()
    monkeypatch.setattr(browser, "get_executor_page", get_page)
    result = asyncio.run(tools._execute_browser_tool_impl("hold", {"reason": "User input"}))
    assert result["state"] == "held"
    assert json.loads(result["content"][0]["text"])["alive"]
    result = asyncio.run(tools._execute_browser_tool_impl("release", {}))
    assert result["state"] == "open"
    get_page.assert_not_called()


@pytest.mark.parametrize("host,token,origin,expected", [
    ("127.0.0.1", "test-token-" * 4, None, 200),
    ("127.0.0.1", "bad", None, 403),
    ("192.0.2.1", "test-token-" * 4, None, 403),
    ("127.0.0.1", "test-token-" * 4, "https://external.example", 403),
])
def test_manager_route_authentication(isolated, host, token, origin, expected):
    from app.core.api.browser_routes import router
    app = FastAPI()
    app.include_router(router)

    async def run():
        headers = {"X-Dan-Browser-Token": token}
        if origin:
            headers["Origin"] = origin
        transport = httpx.ASGITransport(app=app, client=(host, 1234))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/internal/browser/session", headers=headers,
                                     json={"room_id": "room", "operation": "status"})

    assert asyncio.run(run()).status_code == expected
