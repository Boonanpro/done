"""部屋ごとの相談先（projects.metadata.advisor → claude --advisor）。"""
from app.agent import cli_runner as c


def _set(room, adv):
    c._room_advisor_cache[room] = adv


def test_advisor_only_for_claude_base_weaker_than_advisor(monkeypatch):
    monkeypatch.setattr(c, "_apply_fable_quota_guard", lambda m: m)
    _set("r1", "fable")
    assert c._resolve_cli_advisor("r1", "opus") == "fable"
    assert c._resolve_cli_advisor("r1", "fable") is None          # 本体と同じ
    assert c._resolve_cli_advisor("r1", "gpt-6-astra") is None    # Codex の部屋
    assert c._resolve_cli_advisor("unset-room", "opus") is None
    assert c._resolve_cli_advisor(None, "opus") is None
    _set("r2", "gpt-6-astra")
    assert c._resolve_cli_advisor("r2", "opus") is None           # Codex は相談先にならない
    _set("r3", "nonsense")
    assert c._resolve_cli_advisor("r3", "opus") is None


def test_advisor_dropped_when_fable_quota_exhausted(monkeypatch):
    monkeypatch.setattr(c, "_apply_fable_quota_guard", lambda m: "opus")
    _set("r4", "fable")
    assert c._resolve_cli_advisor("r4", "opus") is None


def test_session_key_changes_with_advisor():
    assert c._session_model_key("opus", None) == "opus"
    assert c._session_model_key("opus", "fable") != "opus"


def test_build_cmd_adds_advisor_flag():
    cmd = c._build_cli_cmd("claude", None, "m.json", "sp", model="opus", advisor="fable")
    i = cmd.index("--advisor")
    assert cmd[i + 1] == "fable"
    assert "--advisor" not in c._build_cli_cmd("claude", None, "m.json", "sp", model="opus")


def test_invalidate_clears_advisor():
    _set("r5", "fable")
    c.invalidate_room_model_cache("r5")
    assert "r5" not in c._room_advisor_cache


def test_advisor_block_is_shown_as_a_tool_step():
    ev = c._classify_content_blocks([
        {"type": "server_tool_use", "id": "s1", "name": "advisor", "input": {}},
        {"type": "advisor_tool_result", "tool_use_id": "s1", "content": {"type": "advisor_redacted_result"}},
        {"type": "text", "text": "答え"},
    ])
    assert [e["type"] for e in ev] == ["tool_use", "text"]
