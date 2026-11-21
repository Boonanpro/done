"""開発室を開き直す時の読み方（11-21 本人「開発室のページをリフレッシュした時の読み込みが遅すぎる」）:
絵をファイルとして返して控えさせる /media と、会話の印をまとめて返す /rooms/pulse。"""
import base64
from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import dan_notion_routes as routes
from app.services.auth_service import TokenData

USER = "00000000-0000-0000-0000-000000000001"
PNG = b"\x89PNG\r\n\x1a\nfake"
TOKEN = lambda: TokenData(user_id=USER, email="t@example.com", exp=datetime.now() + timedelta(hours=1))


class _Svc:
    def get_block(self, user_id, block_id):
        if block_id == "pic":
            return {"id": block_id, "properties": {"image": {"hash": "h1", "data": "data:image/png;base64," + base64.b64encode(PNG).decode()}}}
        if block_id == "plain":
            return {"id": block_id, "properties": {"thread": {}}}
        return None


def _notion(monkeypatch):
    app = FastAPI(); app.include_router(routes.router)
    app.dependency_overrides[routes.get_current_user] = TOKEN
    monkeypatch.setattr(routes, "_svc", lambda: _Svc())
    return TestClient(app)


def test_media_returns_the_picture_kept_a_year_when_hash_matches(monkeypatch):
    r = _notion(monkeypatch).get("/dan-notion/blocks/pic/media?h=h1")
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "private, max-age=31536000, immutable"


def test_media_with_an_old_hash_is_not_kept(monkeypatch):
    r = _notion(monkeypatch).get("/dan-notion/blocks/pic/media?h=old")
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-cache"


def test_media_without_picture_is_404(monkeypatch):
    c = _notion(monkeypatch)
    assert c.get("/dan-notion/blocks/plain/media").status_code == 404
    assert c.get("/dan-notion/blocks/none/media").status_code == 404


def test_rooms_pulse_answers_every_room_in_one_call(monkeypatch):
    from app.api import chat_routes
    from app.services import parallel_job_runner as runner

    class Chat:
        async def get_messages(self, room_id, user_id, limit=50, before=None):
            if room_id == "secret":
                raise ValueError("not a member")
            return [{"id": f"{room_id}-m{i}", "room_id": room_id, "sender_type": "ai", "content": "x", "created_at": "2026-11-21T00:00:00+00:00"} for i in range(limit)]

    async def active(room_id):
        return {"active": room_id == "a", "started_at": None}

    monkeypatch.setattr(chat_routes, "_active_session_status", active)
    monkeypatch.setattr(chat_routes, "_message_responses", lambda rows: [SimpleNamespace(model_dump=lambda mode=None, r=r: r) for r in rows])
    monkeypatch.setattr(runner, "rooms_jobs", lambda user_id, room_ids, hours, quiet: {r: [{"id": "j-" + r}] for r in room_ids})
    monkeypatch.setattr(runner, "public", lambda s: {"id": s["id"], "active": True})
    app = FastAPI(); app.include_router(chat_routes.router)
    app.dependency_overrides[chat_routes.get_current_user] = TOKEN
    app.dependency_overrides[chat_routes.get_chat_service] = lambda: Chat()
    r = TestClient(app).post(chat_routes.router.prefix + "/rooms/pulse", json={"room_ids": ["a", "b", "secret", "a"], "limit": 3}).json()
    rooms = r["rooms"]
    assert set(rooms) == {"a", "b", "secret"}
    assert rooms["a"]["active"]["active"] is True and rooms["b"]["active"]["active"] is False
    assert len(rooms["a"]["messages"]) == 3 and rooms["b"]["jobs"] == [{"id": "j-b", "active": True}]
    assert rooms["secret"] == {"error": "forbidden"}
