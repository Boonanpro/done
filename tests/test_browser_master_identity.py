from unittest.mock import AsyncMock
import pytest
from app.tools import browser
from app.services import owner

@pytest.mark.parametrize("user", ["test-user", "", None])
def test_other_user_never_copies_owner_storage(tmp_path, monkeypatch, user):
    master = tmp_path / "master"
    (master / "Default/Local Storage").mkdir(parents=True)
    (master / "Default/Local Storage/session").write_text("owner session")
    monkeypatch.setattr(browser, "_master_profile_dir", lambda: master)
    monkeypatch.setattr(owner, "resolve_owner_user_id", lambda: "owner")
    if user is None:
        monkeypatch.delenv("DAN_USER_ID", raising=False)
    else:
        monkeypatch.setenv("DAN_USER_ID", user)
    target = tmp_path / "test-profile"
    browser._seed_profile_from_master(target)
    assert not target.exists()

@pytest.mark.asyncio
async def test_cookie_fallback_cannot_copy_owner_login(monkeypatch):
    monkeypatch.setenv("DAN_USER_ID", "test-user")
    monkeypatch.setattr(owner, "resolve_owner_user_id", lambda: "owner")
    fetch = AsyncMock(return_value=[{"name":"session", "value":"owner"}])
    monkeypatch.setattr(browser, "_fetch_master_cookies_raw", fetch)
    monkeypatch.setattr(browser, "_pending_cookie_import", True)
    context = AsyncMock()
    await browser._import_master_cookies(context)
    fetch.assert_not_called()
    context.add_cookies.assert_not_called()
    assert not browser._pending_cookie_import

def test_owner_still_can_reuse_master_login(monkeypatch):
    monkeypatch.setenv("DAN_USER_ID", "owner")
    monkeypatch.setattr(owner, "resolve_owner_user_id", lambda: "owner")
    assert browser._may_use_master_login()

def test_unresolved_owner_does_not_grant_access(monkeypatch):
    monkeypatch.setenv("DAN_USER_ID", "test-user")
    monkeypatch.setattr(owner, "resolve_owner_user_id", lambda: None)
    assert not browser._may_use_master_login()
