from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.otp_routes import (
    disable_apk_otp_device,
    forward_apk_sms,
    get_apk_otp_device_status,
    register_apk_otp_device,
)
from app.models.otp_schemas import APKOTPDeviceRegisterRequest, APKOTPForwardRequest
from app.services.auth_service import TokenData


@pytest.fixture
def current_user():
    return TokenData(
        user_id="00000000-0000-0000-0000-000000000001",
        email="owner@example.com",
        exp="2099-01-01T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_register_apk_device_returns_one_time_token(current_user):
    service = AsyncMock()
    service.register_apk_otp_device.return_value = "device-secret"
    with patch("app.api.otp_routes.get_otp_service", return_value=service):
        response = await register_apk_otp_device(
            APKOTPDeviceRegisterRequest(device_name="Pixel"),
            current_user,
        )

    assert response.enabled is True
    assert response.device_token == "device-secret"
    service.register_apk_otp_device.assert_awaited_once()


@pytest.mark.asyncio
async def test_forward_apk_sms_requires_device_token():
    with pytest.raises(HTTPException) as exc:
        await forward_apk_sms(
            APKOTPForwardRequest(sender="Example", body="Your code is 123456"),
            None,
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_forward_apk_sms_accepts_authenticated_device():
    service = AsyncMock()
    service.save_apk_forwarded_sms.return_value = None
    with patch("app.api.otp_routes.get_otp_service", return_value=service):
        response = await forward_apk_sms(
            APKOTPForwardRequest(sender="Example", body="Your code is 123456"),
            "device-secret",
        )

    assert response == {"accepted": True, "otp_detected": False}


@pytest.mark.asyncio
async def test_browser_blocks_direct_login_navigation():
    from app.agent.v2.tools import _execute_browser_tool

    page = AsyncMock()
    with patch("app.tools.browser.get_executor_page", return_value=page):
        result = await _execute_browser_tool("open", {"url": "https://example.com/login"})

    assert result["success"] is False
    assert "open_target" in result["error"]
    page.goto.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_open_target_reuses_destination_first():
    from app.agent.v2.tools import _execute_browser_tool

    page = AsyncMock()
    page.url = "https://example.com/account"
    with (
        patch("app.tools.browser.get_executor_page", return_value=page),
        patch("app.agent.v2.tools._get_browser_state", return_value={"success": True, "content": []}),
    ):
        result = await _execute_browser_tool(
            "open_target",
            {"url": "https://example.com/account"},
        )

    page.goto.assert_awaited_once_with("https://example.com/account")
    assert "Existing browser session was reused" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_browser_blocks_login_link_without_target_redirect():
    from app.agent.v2.tools import _browser_auth_state, _execute_browser_tool

    _browser_auth_state["target_url"] = None
    _browser_auth_state["login_url"] = None
    page = AsyncMock()
    page.url = "https://example.com/login"
    page.get_tab_count.side_effect = [{"count": 1}, {"count": 1}]
    with (
        patch("app.tools.browser.get_executor_page", return_value=page),
        patch("app.agent.v2.tools._get_browser_state", return_value={"success": True, "content": []}),
    ):
        result = await _execute_browser_tool("click", {"ref": "@e1"})

    assert result["success"] is False
    assert "open_target" in result["error"]
    page.go_back.assert_awaited_once()
