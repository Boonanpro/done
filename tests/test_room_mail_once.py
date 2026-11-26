# -*- coding: utf-8 -*-
"""One mail wakes a room once (2026-11-26: a JLCPCB mail woke the pin room three times — the reply routing and two
jlcpcb.com mail watches — and Dan said the same thing three times)."""
import asyncio

import pytest

from app.services import followup_poller, inbound_wakeup, room_mail_once

ROOM = "f33845ec-56b7-43b0-9688-e7b650d34fde"
MID = "<CAMTqJdNf3h+GM82FYp01kafHdKhjpsixFedjO2GPk5++hmCkCw@mail.gmail.com>"
MAIL = {"message_id": MID, "sender": "Brosnan <brosnan@jlcpcb.com>", "subject": "Re: Potential Delivery Delay Notice",
        "date": "Thu, 26 Nov 2026 09:18:46 -0500", "attachments": "なし", "body": "we have closed this case."}
NOTES = {"w1": "基板Bの審査・出荷のメール", "w2": "直した部品配置図が来たら1番ピンを確かめる"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(room_mail_once, "PATH", tmp_path / "once.json")
    monkeypatch.setattr(room_mail_once, "watch_notes",
                        lambda room, sender, subject="", skip="": [n for k, n in NOTES.items() if k != skip])
    wakes = []

    async def wake_turn(room_id, user_id, content):
        wakes.append(("watch", content))
        return "ok", True
    monkeypatch.setattr(followup_poller, "_wake_turn", wake_turn)
    monkeypatch.setattr("app.services.mail_watch.check_mail_watch", lambda spec: ({**spec, "last_uid": 2141}, [dict(MAIL)]))
    monkeypatch.setattr("app.services.inbox.enabled", lambda: False)
    monkeypatch.setattr("app.services.followups.reschedule_watch", lambda *a, **k: None)
    monkeypatch.setattr("app.services.work_continuity.enqueue", lambda **k: None)

    async def wake_task(msg, room_id, reason):
        wakes.append(("inbound", inbound_wakeup._build_prompt(msg, reason)))
    monkeypatch.setattr(inbound_wakeup, "_wake_task", wake_task)
    return wakes


def _watch(wid):
    return {"id": wid, "room_id": ROOM, "user_id": "u", "plain_note": NOTES[wid],
            "spec": {"from": "jlcpcb.com", "mailbox": "gmail", "last_uid": 2140}}


def _detected():
    return {"id": "315d40f6", "user_id": "u", "source": "gmail", "source_id": MID, "subject": MAIL["subject"],
            "content": MAIL["body"], "sender_info": {"from": MAIL["sender"], "date": MAIL["date"]},
            "metadata": {"message_id": MID}}


def test_reply_routing_then_two_watches_wake_once(world):
    async def run():
        assert inbound_wakeup.schedule_room_wakeup(_detected(), ROOM, reason="sent_form_reply")
        await asyncio.sleep(0)
        await followup_poller._fire_mail(_watch("w1"))
        await followup_poller._fire_mail(_watch("w2"))
    asyncio.run(run())
    assert [w[0] for w in world] == ["inbound"]
    # the one wake carries what both watches wait for
    assert NOTES["w1"] in world[0][1] and NOTES["w2"] in world[0][1]


def test_two_watches_without_routing_wake_once(world):
    async def run():
        await followup_poller._fire_mail(_watch("w1"))
        await followup_poller._fire_mail(_watch("w2"))
    asyncio.run(run())
    assert len(world) == 1
    assert NOTES["w2"] in world[0][1]


def test_a_new_mail_still_wakes(world, monkeypatch):
    async def run():
        await followup_poller._fire_mail(_watch("w1"))
        monkeypatch.setattr("app.services.mail_watch.check_mail_watch",
                            lambda spec: (spec, [{**MAIL, "message_id": "<other@jlcpcb.com>", "subject": "Updated preview"}]))
        await followup_poller._fire_mail(_watch("w2"))
    asyncio.run(run())
    assert len(world) == 2


def test_same_watch_may_retry_and_release_frees(tmp_path, monkeypatch):
    monkeypatch.setattr(room_mail_once, "PATH", tmp_path / "once.json")
    assert room_mail_once.claim(ROOM, MID, "watch:w1")
    assert room_mail_once.claim(ROOM, MID, "watch:w1")
    assert not room_mail_once.claim(ROOM, MID, "inbound")
    room_mail_once.release(ROOM, MID, "watch:w1")
    assert room_mail_once.claim(ROOM, MID, "inbound")
    assert room_mail_once.claim("other-room", MID, "watch:w9")   # another room is its own
    assert room_mail_once.claim(ROOM, "", "x") and room_mail_once.claim(ROOM, "", "y")   # no id: never blocked
