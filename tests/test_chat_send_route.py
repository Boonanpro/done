"""The real send route (chat_routes.send_dan_message_stream) and the real ChatService.send_message over HTTP
(FastAPI TestClient), with an in-memory database and no model: the owner's message is saved, refused or returned
as already saved exactly as the rules say. Only outside effects are replaced (no model turn is started: the
room is treated as busy so a send is queued as a follow-up; feed / delivery / detection are stubbed).

Pinned here (VERIFY3 A, B, C, F and the earlier refusals):
- a client_message_id that is someone else's / another room's row is refused (never returned, never changed)
- the same answer sent again with the same id returns the saved row and starts nothing (no second row, no turn)
- the rewrite after a cancel needs membership of the room, like a new message
- the quote is a message of the same room; the echo's quote is the saved row's quote
- "was my send saved?" answers saved only for the caller's own human message in that room"""
import importlib.util
import json
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

from app.agent.chat_shapes import part_key
from app.api import chat_routes as cr
from app.services.chat_service import ChatService

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("answer_to_fixtures", ROOT / "tests" / "test_chat_shapes_answer_to.py")
fx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fx)

USER = "1f53bb2a-51da-4a2a-be9e-4c5a0f74d5f1"
OTHER = "22222222-0000-4000-8000-000000000001"
ROOM = "b2c3d4e5-0000-4000-8000-000000000002"
ROOM2 = "bbbbbbbb-0000-4000-8000-000000000002"
AI = "aaaaaaaa-0000-4000-8000-000000000001"
AI2 = "aaaaaaaa-0000-4000-8000-000000000002"
MID = "11111111-0000-4000-8000-000000000001"
NEW = "33333333-0000-4000-8000-000000000003"
CODE = 'root = Choice("Q", ["A", "B"])'
FENCE = "```openui-lang\n" + CODE + "\n```"


def link(**kw):
    return {"message_id": AI, "part": part_key(CODE), "kind": "choice", "value": "A", **kw}


@pytest.fixture
def env():
    state = {}

    def reset(members=((ROOM, USER), (ROOM2, OTHER))):
        state["db"] = fx.FakeDB({
            "projects": [],
            "users": [{"id": USER, "display_name": "dan-test"}, {"id": OTHER, "display_name": "other-test"}],
            "chat_room_members": [{"id": f"m{i}", "room_id": r, "user_id": u} for i, (r, u) in enumerate(members)],
            "chat_messages": [
                {"id": AI, "room_id": ROOM, "sender_type": "ai", "sender_id": "dan", "content": FENCE, "created_at": "2026-10-17T00:00:00Z"},
                {"id": AI2, "room_id": ROOM2, "sender_type": "ai", "sender_id": "dan", "content": "他の部屋の返事", "created_at": "2026-10-17T00:00:00Z"},
                {"id": MID, "room_id": ROOM, "sender_type": "human", "sender_id": USER, "content": "old", "created_at": "2026-10-17T00:00:01Z",
                 "ai_context": {"other": "preserve", "answer_to": {**link(), "value": "B"}}},
            ]})
        svc = fx._service(state["db"])
        svc.get_user_by_id = AsyncMock(return_value={"display_name": "dan-test"})
        state["svc"] = svc
        return state["db"]

    app = FastAPI()
    app.add_api_route("/api/v1/chat/dan/messages/stream", cr.send_dan_message_stream, methods=["POST"])
    app.add_api_route("/api/v1/chat/rooms/{room_id}/messages/{message_id}/saved", cr.get_message_saved, methods=["GET"])

    def user(x_test_user: str = Header(default=USER)):
        return NS(user_id=x_test_user)

    app.dependency_overrides[cr.get_current_user] = user
    app.dependency_overrides[cr.get_chat_service] = lambda: state["svc"]
    followups = []
    with ExitStack() as s:
        s.enter_context(patch("app.services.project_service.ProjectService", side_effect=lambda: NS(supabase=state["db"])))
        s.enter_context(patch("app.agent.streaming_session.streaming_enabled", return_value=True))
        s.enter_context(patch("app.agent.streaming_session.submit_room_followup", side_effect=lambda *a, **k: followups.append(a) or "queued"))
        s.enter_context(patch("app.agent.turn_flow.waits_for_running_turn", return_value=True))
        s.enter_context(patch("app.services.voice_calls.active", return_value=None))
        s.enter_context(patch("app.services.room_feed.publish_message"))
        s.enter_context(patch.object(cr, "_write_latency_log"))
        for name in ("_record_message_delivery", "_trigger_message_detection", "_archive_chat_attachments"):
            s.enter_context(patch.object(ChatService, name, new_callable=AsyncMock))
        client = s.enter_context(TestClient(app))

        def send(body, user_id=USER):
            req = {"content": "Q → A", "session_id": ROOM, "client_message_id": NEW, **body}
            r = client.post("/api/v1/chat/dan/messages/stream", json=req, headers={"x-test-user": user_id})
            events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
            return r.status_code, events

        def saved(room, mid, user_id=USER):
            r = client.get(f"/api/v1/chat/rooms/{room}/messages/{mid}/saved", headers={"x-test-user": user_id})
            return r.status_code, (r.json() if r.status_code == 200 else None)

        yield NS(reset=reset, send=send, saved=saved, state=state, followups=followups)


def types(events):
    return [e["type"] for e in events]


def rows(env):
    return json.loads(json.dumps(env.state["db"].tables["chat_messages"]))


def test_a_foreign_client_message_id_is_refused_and_never_echoed(env) -> None:
    env.reset()
    before = rows(env)
    status, events = env.send({"session_id": ROOM2, "client_message_id": MID}, OTHER)   # VERIFY3 A: the victim's id from the attacker's own room
    assert status == 200 and types(events) == ["error", "done"]
    assert "old" not in json.dumps(events, ensure_ascii=False) and rows(env) == before and not env.followups


def test_the_same_answer_sent_again_returns_the_saved_row_and_starts_nothing(env) -> None:
    env.reset()
    status, events = env.send({"answer_to": link()})
    assert types(events) == ["user_message", "followup_queued", "done"] and len(env.followups) == 1
    first = events[0]["message"]
    n = len(rows(env))
    # the screen did not get the echo and sends the same answer again with the same id (or another option):
    status, again = env.send({"answer_to": link(value="B"), "content": "Q → B"})
    assert types(again) == ["user_message", "done"]                     # no second turn
    assert again[0]["message"]["id"] == first["id"] == NEW and again[0]["message"]["content"] == "Q → A"
    assert again[0]["message"]["ai_context"] == first["ai_context"] and len(rows(env)) == n and len(env.followups) == 1


def test_a_plain_send_that_meets_its_own_saved_id_does_not_start_a_second_turn(env) -> None:
    """The race after the "already saved?" check: the insert meets the row saved meanwhile (the service marks it)."""
    env.reset()
    env.send({"content": "ふつうの文"})
    status, again = env.send({"content": "ふつうの文"})
    assert types(again) == ["user_message", "done"] and len(env.followups) == 1
    assert sum(1 for r in rows(env) if r["id"] == NEW) == 1


def test_rewrite_after_cancel_needs_membership_of_the_room(env) -> None:
    env.reset(members=((ROOM2, OTHER),))   # VERIFY3 C: the owner's own row, after they left the room
    before = rows(env)
    status, events = env.send({"replace_message_id": MID, "content": "changed"})
    assert types(events) == ["error", "done"] and rows(env) == before
    env.reset()
    status, events = env.send({"replace_message_id": MID, "content": "changed"})    # still a member: rewritten
    assert types(events)[0] == "user_message" and next(r for r in rows(env) if r["id"] == MID)["content"] == "changed"


def test_the_echo_quote_is_the_saved_quote_and_quotes_stay_in_the_room(env) -> None:
    env.reset()
    status, events = env.send({"replace_message_id": MID, "reply_to_id": AI, "content": "plain"})   # VERIFY3 F
    row = next(r for r in rows(env) if r["id"] == MID)
    echo = events[0]["message"]
    assert row["reply_to"] == AI == echo["reply_to_id"] and echo["reply_to_message"]["id"] == AI
    status, events = env.send({"replace_message_id": MID, "content": "plain again"})                  # the re-send has no quote now
    row = next(r for r in rows(env) if r["id"] == MID)
    assert row["reply_to"] is None and "reply_to_id" not in events[0]["message"]
    env.reset()
    status, events = env.send({"reply_to_id": AI2, "content": "これに返信"})                         # a quote into another room
    echo = events[0]["message"]
    assert "reply_to_id" not in echo and "他の部屋の返事" not in json.dumps(events, ensure_ascii=False)
    assert "reply_to" not in next(r for r in rows(env) if r["id"] == NEW)


def test_was_my_send_saved(env) -> None:
    env.reset()
    assert env.saved(ROOM, NEW) == (200, {"saved": False})
    env.send({"answer_to": link()})
    status, body = env.saved(ROOM, NEW)
    assert status == 200 and body["saved"] is True and body["message"]["id"] == NEW and body["message"]["ai_context"]["answer_to"]["value"] == "A"
    assert env.saved(ROOM, AI) == (200, {"saved": False})               # not the caller's own human message
    assert env.saved(ROOM2, NEW, OTHER) == (200, {"saved": False})      # another user asking for it from their room
    assert env.saved(ROOM, NEW, OTHER)[0] == 403                        # not a member of that room


def test_a_non_member_is_refused_before_anything_is_read_or_started(env) -> None:
    """Writing in a room is for its members, checked first: someone outside the room learns nothing from the answer
    checks (whether a reply / a part / a message id exists there) and starts nothing in that room."""
    env.reset()
    before = rows(env)
    for body in ({"answer_to": link()},                                  # a real part of that room's reply
                 {"answer_to": link(part="pffffffff")},                  # a part that is not there
                 {"answer_to": {**link(), "message_id": "99999999-0000-4000-8000-000000000009"}},   # a reply that is not there
                 {"answer_to": link(), "client_message_id": MID},        # an id that is someone's saved message there
                 {"content": "ふつうの文"}):
        status, events = env.send(body, OTHER)                            # OTHER is not a member of ROOM
        assert types(events) == ["error", "done"] and events[0]["message"] == "この部屋には書き込めません", body
    assert rows(env) == before and not env.followups


def test_stopping_is_for_the_members_of_the_room() -> None:
    """/dan/cancel acts on the room's running turn (kills its CLI, pauses its runs, clears queued follow-ups): only a
    member of that room may do it. A failing membership lookup still lets the owner stop (stopping comes first)."""
    db = fx.FakeDB({"chat_room_members": [{"id": "m0", "room_id": ROOM, "user_id": USER}], "chat_messages": [], "execution_events": []})
    app = FastAPI()
    app.add_api_route("/api/v1/chat/dan/cancel", cr.cancel_dan_session, methods=["POST"])

    def user(x_test_user: str = Header(default=USER)):
        return NS(user_id=x_test_user)

    app.dependency_overrides[cr.get_current_user] = user
    killed = []
    runs = NS(get_current_run_for_room=AsyncMock(return_value=None), pause_active_runs_for_room=AsyncMock(return_value=0))
    with patch.object(cr, "ChatService", lambda: NS(supabase=db)), \
            patch("app.agent.cli_runner.kill_cli_process", side_effect=lambda room, **k: killed.append(room) or False), \
            patch("app.agent.cli_runner.is_cli_active", return_value=False), \
            patch("app.agent.streaming_session.streaming_enabled", return_value=False), \
            patch("app.services.run_service.RunService", lambda: runs), \
            patch("app.tools.browser.abort_executor_session"), TestClient(app) as client:
        r = client.post("/api/v1/chat/dan/cancel", json={"session_id": ROOM}, headers={"x-test-user": OTHER})
        assert r.status_code == 403 and killed == [] and runs.pause_active_runs_for_room.await_count == 0
        r = client.post("/api/v1/chat/dan/cancel", json={"session_id": ROOM}, headers={"x-test-user": USER})
        assert r.status_code == 200 and killed == [ROOM]
        with patch("app.services.chat_service.member_of_room_sync", side_effect=RuntimeError("db down")):
            r = client.post("/api/v1/chat/dan/cancel", json={"session_id": ROOM}, headers={"x-test-user": USER})
        assert r.status_code == 200 and killed == [ROOM, ROOM]


def test_the_earlier_refusals_still_hold(env) -> None:
    env.reset()
    before = rows(env)
    assert types(env.send({"answer_to": link(part="pffffffff")})[1]) == ["error", "done"]                 # a part that is not there
    assert types(env.send({"session_id": ROOM2, "answer_to": link()}, OTHER)[1]) == ["error", "done"]     # a reply of another room
    assert env.send({"answer_to": link(value=0)})[0] == 422                                              # wrong type
    assert types(env.send({"replace_message_id": MID, "content": "x"}, OTHER)[1]) == ["error", "done"]  # someone else's row
    assert rows(env) == before
