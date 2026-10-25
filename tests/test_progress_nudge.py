"""Reminding Dan to write the work lines (scripts/hook_progress_nudge.py) and Codex search lines (2026-10-25)."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


nudge = _load("hook_progress_nudge", "scripts/hook_progress_nudge.py")
bridge = _load("codex_hook_bridge", "scripts/codex_hook_bridge.py")
al = nudge._activity_line()
SILENT = set(al._SILENT) | {"ToolSearch", "TodoWrite"}


def _run(tools, turn="t1", start=1000.0, step=5.0, state=None):
    state, said = state or {}, []
    for i, name in enumerate(tools):
        state, text = nudge.decide(state, name, turn, start + i * step, SILENT, al._base_name)
        said.append(text)
    return state, said


def test_third_tool_without_progress_is_nudged_once():
    _, said = _run(["mcp__dan-tools__web_search", "mcp__dan-tools__browser", "mcp__dan-tools__browser", "Bash"])
    assert [bool(s) for s in said] == [False, False, True, False]
    assert "progress" in said[2] and "doing" in said[2]


def test_short_answers_and_background_tools_are_not_nudged():
    _, said = _run(["mcp__dan-tools__web_search", "mcp__dan-tools__watch", "mcp__dan-tools__preference",
                    "mcp__dan-tools__lookup"])
    assert not any(said)


def test_progress_resets_and_later_nudge_after_six():
    tools = ["mcp__dan-tools__progress"] + ["mcp__dan_tools__browser"] * 6 + ["mcp__dan_tools__progress", "Bash"]
    _, said = _run(tools)
    assert [i for i, s in enumerate(said) if s] == [6]
    assert "done" in said[6]


def test_new_turn_starts_over():
    state, _ = _run(["Bash", "Bash"], turn="a")
    _, said = _run(["Bash", "Bash"], turn="b", state=state)
    assert not any(said)
    # Claude (no turn id): a long pause also starts a new turn
    state, _ = _run(["Bash", "Bash"], turn="")
    _, said = _run(["Bash"], turn="", start=1000 + nudge.TURN_GAP_SECONDS + 60, state=state)
    assert not any(said)


def test_hook_end_to_end_and_stop_clears(tmp_path, monkeypatch):
    sid = "test-progress-nudge-session"
    path = nudge.STATE_DIR / (sid + ".json")
    path.unlink(missing_ok=True)

    def call(payload):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "hook_progress_nudge.py")],
                              input=json.dumps(payload), capture_output=True, text=True, timeout=20).stdout
    base = {"session_id": sid, "hook_event_name": "PostToolUse", "turn_id": "x"}
    outs = [call({**base, "tool_name": "webrun"}) for _ in range(3)]
    assert outs[0] == outs[1] == ""
    spec = json.loads(outs[2])["hookSpecificOutput"]
    assert spec["hookEventName"] == "PostToolUse" and "progress" in spec["additionalContext"]
    # what Codex is given through the bridge: the text alone
    assert bridge._context_text(outs[2]) == spec["additionalContext"]
    assert bridge._context_text("plain text\n") == "plain text"
    call({"session_id": sid, "hook_event_name": "Stop"})
    assert not path.exists()


def test_codex_search_words_and_opened_page():
    from app.agent import codex_runner as cr
    started = {"id": "s1", "type": "web_search", "query": "", "action": {"type": "other"}}
    assert cr.web_search_query(started) == "" and cr.web_search_url(started) == ""
    done = {"id": "s1", "type": "web_search", "query": "メンヤ ニューオルド 食べログ…",
            "action": {"type": "search", "query": None, "queries": ["メンヤ ニューオルド 食べログ 営業時間"]}}
    [ev] = cr._item_to_events(done)
    assert ev["name"] == "WebSearch" and ev["input"]["query"] == "メンヤ ニューオルド 食べログ 営業時間"
    assert al.activity_phrase(ev["name"], ev["input"]).startswith("「メンヤ ニューオルド")
    opened = {"id": "s2", "type": "web_search", "query": "", "action": {"type": "other"},
              "results": [{"url": "https://silver-grape.com/shop/"}]}
    [ev] = cr._item_to_events(opened)
    assert al.activity_phrase(ev["name"], ev["input"]) == "silver-grape.com を読んでいます"


def test_codex_profile_runs_post_tool_hooks_for_every_tool(tmp_path, monkeypatch):
    from app.agent import codex_runner as cr
    monkeypatch.setattr(cr, "_CODEX_HOME", tmp_path)
    mcp = tmp_path / "mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    name = cr.build_codex_profile("room-x", str(mcp), "")
    text = (tmp_path / f"{name}.config.toml").read_text(encoding="utf-8")
    pre, post = text.split("[[hooks.PreToolUse]]")[1], text.split("[[hooks.PostToolUse]]")[1]
    assert 'matcher = "Bash|apply_patch"' in pre.split("[[hooks.")[0]
    assert 'matcher = ".*"' in post.split("[[hooks.")[0]
