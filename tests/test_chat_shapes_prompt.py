"""The answer-shapes section (``` openui-lang parts): where it goes and where it must not.

It reaches only turns whose reply is drawn by the room's chat screen (process_message_cli callers that pass
answer_shapes=True, on both engines with the same text). Voice (dan_core.shared), the editor (editor_runtime),
the external window (collab) and every other caller get a prompt without it."""
import re
from pathlib import Path
from unittest.mock import patch

from app.agent import chat_shapes
from app.agent.chat_shapes import chat_shapes_section

ROOT = Path(__file__).resolve().parent.parent


def test_section_is_generated_file_content() -> None:
    section = chat_shapes_section()
    assert section.startswith("## Answer shapes")
    for name in ("Compare", "Choice", "Input", "Steps", "Chart"):
        assert f"- {name}(" in section
    assert "```openui-lang" in section
    assert len(section) <= 2500


def test_missing_file_degrades_to_empty(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(chat_shapes, "CHAT_SHAPES_PROMPT_PATH", tmp_path / "missing.md")
    assert chat_shapes_section() == ""
    bad = tmp_path / "bad.md"
    bad.write_text("## something else", encoding="utf-8")
    monkeypatch.setattr(chat_shapes, "CHAT_SHAPES_PROMPT_PATH", bad)
    assert chat_shapes_section() == ""


def test_section_only_with_answer_shapes_flag_same_for_both_engines() -> None:
    """Off by default; on with answer_shapes=True. Codex receives the very same string
    (wrap_turn_content) and its per-thread fingerprint follows what the prompt carries."""
    from app.agent import cli_runner, codex_runner

    section = chat_shapes_section()
    assert section
    off = cli_runner._build_system_prompt("t", "", "in_progress", include_room_role=False)
    on = cli_runner._build_system_prompt("t", "", "in_progress", include_room_role=False, answer_shapes=True)
    assert section not in off
    assert section in on
    assert on.index(cli_runner._ABSOLUTE_RULES) < on.index(section) < on.index(cli_runner._BROWSER_AUTH_RULES)
    assert on.replace(section + "\n\n", "") == off   # the only difference is the section

    # the Claude launch payload (argv or stdin) and the Codex turn wrapper carry the same prompt
    argv, stdin = cli_runner._prepare_cli_launch_payload(on, "hello")
    assert section in argv or section in stdin
    assert section in codex_runner.wrap_turn_content(on, "hello")
    assert section not in codex_runner.wrap_turn_content(off, "hello")

    # Codex fingerprint: differs between on and off, and equals "no section" when the prompt lacks it
    assert codex_runner.compute_static_hash(on) != codex_runner.compute_static_hash(off)
    with patch.object(chat_shapes, "CHAT_SHAPES_PROMPT_PATH", Path("missing.md")):
        assert codex_runner.compute_static_hash(off) == codex_runner.compute_static_hash("")


def test_prepare_cli_inputs_passes_the_flag_through() -> None:
    import asyncio
    from app.agent import cli_runner

    section = chat_shapes_section()
    kw = dict(title="t", description="", status="in_progress", user_messages="", latest_user_message="x",
              room_id="", user_id="", include_room_role=False)
    with patch.object(cli_runner, "_build_mcp_config", return_value="mcp.json"):
        with_flag, _ = asyncio.run(cli_runner._prepare_cli_inputs("r", "u", None, None, None, {**kw, "answer_shapes": True}))
        without, _ = asyncio.run(cli_runner._prepare_cli_inputs("r", "u", None, None, None, {**kw, "answer_shapes": False}))
    assert section in with_flag and section not in without


def test_voice_and_editor_briefs_have_no_section() -> None:
    """dan_core.shared (voice / jobs) and editor_runtime build their brief without the flag."""
    from app.services import dan_core

    section = chat_shapes_section()
    with patch.object(dan_core, "_owner_words", return_value=""), patch.object(dan_core, "CLI_WORKSPACE", ROOT / "tests"):
        dan_core._cache.clear()
        shared = dan_core.shared(None, None)
    assert section not in shared
    editor_src = (ROOT / "app/services/editor_runtime.py").read_text(encoding="utf-8")
    assert "answer_shapes" not in editor_src


def test_callers_that_draw_in_the_chat_screen_are_exactly_these() -> None:
    """Pin which process_message_cli call sites opt in. Anything else (collab, voice, production assets,
    the observer) stays prose-only. Add a file here deliberately when a new drawable caller appears."""
    expected_on = {
        "app/api/chat_routes.py",            # the owner's chat turn (web; the APK shows parts as text)
        "app/services/inbound_wakeup.py",    # a report into the room's chat
        "app/services/followup_poller.py",   # a watch firing into the room's chat
        "app/services/command_handoff.py",   # a delegated job reporting into that room's chat
        "app/services/chat_service.py",      # an instruction about a proposal, answered in the room's chat
    }
    pattern = re.compile(r"process_message_cli\((?P<args>.*?)\)\s*:", re.S)
    on, off = set(), set()
    for path in (ROOT / "app").rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT).as_posix()
        for m in pattern.finditer(src):
            if "def process_message_cli" in src[max(0, m.start() - 10):m.start() + 30]:
                continue
            (on if "answer_shapes=True" in m.group("args") else off).add(rel)
    assert on == expected_on
    for rel in ("app/services/collab_wakeup.py", "app/api/collab_routes.py", "app/api/voice_routes.py",
                "app/api/production_asset_routes.py"):
        assert rel in off and rel not in on
