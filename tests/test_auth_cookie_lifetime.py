"""ブラウザの更新用 Cookie がトークンと同じ30日もつこと（2026-10-24: 1日で消えて毎日ログイン画面に戻されていた）。"""
from fastapi import Response

from app.api.chat_routes import REFRESH_TOKEN_COOKIE, set_auth_cookies
from app.config import settings


def _refresh_max_age(response: Response) -> int:
    for name, value in response.raw_headers:
        line = value.decode()
        if name == b"set-cookie" and line.startswith(REFRESH_TOKEN_COOKIE + "="):
            part = next(p for p in line.split(";") if p.strip().lower().startswith("max-age="))
            return int(part.split("=")[1])
    raise AssertionError("refresh cookie not set")


def test_refresh_cookie_lives_as_long_as_token():
    response = Response()
    set_auth_cookies(response, "a", "r", remember_me=True)
    assert _refresh_max_age(response) == settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400


def test_login_and_refresh_routes_keep_cookie_for_30_days():
    import inspect
    from app.api import chat_routes
    for fn in (chat_routes.login, chat_routes.refresh_token_endpoint):
        assert "remember_me=True)" in inspect.getsource(fn).split("set_auth_cookies(")[1].split("\n")[0]
