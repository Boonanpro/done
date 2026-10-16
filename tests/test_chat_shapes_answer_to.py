"""The owner's answer to a part (Choice / Input) is an ordinary human message「<問い> → <答え>」 plus the
link to the part it answers, saved as the message's ai_context.answer_to.

What is pinned here (chat_routes / chat_schemas / chat_service / app.agent.chat_shapes):
- the link is strict: exact types, UUID reply id, part-key shape, kind choice|input, limits shared with the
  screen (frontend/src/lib/chat-shapes/schema.ts), nothing coerced or cut
- the server re-derives the screen's part keys (tests/fixtures/chat_shapes_part_keys.json, written by the
  screen's own code) and refuses a link to another room's reply, a missing reply or a part that is not there
- the replace path (re-send after a cancel) is authorized: only the sender's own human message in this room;
  ai_context keeps its other keys, answer_to is replaced or removed
- the SSE echo of the saved message is built from the saved row on every save path (normal, parallel,
  replace, duplicate id)"""
import inspect
import json
import re
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.agent import chat_shapes
from app.api.chat_routes import (
    _AnswerLinkRejected, _answer_to_context, _check_answer_link, _replace_user_message, _user_message_echo,
)
from app.models.chat_schemas import AnswerToLink, MessageSendRequest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def anyio_backend():
    return "asyncio"


FIXTURE = ROOT / "tests" / "fixtures" / "chat_shapes_part_keys.json"
AI_ID = "aaaaaaaa-0000-4000-8000-000000000001"
OWNER, OTHER, ROOM, OTHER_ROOM = "owner-user", "other-user", "room-a", "room-b"
CODE = 'root = Choice("予算", ["5万円", "10万円"])'
FENCE = f"```openui-lang\n{CODE}\n```"


def link(**over):
    base = {"message_id": AI_ID, "part": chat_shapes.part_key(CODE), "kind": "choice", "value": "5万円"}
    base.update(over)
    return base


# --- a small stand-in for the supabase query builder -------------------------------------------------

class _AnyOf(tuple):
    """An in_() filter value: equal to any of the values."""
    def __eq__(self, other):
        return other in tuple(self)

    __hash__ = tuple.__hash__


class FakeDB:
    def __init__(self, tables):
        self.tables = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.calls = []

    def table(self, name):
        return _Query(self, name)


class _Query:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.mode, self.payload = db, name, [], "select", None

    def select(self, *_):
        self.mode = "select"
        return self

    def update(self, payload):
        self.mode, self.payload = "update", payload
        return self

    def insert(self, payload):
        self.mode, self.payload = "insert", payload
        return self

    def delete(self):
        self.mode = "delete"
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def in_(self, key, values):
        self.filters.append((key, _AnyOf(values)))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        rows = self.db.tables.setdefault(self.name, [])
        self.db.calls.append((self.name, self.mode, list(self.filters), self.payload))
        match = [r for r in rows if all(r.get(k) == v for k, v in self.filters)]
        if self.mode == "update":
            for r in match:
                r.update(self.payload)
            return NS(data=[dict(r) for r in match])
        if self.mode == "insert":
            if any(r.get("id") == self.payload.get("id") for r in rows):
                raise Exception("duplicate key value violates unique constraint (23505)")
            row = {"created_at": "2026-10-17T00:00:00+00:00", **self.payload}
            rows.append(row)
            return NS(data=[dict(row)])
        if self.mode == "delete":
            self.db.tables[self.name] = [r for r in rows if r not in match]
            return NS(data=match)
        return NS(data=[dict(r) for r in match])


def db_with_reply(content=FENCE, room=ROOM, sender_type="ai", ai_context=None):
    return FakeDB({"chat_messages": [{"id": AI_ID, "room_id": room, "sender_id": "dan", "sender_type": sender_type,
                                      "content": content, "ai_context": ai_context}]})


# --- the contract --------------------------------------------------------------------------------------

def test_limits_and_key_shape_match_the_screen() -> None:
    """schema.ts and chat_shapes.py carry the same numbers; the link model enforces them without cutting."""
    schema_ts = (ROOT / "frontend/src/lib/chat-shapes/schema.ts").read_text(encoding="utf-8")
    assert int(re.search(r"export const ANSWER_VALUE_MAX = (\d+);", schema_ts).group(1)) == chat_shapes.ANSWER_VALUE_MAX
    assert int(re.search(r"export const ANSWER_QUESTION_MAX = (\d+);", schema_ts).group(1)) == chat_shapes.ANSWER_QUESTION_MAX
    answers_ts = (ROOT / "frontend/src/lib/chat-shapes/answers.ts").read_text(encoding="utf-8")
    assert "toString(16).padStart(8, '0')" in answers_ts   # p + 8 hex digits (+ -ordinal), what PART_KEY_RE accepts
    assert chat_shapes.PART_KEY_RE.match("p0a1b2c3d") and chat_shapes.PART_KEY_RE.match("p0a1b2c3d-2")
    assert not chat_shapes.PART_KEY_RE.match("p0a1b2c3") and not chat_shapes.PART_KEY_RE.match("p0a1b2c3d-0")
    ok = AnswerToLink.model_validate(link(value="v" * chat_shapes.ANSWER_VALUE_MAX, question="q" * chat_shapes.ANSWER_QUESTION_MAX))
    assert len(ok.value) == chat_shapes.ANSWER_VALUE_MAX and len(ok.question) == chat_shapes.ANSWER_QUESTION_MAX
    for too_long in (link(value="v" * (chat_shapes.ANSWER_VALUE_MAX + 1)), link(question="q" * (chat_shapes.ANSWER_QUESTION_MAX + 1))):
        with pytest.raises(ValidationError):
            AnswerToLink.model_validate(too_long)
        assert _answer_to_context(too_long) is None          # never silently cut


def test_link_types_are_strict() -> None:
    """The verifier's cases: 123 is not "123", a list is not a string, a dict is not a string, 0 is not ""."""
    assert _answer_to_context({"message_id": 123, "part": ["p"], "kind": "input", "value": {"bad": 1}}) is None
    assert _answer_to_context({"message_id": "m", "part": "p", "kind": "input", "value": 0}) is None
    assert _answer_to_context(link(message_id=AI_ID.replace("-", ""))) is None    # not a UUID
    assert _answer_to_context(link(part="p")) is None                              # not a part key
    assert _answer_to_context(link(part="P0A1B2C3D")) is None                      # keys are lower-case hex
    assert _answer_to_context(link(kind="other")) is None
    assert _answer_to_context(link(value="")) is None
    assert _answer_to_context(link(value=" ")) == {"answer_to": link(value=" ")}   # length is the screen's concern; emptiness is not
    assert _answer_to_context(link(question="")) is None
    assert _answer_to_context(link(extra="dropped")) is None                       # unknown keys are refused, not dropped
    assert _answer_to_context(None) is None and _answer_to_context("x") is None
    good = _answer_to_context(link(question="予算"))
    assert good == {"answer_to": link(question="予算")}
    assert _answer_to_context(AnswerToLink.model_validate(link())) == {"answer_to": link()}
    assert "question" not in _answer_to_context(link())["answer_to"]


def test_request_model_refuses_a_bad_link_before_the_stream() -> None:
    """A malformed link is a 422 on the request (FastAPI validates MessageSendRequest), not a saved message."""
    req = MessageSendRequest(content="予算 → 5万円", session_id=ROOM, answer_to=link())
    assert isinstance(req.answer_to, AnswerToLink) and req.answer_to.part == chat_shapes.part_key(CODE)
    assert MessageSendRequest(content="hi").answer_to is None
    for bad in ({"message_id": 123, "part": "p", "kind": "input", "value": "x"}, link(value=0), link(value="v" * 999)):
        with pytest.raises(ValidationError):
            MessageSendRequest(content="x", session_id=ROOM, answer_to=bad)
    from app.services.chat_service import ChatService
    assert "ai_context" in inspect.signature(ChatService.send_message).parameters


# --- the server derives the screen's part keys ---------------------------------------------------------

def test_part_keys_match_the_screen_fixture() -> None:
    """tests/fixtures/chat_shapes_part_keys.json is written by split.ts + answers.ts (the screen). The same
    texts must give the same codes and keys here, including HTML comments, CRLF, JS whitespace, surrogates."""
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(cases) >= 15
    for case in cases:
        codes = chat_shapes.shape_codes(case["text"])
        assert codes == case["codes"], case["name"]
        assert chat_shapes.part_keys(codes) == case["keys"], case["name"]
        for key in case["keys"]:
            assert chat_shapes.part_in_reply(case["text"], key), (case["name"], key)
        assert not chat_shapes.part_in_reply(case["text"], "p00000000"), case["name"]
        if case["keys"]:
            assert not chat_shapes.part_in_reply(case["text"], case["keys"][0] + "-9"), case["name"]


def test_check_answer_link_refuses_other_rooms_missing_replies_and_absent_parts() -> None:
    db = db_with_reply()
    service = NS(supabase=db)
    _check_answer_link(service, ROOM, link())                                  # the real part of the real reply: fine
    with pytest.raises(_AnswerLinkRejected):
        _check_answer_link(service, OTHER_ROOM, link())                        # the reply is not in that room
    with pytest.raises(_AnswerLinkRejected):
        _check_answer_link(service, None, link())                              # no room at all
    with pytest.raises(_AnswerLinkRejected):
        _check_answer_link(service, ROOM, link(message_id="bbbbbbbb-0000-4000-8000-000000000002"))   # no such reply
    with pytest.raises(_AnswerLinkRejected):
        _check_answer_link(service, ROOM, link(part=chat_shapes.part_key('root = Choice("x", ["a", "b"])')))   # part not there
    with pytest.raises(_AnswerLinkRejected):
        _check_answer_link(service, ROOM, link(part=chat_shapes.part_key(CODE) + "-1"))   # only one such part
    with pytest.raises(_AnswerLinkRejected):
        _check_answer_link(NS(supabase=db_with_reply(sender_type="human")), ROOM, link())   # the owner's own message is not a reply
    # a reply saved with blocks: a part keyed inside a later text block is found through the blocks too
    blocks = {"blocks": [{"type": "text", "text": "前"}, {"type": "tool", "name": "lookup"}, {"type": "text", "text": FENCE}]}
    _check_answer_link(NS(supabase=db_with_reply(content="前\n" + FENCE, ai_context=blocks)), ROOM, link())


# --- the replace path is authorized and keeps the rest of ai_context -----------------------------------

def _request(**over):
    base = dict(replace_message_id="victim-message", session_id=ROOM, reply_to_id=None, client_message_id=None)
    base.update(over)
    return NS(**base)


def _victim_db(room=ROOM, members=((ROOM, OWNER),)):
    return FakeDB({"chat_room_members": [{"id": f"m-{r}-{u}", "room_id": r, "user_id": u} for r, u in members],
                   "chat_messages": [{"id": "victim-message", "sender_id": OWNER, "sender_type": "human", "room_id": room,
                                      "content": "old", "ai_context": {"answer_to": {"message_id": "old-ai", "part": "old-part", "kind": "input", "value": "old"},
                                                                       "existing": "preserve"}}]})


def test_replace_refuses_another_user_or_room_and_leaves_the_row_alone() -> None:
    """The verifier's foreign_replace: a different user, from their own room, naming the victim's message id; and
    VERIFY3 C: the owner's own row after they left the room (no membership any more)."""
    db = _victim_db(members=((ROOM, OWNER), (ROOM, "different-user"), ("attacker-room", "different-user"), (OTHER_ROOM, OWNER)))
    before = json.dumps(db.tables["chat_messages"], sort_keys=True)
    with pytest.raises(PermissionError):
        _replace_user_message(NS(supabase=db), _request(session_id="attacker-room"), NS(user_id="different-user"), "changed", _answer_to_context(link()), None)
    with pytest.raises(PermissionError):
        _replace_user_message(NS(supabase=db), _request(), NS(user_id="different-user"), "changed", None, None)       # right room, wrong user
    with pytest.raises(PermissionError):
        _replace_user_message(NS(supabase=db), _request(session_id=OTHER_ROOM), NS(user_id=OWNER), "changed", None, None)   # right user, wrong room
    with pytest.raises(PermissionError):
        _replace_user_message(NS(supabase=db), _request(session_id=None), NS(user_id=OWNER), "changed", None, None)
    left = _victim_db(members=())
    with pytest.raises(PermissionError):   # the owner's own row, but they are no longer a member of the room
        _replace_user_message(NS(supabase=left), _request(), NS(user_id=OWNER), "changed", None, None)
    assert all(mode != "update" for _, mode, _, _ in left.calls)
    assert json.dumps(db.tables["chat_messages"], sort_keys=True) == before
    assert all(mode != "update" for _, mode, _, _ in db.calls)
    with pytest.raises(LookupError):   # the row is gone (withdrawn by a cancel): the caller inserts a new row instead
        _replace_user_message(NS(supabase=db), _request(replace_message_id="missing"), NS(user_id=OWNER), "changed", None, None)
    ai_row = FakeDB({"chat_room_members": [{"room_id": ROOM, "user_id": "dan"}],
                     "chat_messages": [{"id": "victim-message", "sender_id": "dan", "sender_type": "ai", "room_id": ROOM, "content": "reply"}]})
    with pytest.raises(PermissionError):   # Dan's reply is never rewritten through this path
        _replace_user_message(NS(supabase=ai_row), _request(), NS(user_id="dan"), "changed", None, None)


def test_replace_by_the_owner_merges_answer_to_and_keeps_other_context() -> None:
    db = _victim_db()
    row = _replace_user_message(NS(supabase=db), _request(), NS(user_id=OWNER), "予算 → 5万円", _answer_to_context(link()), None)
    assert row["content"] == "予算 → 5万円"
    assert row["ai_context"] == {"existing": "preserve", "answer_to": link()}          # new link, other key kept
    update = next(c for c in db.calls if c[1] == "update")
    assert set(update[2]) >= {("id", "victim-message"), ("sender_id", OWNER), ("room_id", ROOM), ("sender_type", "human")}
    # plain text now: the old link goes, the other key stays
    db2 = _victim_db()
    row2 = _replace_user_message(NS(supabase=db2), _request(), NS(user_id=OWNER), "普通の文", None, None)
    assert row2["content"] == "普通の文" and row2["ai_context"] == {"existing": "preserve"}
    # nothing else in ai_context and no link: the column is cleared rather than left as {}
    db3 = _victim_db()
    db3.tables["chat_messages"][0]["ai_context"] = {"answer_to": link()}
    row3 = _replace_user_message(NS(supabase=db3), _request(), NS(user_id=OWNER), "普通の文", None, None)
    assert row3["ai_context"] is None


def test_replace_saves_the_quote_of_the_resend() -> None:
    """VERIFY3 F: the re-sent message replaces the quote too (the validated quote of this request, or none)."""
    db = _victim_db()
    row = _replace_user_message(NS(supabase=db), _request(), NS(user_id=OWNER), "引用つき", None, AI_ID)
    assert row["reply_to"] == AI_ID == db.tables["chat_messages"][0]["reply_to"]
    row2 = _replace_user_message(NS(supabase=db), _request(), NS(user_id=OWNER), "引用なし", None, None)
    assert row2["reply_to"] is None


# --- the echo is the saved row; a re-used id is only ever the sender's own row -------------------------------

def _service(db):
    from app.services.chat_service import ChatService
    svc = ChatService.__new__(ChatService)
    svc.supabase = db
    import logging
    svc.logger = logging.getLogger("test")
    return svc


def _members_db(rows=()):
    return FakeDB({"chat_room_members": [{"id": "m1", "room_id": ROOM, "user_id": OWNER, "role": "owner", "ai_mode": "auto"},
                                         {"id": "m2", "room_id": OTHER_ROOM, "user_id": OTHER, "role": "owner", "ai_mode": "auto"}],
                   "users": [{"id": OWNER, "display_name": "本人"}, {"id": OTHER, "display_name": "他人"}],
                   "chat_messages": list(rows)})


@pytest.mark.anyio
async def test_echo_matches_the_saved_row_on_every_save_path() -> None:
    from app.services.chat_service import ChatService
    quiet = {name: AsyncMock(return_value=None) for name in ("_record_message_delivery", "_trigger_message_detection", "_archive_chat_attachments")}
    with patch.multiple(ChatService, **quiet):
        # normal path: insert with the link → the echo carries the row's ai_context (not the request's)
        db = _members_db()
        svc = _service(db)
        ctx = _answer_to_context(link())
        row = await svc.send_message(ROOM, OWNER, "予算 → 5万円", sender_type="human", message_id="11111111-0000-4000-8000-000000000001", ai_context=ctx)
        echo = _user_message_echo(row, ROOM, None, row.get("sender_name"))
        saved = db.tables["chat_messages"][-1]
        assert echo["id"] == saved["id"] == "11111111-0000-4000-8000-000000000001"
        assert echo["content"] == saved["content"] and echo["ai_context"] == saved["ai_context"] == ctx
        assert echo["sender_id"] == OWNER and echo["sender_type"] == "human" and echo["sender_name"] == "本人"
        assert echo["created_at"] == saved["created_at"] and "_existed" not in row
        # parallel path: the same insert with the arrival time → the echo shows the row's time
        row_p = await svc.send_message(ROOM, OWNER, "予算 → 6万円", sender_type="human", created_at="2026-10-17T01:02:03+00:00",
                                       message_id="11111111-0000-4000-8000-000000000002", ai_context=_answer_to_context(link(value="6万円")))
        echo_p = _user_message_echo(row_p, ROOM, None, None)
        assert echo_p["created_at"] == "2026-10-17T01:02:03+00:00" and echo_p["ai_context"]["answer_to"]["value"] == "6万円"
        # a plain message: no ai_context key in the echo
        row_n = await svc.send_message(ROOM, OWNER, "普通の文", sender_type="human", message_id="11111111-0000-4000-8000-000000000003")
        assert "ai_context" not in _user_message_echo(row_n, ROOM, None, None)
    # replace path: the echo is the re-read row (merged context), with the quote of the row
    db_r = _victim_db()
    db_r.tables["chat_messages"].append({"id": AI_ID, "room_id": ROOM, "sender_id": "dan", "sender_type": "ai", "content": "c" * 300,
                                         "created_at": "2026-10-17T00:00:00+00:00"})
    row_r = _replace_user_message(NS(supabase=db_r), _request(reply_to_id=AI_ID), NS(user_id=OWNER), "予算 → 5万円", _answer_to_context(link()), AI_ID)
    from app.services.chat_service import reply_target_sync
    echo_r = _user_message_echo(row_r, ROOM, reply_target_sync(db_r, ROOM, row_r["reply_to"]), "本人")
    assert echo_r["ai_context"] == db_r.tables["chat_messages"][0]["ai_context"] == {"existing": "preserve", "answer_to": link()}
    assert echo_r["reply_to_id"] == AI_ID == row_r["reply_to"] and echo_r["reply_to_message"]["content"] == "c" * 200
    # the echo never takes a quote that is not the row's
    assert "reply_to_message" not in _user_message_echo(row_r, ROOM, {"id": "something-else", "sender_name": "x", "sender_type": "ai",
                                                                      "content": "x", "created_at": "t"}, "本人")
    # plain replace: the old link is gone from the row and therefore from the echo
    db_r2 = _victim_db()
    row_r2 = _replace_user_message(NS(supabase=db_r2), _request(), NS(user_id=OWNER), "普通の文", None, None)
    assert "answer_to" not in _user_message_echo(row_r2, ROOM, None, None)["ai_context"]


@pytest.mark.anyio
async def test_a_reused_id_returns_only_the_senders_own_row_and_does_nothing_twice() -> None:
    """VERIFY3 A and B on the service: an insert that meets an existing id reads it back only when it is the sender's
    own message in this room (else MessageIdTaken, nothing returned or changed). The same send tried again returns the
    saved row marked _existed, and the counting / feed / detection side effects are not done a second time."""
    from app.services.chat_service import ChatService, MessageIdTaken
    record, detect, archive = AsyncMock(return_value=None), AsyncMock(return_value=None), AsyncMock(return_value=None)
    with patch.multiple(ChatService, _record_message_delivery=record, _trigger_message_detection=detect, _archive_chat_attachments=archive), \
            patch("app.services.room_feed.publish_message") as publish:
        db = _members_db()
        svc = _service(db)
        mid = "11111111-0000-4000-8000-000000000009"
        first = await svc.send_message(ROOM, OWNER, "予算 → 5万円", sender_type="human", message_id=mid, ai_context=_answer_to_context(link()))
        assert "_existed" not in first and record.await_count == detect.await_count == publish.call_count == 1
        again = await svc.send_message(ROOM, OWNER, "予算 → 10万円（届かない）", sender_type="human", message_id=mid, ai_context=None)
        assert again["_existed"] is True and again["content"] == "予算 → 5万円" and again["id"] == mid
        assert record.await_count == detect.await_count == publish.call_count == 1          # nothing done twice
        assert len(db.tables["chat_messages"]) == 1
        before = json.dumps(db.tables["chat_messages"], sort_keys=True)
        with pytest.raises(MessageIdTaken):   # another user, in their own room, naming the owner's message id
            await svc.send_message(OTHER_ROOM, OTHER, "x", sender_type="human", message_id=mid)
        db.tables["chat_room_members"].append({"id": "m3", "room_id": ROOM, "user_id": OTHER})
        with pytest.raises(MessageIdTaken):   # another member of the same room
            await svc.send_message(ROOM, OTHER, "x", sender_type="human", message_id=mid)
        with pytest.raises(MessageIdTaken):   # the same person, as another kind of sender
            await svc.send_message(ROOM, OWNER, "x", sender_type="system", message_id=mid)
        assert json.dumps(db.tables["chat_messages"], sort_keys=True) == before


@pytest.mark.anyio
async def test_a_quote_is_only_ever_a_message_of_the_same_room() -> None:
    """A quote (reply_to) names a message of the same room; an id from another room is not saved, and the list of
    messages never shows the text of a quoted message of another room."""
    from app.services.chat_service import ChatService
    quiet = {name: AsyncMock(return_value=None) for name in ("_record_message_delivery", "_trigger_message_detection", "_archive_chat_attachments")}
    with patch.multiple(ChatService, **quiet):
        db = _members_db([{"id": "secret", "room_id": OTHER_ROOM, "sender_id": OTHER, "sender_type": "human", "content": "他の部屋の秘密",
                           "created_at": "2026-10-17T00:00:00+00:00"},
                          {"id": AI_ID, "room_id": ROOM, "sender_id": "dan", "sender_type": "ai", "content": "ダンの返事",
                           "created_at": "2026-10-17T00:00:01+00:00"}])
        svc = _service(db)
        row = await svc.send_message(ROOM, OWNER, "これに返信", sender_type="human", reply_to_id="secret")
        assert "reply_to" not in row
        row2 = await svc.send_message(ROOM, OWNER, "これに返信", sender_type="human", reply_to_id=AI_ID)
        assert row2["reply_to"] == AI_ID
        # an old row that already points into another room: the list shows the id, never the other room's text
        db.tables["chat_messages"].append({"id": "old", "room_id": ROOM, "sender_id": OWNER, "sender_type": "human", "content": "古い",
                                           "reply_to": "secret", "created_at": "2026-10-17T00:00:02+00:00"})
        listed = svc._get_messages_sync(ROOM, OWNER, 50, None)
        old = next(m for m in listed if m["id"] == "old")
        assert old.get("reply_to_id") == "secret" and "reply_to_message" not in old
        assert "他の部屋の秘密" not in json.dumps(listed, ensure_ascii=False)


def test_was_my_send_saved_answers_only_for_the_senders_own_row() -> None:
    """The screen's "was it saved?" lookup by id: saved only for the caller's own human message in this room."""
    db = _members_db([{"id": "mine", "room_id": ROOM, "sender_id": OWNER, "sender_type": "human", "content": "予算 → 5万円",
                       "ai_context": {"answer_to": link()}, "created_at": "2026-10-17T00:00:00+00:00"},
                      {"id": "theirs", "room_id": OTHER_ROOM, "sender_id": OTHER, "sender_type": "human", "content": "他人",
                       "created_at": "2026-10-17T00:00:00+00:00"}])
    svc = _service(db)
    mine = svc.get_own_message_sync(ROOM, OWNER, "mine")
    assert mine["id"] == "mine" and mine["ai_context"]["answer_to"] == link()
    assert svc.get_own_message_sync(ROOM, OWNER, "theirs") is None      # someone else's id: not shown, not "saved"
    assert svc.get_own_message_sync(ROOM, OWNER, "missing") is None
    with pytest.raises(ValueError):                                     # not a member of that room
        svc.get_own_message_sync(OTHER_ROOM, OWNER, "theirs")


def test_send_stream_route_builds_every_echo_from_the_saved_row() -> None:
    """The route wires the helpers in: the link check and the already-saved check before any save, the replace helper on
    the replace branch, and the echo helper on every echo site with the row's own quote (no echo from the request)."""
    src = (ROOT / "app/api/chat_routes.py").read_text(encoding="utf-8")
    gen = src[src.index("async def send_dan_message_stream"):src.index('@router.post("/dan/read"')]
    assert gen.index("_check_answer_link,") < gen.index("_saved_send,") < gen.index("if request.replace_message_id:") < gen.index("_replace_user_message,")
    assert gen.count("_user_message_echo(") == 4 and gen.count("_reply_for(service") == 4
    assert "request.reply_to_id, message_id" not in gen and "reply_to_id=request.reply_to_id" not in gen
    assert '"sender_name": sender_display_name or "You"' not in gen
    assert "except PermissionError" in gen and "except LookupError" in gen and "except MessageIdTaken" in gen
