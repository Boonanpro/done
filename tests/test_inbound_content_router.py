from app.services.inbound_content_router import _parse_json


def test_parse_clean_json():
    assert _parse_json('{"decision":"new","room_index":null,"reason":"x"}') == {
        "decision": "new",
        "room_index": None,
        "reason": "x",
    }


def test_parse_json_with_surrounding_text():
    raw = 'はい。\n{"decision":"existing","room_index":2,"reason":"件Aの返信"}\n以上です。'
    out = _parse_json(raw)
    assert out["decision"] == "existing"
    assert out["room_index"] == 2


def test_parse_json_garbage_returns_none():
    assert _parse_json("これはJSONではありません") is None
    assert _parse_json("") is None
    assert _parse_json(None) is None


def test_sent_form_matches_new_contact_and_leaves_ambiguous_projects_unassigned():
    from app.services.external_message_routing import _matching_form

    form = {"source_room_id": "prototype", "action_data": {"to": "電子部品商会"},
            "content": "小型マイク AB-2019 の見積をお願いします。"}
    args = ("new@example.jp", "電子部品商会からの回答", "AB-2019 は来週納品できます。")
    assert _matching_form([form], *args) == form
    assert _matching_form([form, {**form, "source_room_id": "another"}], *args) is None
    assert _matching_form([form], args[0], args[1], "担当が変わりました") is None


def test_unassigned_request_retried_goes_to_home_queue_once(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock
    from app.services import inbound_content_router as router, inbound_wakeup, inbox, work_continuity

    monkeypatch.setattr(work_continuity, "DB", tmp_path / "work.sqlite")
    monkeypatch.setattr(inbound_wakeup, "_wake_task", AsyncMock())
    monkeypatch.setattr(router, "_recent_rooms", lambda sb: [])
    monkeypatch.setattr(router, "_classify", lambda *args: {"decision": "new"})
    monkeypatch.setattr(inbox, "home_room", AsyncMock(return_value="home"))
    item = {"source": "gmail", "id": "mail", "user_id": "owner", "content": "Please confirm delivery."}
    svc = SimpleNamespace(supabase=MagicMock())

    async def retry():
        for _ in range(2):
            result = await router.classify_and_route(item, svc)
            assert result["room_id"] == "home"

    asyncio.run(retry())
    jobs = work_continuity.room_work("home")
    assert len(jobs) == 1 and item["content"] in jobs[0]["prompt"]
