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
from app.services.chat_service import ChatService, clear_send_rights

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
        # each scenario starts like a fresh Core: no send rights, tombstones or running-work senders from before
        clear_send_rights()
        cr._cancel_tombstones.clear()
        cr._room_work_senders.clear()
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


def _cancel_client(db, killed, runs):
    app = FastAPI()
    app.add_api_route("/api/v1/chat/dan/cancel", cr.cancel_dan_session, methods=["POST"])

    def user(x_test_user: str = Header(default=USER)):
        return NS(user_id=x_test_user)

    app.dependency_overrides[cr.get_current_user] = user
    s = ExitStack()
    s.enter_context(patch.object(cr, "ChatService", lambda: NS(supabase=db)))
    s.enter_context(patch("app.agent.cli_runner.kill_cli_process", side_effect=lambda room, **k: killed.append(room) or False))
    s.enter_context(patch("app.agent.cli_runner.is_cli_active", return_value=False))
    s.enter_context(patch("app.agent.streaming_session.streaming_enabled", return_value=False))
    s.enter_context(patch("app.services.run_service.RunService", lambda: runs))
    s.enter_context(patch("app.tools.browser.abort_executor_session"))
    return s, s.enter_context(TestClient(app))


def test_stopping_is_for_the_members_of_the_room() -> None:
    """/dan/cancel acts on the room's running turn (kills its CLI, pauses its runs, clears queued follow-ups): only a
    member of that room may do it. When the membership lookup fails, only someone known without the database may stop:
    the one who started the work running in that room now (VERIFY4 P2-2). Anyone else gets 503 and nothing is touched."""
    from app.services.cancellation import CancellationRegistry
    db = fx.FakeDB({"chat_room_members": [{"id": "m0", "room_id": ROOM, "user_id": USER}], "chat_messages": [], "execution_events": []})
    killed = []
    runs = NS(get_current_run_for_room=AsyncMock(return_value=None), pause_active_runs_for_room=AsyncMock(return_value=0))
    cr._room_work_senders.clear()
    s, client = _cancel_client(db, killed, runs)
    with s:
        r = client.post("/api/v1/chat/dan/cancel", json={"session_id": ROOM}, headers={"x-test-user": OTHER})
        assert r.status_code == 403 and killed == [] and runs.pause_active_runs_for_room.await_count == 0
        r = client.post("/api/v1/chat/dan/cancel", json={"session_id": ROOM}, headers={"x-test-user": USER})
        assert r.status_code == 200 and killed == [ROOM]
        with patch("app.services.chat_service.member_of_room_sync", side_effect=RuntimeError("db down")):
            # nobody is known to run anything here: neither the stranger nor the member is taken for a member
            for who in (OTHER, USER):
                r = client.post("/api/v1/chat/dan/cancel", json={"session_id": ROOM}, headers={"x-test-user": who})
                assert r.status_code == 503 and killed == [ROOM] and runs.pause_active_runs_for_room.await_count == 1
            # the owner's turn is running in this room (they sent it through the send route): the owner may stop it,
            # the stranger still may not
            CancellationRegistry.register(ROOM)
            cr._note_room_work_sender(ROOM, USER)
            try:
                r = client.post("/api/v1/chat/dan/cancel", json={"session_id": ROOM}, headers={"x-test-user": OTHER})
                assert r.status_code == 503 and killed == [ROOM]
                r = client.post("/api/v1/chat/dan/cancel", json={"session_id": ROOM}, headers={"x-test-user": USER})
                assert r.status_code == 200 and killed == [ROOM, ROOM]
                # the work is over (the flag is down): the old record alone proves nothing
                CancellationRegistry.unregister(ROOM)
                r = client.post("/api/v1/chat/dan/cancel", json={"session_id": ROOM}, headers={"x-test-user": USER})
                assert r.status_code == 503 and killed == [ROOM, ROOM]
            finally:
                CancellationRegistry.unregister(ROOM)
                cr._room_work_senders.clear()


def test_a_tombstone_only_removes_the_requesters_own_row(env) -> None:
    """VERIFY4 P2-3: the late delete (tombstone) checks room, sender and human like the direct delete. Another member
    naming the owner's message id arms nothing that can remove the owner's row later; the owner's own cancel of a send
    that was not saved yet still removes it when its save lands."""
    db = env.reset(members=((ROOM, USER), (ROOM, OTHER)))
    killed = []
    runs = NS(get_current_run_for_room=AsyncMock(return_value=None), pause_active_runs_for_room=AsyncMock(return_value=0))
    s, client = _cancel_client(db, killed, runs)
    with s:
        r = client.post("/api/v1/chat/dan/cancel", json={"session_id": ROOM, "cancelled_user_message_id": MID}, headers={"x-test-user": OTHER})
        assert r.status_code == 200 and any(r["id"] == MID for r in rows(env))     # the direct delete is the owner's rows only
    status, events = env.send({"client_message_id": MID, "content": "old"})          # the owner's same send again
    assert types(events)[0] == "user_message" and any(r["id"] == MID for r in rows(env))   # still there
    # the owner cancels a send before its save lands, then the save lands: removed (and only that row)
    later = "44444444-0000-4000-8000-000000000004"
    s, client = _cancel_client(db, killed, runs)
    with s:
        r = client.post("/api/v1/chat/dan/cancel", json={"session_id": ROOM, "cancelled_user_message_id": later}, headers={"x-test-user": USER})
        assert r.status_code == 200 and r.json()["deleted_user_message"] is False
    status, events = env.send({"client_message_id": later, "content": "取り消した文"})
    assert not any(r["id"] == later for r in rows(env)) and any(r["id"] == MID for r in rows(env))


def test_one_send_starts_dan_once_even_when_a_transient_error_and_a_retry_overlap(env) -> None:
    """VERIFY4 P2-1: the first request's insert fails before reaching the database; while it waits to retry, the same
    answer arrives again and is saved and started. The first request's retry meets the saved row: it starts nothing
    (the start right is taken once per send id, not guessed from the attempt count) and does not count it again."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    env.reset()
    failed = threading.Event()
    orig = fx._Query.execute

    def execute(q):
        if q.name == "chat_messages" and q.mode == "insert" and q.payload.get("id") == NEW and not failed.is_set():
            failed.set()
            raise RuntimeError("connection reset before insert reached database")
        return orig(q)

    with patch.object(fx._Query, "execute", execute), ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(env.send, {"answer_to": link()})
        assert failed.wait(10)
        second = env.send({"answer_to": link()})
        first = first.result(10)
    assert len(env.followups) == 1 and sum(1 for r in rows(env) if r["id"] == NEW) == 1
    assert sorted([types(first[1]), types(second[1])]) == [["user_message", "done"], ["user_message", "followup_queued", "done"]]
    assert ChatService._record_message_delivery.await_count == 1   # counted once


def test_a_lost_insert_response_still_starts_the_send(env) -> None:
    """The recovery the attempt count used to give: the insert landed but its response was lost, so this request's
    retry meets its own row. Nobody else started it, so this request takes the right and starts it."""
    env.reset()
    orig = fx._Query.execute
    lost = {"n": 0}

    def execute(q):
        out = orig(q)
        if q.name == "chat_messages" and q.mode == "insert" and q.payload.get("id") == NEW and not lost["n"]:
            lost["n"] += 1
            raise RuntimeError("connection reset after the insert reached the database")
        return out

    with patch.object(fx._Query, "execute", execute):
        status, events = env.send({"answer_to": link()})
    assert types(events) == ["user_message", "followup_queued", "done"] and len(env.followups) == 1
    assert sum(1 for r in rows(env) if r["id"] == NEW) == 1 and ChatService._record_message_delivery.await_count == 1


def test_a_saved_send_that_nothing_started_is_started_by_its_retry(env) -> None:
    """Saved, but the request that saved it ended before starting anything (it gave the start right back): "was it
    saved?" says started: false, and the same send again starts it, once."""
    from app.services.chat_service import begin_send_right, give_back_send_right, take_send_right
    env.reset()
    # the first request saves and takes the right, then ends before starting (cut): its finally gives the right back
    right = take_send_right("start", ROOM, NEW)
    env.state["db"].tables["chat_messages"].append({"id": NEW, "room_id": ROOM, "sender_type": "human", "sender_id": USER, "content": "Q → A",
                                                    "created_at": "2026-10-17T00:00:02Z", "ai_context": {"answer_to": link()}})
    assert env.saved(ROOM, NEW)[1]["started"] is None            # a request is about to start it: nothing to do
    give_back_send_right("start", ROOM, NEW, right["token"])
    assert env.saved(ROOM, NEW)[1]["started"] is False           # saved, nothing started it
    status, events = env.send({"answer_to": link()})
    assert types(events) == ["user_message", "followup_queued", "done"] and len(env.followups) == 1
    assert events[0]["message"]["id"] == NEW and sum(1 for r in rows(env) if r["id"] == NEW) == 1
    assert env.saved(ROOM, NEW)[1]["started"] is True
    status, again = env.send({"answer_to": link()})               # and only once
    assert types(again) == ["user_message", "done"] and len(env.followups) == 1
    assert begin_send_right("start", ROOM, NEW, right["token"]) is False   # the old holder can never start it now


def test_a_send_saved_before_this_request_is_not_started_again_unless_it_was_given_back(env) -> None:
    """A row that was already there when the request came (the first insert met it, or the answer was found saved): this
    Core starts it only if a request here took its start right and gave it back. If this Core never saw it (saved before a
    restart, say), whether it started is unknown, so it is not started — by this request or any later one."""
    env.reset()
    db = env.state["db"]
    db.tables["chat_messages"].append({"id": NEW, "room_id": ROOM, "sender_type": "human", "sender_id": USER, "content": "Q → A",
                                       "created_at": "2026-10-17T00:00:02Z", "ai_context": {"answer_to": link()}})
    for body in ({"answer_to": link()}, {"answer_to": link()}, {"content": "Q → A"}, {"content": "Q → A"}):
        status, events = env.send(body)
        assert types(events) == ["user_message", "done"] and not env.followups and events[0]["message"]["id"] == NEW
    status, events = env.send({"client_message_id": MID, "content": "old"})        # an ordinary row from before, sent again
    assert types(events) == ["user_message", "done"] and not env.followups and len(rows(env)) == 4


def test_a_row_created_again_under_a_used_id_is_a_new_send(env) -> None:
    """The start right is once per send id while that send's row exists. When the row is gone (deleted) and a request
    creates a new row under the same id, what the earlier send finished with does not apply: the new row is started.
    While the row is there, the same id starts nothing more."""
    env.reset()
    env.send({"content": "ふつうの文"})
    assert len(env.followups) == 1
    env.send({"content": "ふつうの文"})                          # same send again, row still there
    assert len(env.followups) == 1
    env.state["db"].tables["chat_messages"] = [r for r in env.state["db"].tables["chat_messages"] if r["id"] != NEW]
    status, events = env.send({"content": "別の文"})            # a new row under the same id
    assert types(events) == ["user_message", "followup_queued", "done"] and len(env.followups) == 2


def test_rights_a_live_request_holds_are_never_forgotten() -> None:
    """forget_finished_send_rights (a request created the row) drops only what is finished: the "saved" right once done,
    the "start" right once given back or begun by a holder whose row was saved. A taken right, or one begun by the
    parallel branch before its row is saved, belongs to a live request of the same send and is kept."""
    from app.services.chat_service import (begin_send_right, forget_finished_send_rights, give_back_send_right,
                                           note_send_right_row_saved, send_right_state, take_send_right)
    clear_send_rights()
    r = take_send_right("start", ROOM, NEW)
    forget_finished_send_rights(ROOM, NEW)
    assert send_right_state("start", ROOM, NEW) == "taken"                 # live holder
    begin_send_right("start", ROOM, NEW, r["token"])
    forget_finished_send_rights(ROOM, NEW)
    assert send_right_state("start", ROOM, NEW) == "begun"                 # began before saving its row (parallel branch)
    note_send_right_row_saved("start", ROOM, NEW, r["token"])
    forget_finished_send_rights(ROOM, NEW)
    assert send_right_state("start", ROOM, NEW) is None                    # its row was saved and is gone now
    r = take_send_right("start", ROOM, NEW)
    give_back_send_right("start", ROOM, NEW, r["token"])
    forget_finished_send_rights(ROOM, NEW)
    assert send_right_state("start", ROOM, NEW) is None
    clear_send_rights()


def test_a_right_held_too_long_is_handed_over_once() -> None:
    """A request that took the start right and neither began nor gave it back for SEND_RIGHT_ABANDONED seconds (stopped
    where its clean-up does not run) counts as having given it back: "was it saved?" says started: false, the next
    request of the same send takes it, and the old holder can no longer begin (only one token ever begins)."""
    from app.services import chat_service as cs
    clear_send_rights()
    now = [1000.0]
    with patch.object(cs.time, "time", lambda: now[0]):
        old = cs.take_send_right("start", ROOM, NEW)
        assert cs.take_send_right("start", ROOM, NEW) is None and cs.send_right_state("start", ROOM, NEW) == "taken"
        now[0] += cs.SEND_RIGHT_ABANDONED + 1
        assert cs.send_right_state("start", ROOM, NEW) == "returned"
        new = cs.take_send_right("start", ROOM, NEW)
        assert new is not None and new["returned"] is True
        assert cs.begin_send_right("start", ROOM, NEW, old["token"]) is False
        assert cs.begin_send_right("start", ROOM, NEW, new["token"]) is True
        assert cs.take_send_right("start", ROOM, NEW) is None and cs.send_right_state("start", ROOM, NEW) == "begun"
    clear_send_rights()


def test_the_parallel_save_branch_takes_the_right_before_starting(env) -> None:
    """VERIFY4 P2-4: with streaming input off and DAN_PARALLEL_SEND on, an ordinary send starts the model before its row
    is saved. The same send twice must still start it once: the right is taken before the start (and before the
    "supersede the running turn" step, so the second request also stops nothing)."""
    env.reset()
    db = env.state["db"]
    db.tables["projects"] = [{"id": "test-project", "room_id": ROOM, "status": "in_progress", "title": "test"}]
    starts, killed = [], []

    async def cli(**kw):
        starts.append(kw["content"])
        yield {"type": "result", "text": "test result", "cli_saved": True, "saved_message_id": "synthetic-ai-" + str(len(starts))}

    run = NS(get_current_run=AsyncMock(return_value=None), create_run=AsyncMock(return_value={"id": "test-run"}), update_run=AsyncMock())
    with ExitStack() as s:
        s.enter_context(patch.dict("os.environ", {"DAN_PARALLEL_SEND": "1"}))
        s.enter_context(patch("app.agent.streaming_session.streaming_enabled", return_value=False))
        s.enter_context(patch("app.agent.turn_flow.waits_for_running_turn", return_value=False))
        s.enter_context(patch("app.agent.turn_flow.claim_new_turn", return_value=None))
        s.enter_context(patch("app.services.run_service.RunService", return_value=run))
        s.enter_context(patch("app.agent.cli_runner.process_message_cli", cli))
        s.enter_context(patch("app.agent.cli_runner.is_cli_active", return_value=False))
        s.enter_context(patch("app.agent.cli_runner.kill_cli_process", side_effect=lambda room, **k: killed.append(room)))
        s.enter_context(patch("app.services.outbound_message_service.OutboundMessageService", return_value=NS(digest_for_turn=lambda _: "")))
        for n in ("_fetch_unseen_voice_digest", "_auto_timeline_refs", "_save_media_artifacts_in_background", "_trigger_observer"):
            s.enter_context(patch.object(cr, n, return_value=None))
        for n in ("_notify_dan_completion", "_register_written_chat_artifacts"):
            s.enter_context(patch.object(cr, n, AsyncMock()))
        a = env.send({"content": "plain"})
        b = env.send({"content": "plain"})
    assert len(starts) == 1 and sum(1 for r in rows(env) if r["id"] == NEW) == 1
    assert types(a[1]) == ["user_message", "ai_message", "done"]
    assert types(b[1]) == ["user_message", "done"] and b[1][0]["message"]["id"] == NEW and not killed


def test_the_earlier_refusals_still_hold(env) -> None:
    env.reset()
    before = rows(env)
    assert types(env.send({"answer_to": link(part="pffffffff")})[1]) == ["error", "done"]                 # a part that is not there
    assert types(env.send({"session_id": ROOM2, "answer_to": link()}, OTHER)[1]) == ["error", "done"]     # a reply of another room
    assert env.send({"answer_to": link(value=0)})[0] == 422                                              # wrong type
    assert types(env.send({"replace_message_id": MID, "content": "x"}, OTHER)[1]) == ["error", "done"]  # someone else's row
    assert rows(env) == before
