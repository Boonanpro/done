from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.external_message_routing import ExternalMessageRoutingService


class FakeQuery:
    def __init__(self, db, table_name: str):
        self.db = db
        self.table_name = table_name
        self.filters: list[tuple[str, object]] = []
        self.insert_row = None
        self.update_data = None
        self.limit_n = None

    def select(self, *_args, **_kwargs):
        return self

    def insert(self, row):
        self.insert_row = dict(row)
        return self

    def update(self, data):
        self.update_data = dict(data)
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, n):
        self.limit_n = n
        return self

    def execute(self):
        rows = self.db.tables.setdefault(self.table_name, [])
        if self.insert_row is not None:
            row = {"id": f"{self.table_name}-{len(rows) + 1}", **self.insert_row}
            rows.append(row)
            return SimpleNamespace(data=[row], count=1)

        if self.update_data is not None:
            matched = self._matched(rows)
            for row in matched:
                row.update(self.update_data)
            return SimpleNamespace(data=matched, count=len(matched))

        matched = self._matched(rows)
        if self.limit_n is not None:
            matched = matched[: self.limit_n]
        return SimpleNamespace(data=matched, count=len(matched))

    def _matched(self, rows):
        out = []
        for row in rows:
            if all(row.get(field) == value for field, value in self.filters):
                out.append(row)
        return out


class FakeSupabase:
    def __init__(self):
        self.tables = {
            "external_message_routes": [],
            "detected_messages": [],
            "dan_proposals": [],
        }

    def table(self, name):
        return FakeQuery(self, name)


def make_service(fake: FakeSupabase) -> ExternalMessageRoutingService:
    service = ExternalMessageRoutingService.__new__(ExternalMessageRoutingService)
    service.supabase = fake
    return service


@pytest.fixture(autouse=True)
def _stub_draft(monkeypatch):
    """メール返信草案の生成は実 CLI を叩かず固定文面にする（高速・決定的）。"""
    import app.agent.cli_runner as cli_runner
    monkeypatch.setattr(cli_runner, "run_oneshot_cli", lambda *a, **k: "（自動生成された返信草案）")


@pytest.mark.asyncio
async def test_routes_detected_message_by_external_thread_id():
    fake = FakeSupabase()
    fake.tables["external_message_routes"].append({
        "id": "route-1",
        "user_id": "user-1",
        "channel": "gmail",
        "external_thread_id": "thread-123",
        "external_message_id": "sent-1",
        "external_recipient_id": "sender@example.com",
        "origin_room_id": "room-1",
        "origin_message_id": "msg-1",
        "last_outbound_at": "2026-06-03T00:00:00Z",
    })
    fake.tables["detected_messages"].append({
        "id": "det-1",
        "user_id": "user-1",
        "source": "gmail",
    })
    service = make_service(fake)

    result = await service.route_detected_message({
        "id": "det-1",
        "user_id": "user-1",
        "source": "gmail",
        "subject": "Re: hello",
        "content": "Thanks",
        "sender_info": {"from": "sender@example.com"},
        "metadata": {"thread_id": "thread-123"},
    })

    assert result is not None
    assert result["route"]["origin_room_id"] == "room-1"
    assert result["reason"] == "external_thread_id"
    assert fake.tables["detected_messages"][0]["routed_room_id"] == "room-1"
    proposal = fake.tables["dan_proposals"][0]
    assert proposal["source_room_id"] == "room-1"
    # gmail 返信は草案付きの reply 提案になる（承認で SMTP 送信）
    assert proposal["type"] == "reply"
    assert proposal["action_data"]["action"] == "send_email_reply"
    assert proposal["action_data"]["channel"] == "email"
    assert proposal["action_data"]["to"] == "sender@example.com"
    assert proposal["action_data"]["detected_message_id"] == "det-1"


@pytest.mark.asyncio
async def test_routes_detected_message_by_routing_key_in_body():
    fake = FakeSupabase()
    fake.tables["external_message_routes"].append({
        "id": "route-2",
        "user_id": "user-1",
        "channel": "line",
        "routing_key": "DK-ABC12345",
        "origin_room_id": "room-2",
        "origin_message_id": None,
        "last_outbound_at": "2026-06-03T00:00:00Z",
    })
    fake.tables["detected_messages"].append({
        "id": "det-2",
        "user_id": "user-1",
        "source": "line",
    })
    service = make_service(fake)

    result = await service.route_detected_message({
        "id": "det-2",
        "user_id": "user-1",
        "source": "line",
        "subject": None,
        "content": "確認しました。お問い合わせID: DK-ABC12345",
        "sender_info": {},
        "metadata": {},
    })

    assert result is not None
    assert result["route"]["origin_room_id"] == "room-2"
    assert result["reason"] == "routing_key"
    assert fake.tables["dan_proposals"][0]["source_room_id"] == "room-2"


@pytest.mark.asyncio
async def test_unmatched_detected_message_does_not_create_proposal():
    fake = FakeSupabase()
    service = make_service(fake)

    result = await service.route_detected_message({
        "id": "det-3",
        "user_id": "user-1",
        "source": "instagram",
        "content": "unrelated",
        "sender_info": {},
        "metadata": {},
    })

    assert result is None
    assert fake.tables["dan_proposals"] == []

