from types import SimpleNamespace
from datetime import timedelta
import pytest
from fastapi import HTTPException

from app.services import native_editor_auth as native
from app.services.auth_service import decode_access_token, decode_refresh_token, create_access_token, refresh_tokens


def test_desktop_login_can_refresh_after_access_expiry(tmp_path, monkeypatch):
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    user = SimpleNamespace(user_id='desktop-test', email='desktop@example.test')
    access = native.prepare_login(user)
    folder = tmp_path / '.done'
    assert (folder / 'native_token.txt').read_text() == access
    refresh = (folder / 'native_refresh_token.txt').read_text()
    assert decode_access_token(access).user_id == user.user_id
    assert decode_refresh_token(refresh).user_id == user.user_id
    expired = create_access_token(user.user_id, user.email, timedelta(seconds=-1))
    assert decode_access_token(expired) is None
    renewed = refresh_tokens(refresh)
    assert decode_access_token(renewed.access_token).user_id == user.user_id
    assert refresh_tokens(expired) is None


def test_sandbox_refresh_endpoint_rejects_access_token_and_renews_refresh():
    from app.api.editor_assistant_routes import refresh_login, RefreshLogin
    from app.services.auth_service import create_refresh_token
    access = create_access_token('test', 'test@example.test')
    with pytest.raises(HTTPException) as error:
        refresh_login(RefreshLogin(refresh_token=access))
    assert error.value.status_code == 401
    result = refresh_login(RefreshLogin(refresh_token=create_refresh_token('test', 'test@example.test')))
    assert decode_access_token(result['access_token']).user_id == 'test'
