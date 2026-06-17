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
