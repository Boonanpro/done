"""部屋ログの単一入口（room_log）と core 外からの配信転送（room_feed）。

2026-09-11: 送信案カードが MCP 子プロセスから DB に直接書かれ、core の押し込み
フィードが知らず、画面に出なかった。ここではその経路が塞がっていることを固定する。
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.services import room_feed, room_log


@pytest.fixture(autouse=True)
def _reset_core_flag():
    before = room_feed._IN_CORE
    room_feed._IN_CORE = False
    yield
    room_feed._IN_CORE = before


class _FakeResp:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_sb(inserted: list):
    sb = MagicMock()

    def _insert(row):
        inserted.append(row)
        m = MagicMock()
        m.execute.return_value = MagicMock(data=[{**row, "created_at": "2026-09-11T08:00:00+00:00"}])
        return m

    sb.table.return_value.insert.side_effect = _insert
    return sb


def test_publish_outside_core_forwards_saved_row_to_core():
    sent = {}

    def _urlopen(req, timeout=0):
        sent["url"] = req.full_url
        sent["body"] = json.loads(req.data.decode("utf-8"))
        sent["timeout"] = timeout
        return _FakeResp({"ok": True, "delivered": 2})

    with patch("app.services.room_feed.urllib.request.urlopen", _urlopen):
        n = room_feed.publish_message("room-1", {"id": "m1", "room_id": "room-1", "content": "x"})
    assert n == 2
    assert sent["url"].endswith("/api/v1/chat/internal/rooms/room-1/messages")
    assert sent["body"]["already_saved"] is True
    assert sent["body"]["message"]["id"] == "m1"
    assert 0 < sent["timeout"] <= 5


def test_publish_outside_core_never_raises_when_core_is_down():
    def _urlopen(req, timeout=0):
        raise OSError("connection refused")

    with patch("app.services.room_feed.urllib.request.urlopen", _urlopen):
        assert room_feed.publish_message("room-1", {"id": "m1"}) == 0


def test_publish_inside_core_uses_in_process_bus_and_no_http():
    room_feed.mark_core_process()
    with patch("app.services.room_feed.urllib.request.urlopen") as urlopen, \
         patch("app.services.room_feed._room_members", return_value=["u1"]), \
         patch("app.services.room_feed.publish", return_value=1) as pub, \
         patch("app.services.room_feed.subscriber_count", return_value=1):
        n = room_feed.publish_message("room-1", {"id": "m1", "room_id": "room-1", "sender_type": "ai", "content": "c"})
    assert n == 1
    urlopen.assert_not_called()
    event = pub.call_args.args[1]
    assert event["type"] == "message" and event["message"]["id"] == "m1"
    assert event["message"]["sender_name"] == "ダン"


def test_append_outside_core_delegates_insert_to_core():
    calls = {}

    def _post(path, payload, timeout=5.0):
        calls["path"] = path
        calls["payload"] = payload
        return {"ok": True, "message": {"id": "core-made", "room_id": "room-1", "content": payload["content"]}}

    inserted = []
    with patch("app.services.room_log._post_core", _post), \
         patch("app.services.supabase_client.get_supabase_client", return_value=MagicMock(client=_fake_sb(inserted))):
        row = room_log.append("room-1", "[送信案: abc]")
    assert row["id"] == "core-made"
    assert calls["path"] == "/api/v1/chat/internal/rooms/room-1/messages"
    assert calls["payload"]["sender_type"] == "ai"
    assert inserted == []  # core に委譲したので自分では書かない


def test_append_outside_core_falls_back_to_direct_insert_and_forwards():
    inserted = []
    forwarded = []

    def _post(path, payload, timeout=5.0):
        raise OSError("core down")

    with patch("app.services.room_log._post_core", _post), \
         patch("app.services.supabase_client.get_supabase_client", return_value=MagicMock(client=_fake_sb(inserted))), \
         patch("app.services.chat_service.record_message_delivery_sync"), \
         patch("app.services.room_feed._forward_to_core", lambda rid, msg: forwarded.append((rid, msg)) or 0):
        row = room_log.append("room-1", "[送信案: abc]")
    assert len(inserted) == 1 and inserted[0]["content"] == "[送信案: abc]"
    assert row["id"] == inserted[0]["id"]
    # 直接書いた場合でも配信は core へ転送を試みる
    assert forwarded and forwarded[0][0] == "room-1" and forwarded[0][1]["id"] == row["id"]


def test_append_inside_core_writes_and_publishes_locally():
    room_feed.mark_core_process()
    inserted = []
    published = []
    with patch("app.services.supabase_client.get_supabase_client", return_value=MagicMock(client=_fake_sb(inserted))), \
         patch("app.services.chat_service.record_message_delivery_sync") as rec, \
         patch("app.services.room_feed.publish_message", lambda rid, msg: published.append((rid, msg)) or 1), \
         patch("app.services.room_log._post_core") as post:
        row = room_log.append("room-1", "hello", sender_type="ai")
    post.assert_not_called()
    assert inserted[0]["room_id"] == "room-1" and inserted[0]["sender_type"] == "ai"
    rec.assert_called_once()
    assert published[0][1]["id"] == row["id"]


def test_append_requires_room_id():
    with pytest.raises(ValueError):
        room_log.append("", "x")


def test_outbound_card_post_goes_through_room_log():
    from app.services.outbound_message_service import OutboundMessageService

    svc = OutboundMessageService.__new__(OutboundMessageService)
    svc.sb = MagicMock()
    with patch("app.services.room_log.append") as append:
        svc._post_room_message("room-1", "[送信案: abc]")
    append.assert_called_once_with("room-1", "[送信案: abc]", sender_type="ai", sender_id=None)
    svc.sb.table.assert_not_called()


@pytest.mark.asyncio
async def test_internal_endpoint_rejects_non_loopback_and_publishes_saved_rows():
    from fastapi import HTTPException
    from app.api.chat_routes import internal_room_message

    class _Req:
        def __init__(self, host, payload):
            self.client = MagicMock(host=host)
            self._payload = payload

        async def json(self):
            return self._payload

    with pytest.raises(HTTPException) as exc:
        await internal_room_message("room-1", _Req("10.0.0.5", {"already_saved": True, "message": {"id": "m1"}}))
    assert exc.value.status_code == 403

    with patch("app.services.room_feed.publish_message", return_value=3) as pub:
        out = await internal_room_message("room-1", _Req("127.0.0.1", {"already_saved": True, "message": {"id": "m1"}}))
    assert out == {"ok": True, "saved": False, "delivered": 3}
    pub.assert_called_once()

    with patch("app.services.room_log.append_local", return_value={"id": "m2", "room_id": "room-1", "sender_type": "ai", "content": "c", "created_at": "t"}) as app_local:
        out = await internal_room_message("room-1", _Req("127.0.0.1", {"content": "c"}))
    assert out["saved"] is True and out["message"]["id"] == "m2" and out["message"]["sender_name"] == "ダン"
    app_local.assert_called_once_with("room-1", "c", "ai", None)

    with pytest.raises(HTTPException) as exc:
        await internal_room_message("room-1", _Req("127.0.0.1", {"content": "   "}))
    assert exc.value.status_code == 400
