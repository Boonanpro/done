from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.collab_service import CollabService


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
            if self.table_name == "collab_invites":
                row.setdefault("status", "pending")
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
        return [
            row for row in rows
            if all(row.get(field) == value for field, value in self.filters)
        ]


class FakeSupabase:
    def __init__(self):
        self.tables = {
            "chat_room_members": [],
            "collab_rooms": [],
            "collab_invites": [],
            "collab_messages": [],
            "dan_proposals": [],
        }

    def table(self, name):
        return FakeQuery(self, name)


def make_service(fake: FakeSupabase) -> CollabService:
    service = CollabService.__new__(CollabService)
    service.supabase = fake
    import logging
    service.logger = logging.getLogger(__name__)
    return service


@pytest.mark.asyncio
async def test_create_external_thread_links_collab_room_to_origin_chat():
    fake = FakeSupabase()
    fake.tables["chat_room_members"].append({
        "id": "member-1",
        "room_id": "origin-room-1",
        "user_id": "owner-1",
    })
    service = make_service(fake)

    result = await service.create_external_thread(
        owner_id="owner-1",
        origin_room_id="origin-room-1",
        title="田中さんとの連絡",
        description="掲載依頼",
        origin_message_id="origin-msg-1",
        expires_hours=24,
    )

    room = result["room"]
    invite = result["invite"]
    assert room["origin_chat_room_id"] == "origin-room-1"
    assert room["origin_chat_message_id"] == "origin-msg-1"
    assert room["origin_kind"] == "done_chat"
    assert invite["room_id"] == room["id"]
    assert invite["status"] == "pending"


@pytest.mark.asyncio
async def test_guest_message_creates_origin_chat_proposal():
    fake = FakeSupabase()
    fake.tables["collab_rooms"].append({
        "id": "collab-1",
        "owner_id": "owner-1",
        "title": "田中さんとの連絡",
        "origin_chat_room_id": "origin-room-1",
        "origin_chat_message_id": "origin-msg-1",
    })
    service = make_service(fake)

    proposal = await service.notify_origin_chat_of_guest_message(
        "collab-1",
        {
            "id": "collab-msg-1",
            "sender_type": "guest",
            "sender_name": "田中",
            "content": "掲載OKです。",
        },
    )

    assert proposal is not None
    assert proposal["user_id"] == "owner-1"
    assert proposal["source_room_id"] == "origin-room-1"
    assert proposal["source_message_id"] == "origin-msg-1"
    assert proposal["action_data"]["collab_room_id"] == "collab-1"
    assert "掲載OKです" in proposal["content"]


@pytest.mark.asyncio
async def test_owner_message_does_not_create_origin_chat_proposal():
    fake = FakeSupabase()
    fake.tables["collab_rooms"].append({
        "id": "collab-1",
        "owner_id": "owner-1",
        "title": "田中さんとの連絡",
        "origin_chat_room_id": "origin-room-1",
    })
    service = make_service(fake)

    proposal = await service.notify_origin_chat_of_guest_message(
        "collab-1",
        {
            "id": "collab-msg-2",
            "sender_type": "owner",
            "sender_name": "Owner",
            "content": "ありがとうございます。",
        },
    )

    assert proposal is None
    assert fake.tables["dan_proposals"] == []
