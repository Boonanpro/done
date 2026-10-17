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
    # 2026-10-17 (fix6): the comparison sentence the owner accepted and the "show the real thing" paragraph made it
    # 3.3KB (was 2.3KB); the cap moved from 2500 to 3400 with them
    assert len(section) <= 3400


def test_section_asks_for_the_real_thing_and_a_table_for_comparisons() -> None:
    section = chat_shapes_section()
    # the sentence tried in REPORT3 (fix2/build_prompt.py EXTRA), word for word
    assert ("When the user asks which of two or more named things is better or how they differ (「AとBどっちが良い？」), "
            "the answer is a Compare of the deciding points followed by your recommendation in prose; "
            "prose alone or a Choice alone is not a comparison.") in section
    assert "Show the real thing when the user picks among things that differ by look" in section
    assert "Never invent an image URL" in section
    assert "(string | {label: string, color?: string, image?: string})[]" in section   # Choice options
    assert "rows: (string | {label: string, color?: string})[][]" in section            # Compare cells


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


def test_job_runners_stay_prose_only() -> None:
    """Independent jobs (command_job_runner: the non-parallel Codex CLI job that command_center starts by default,
    and its parallel/make variants; parallel_job_runner; api_job_runner) build their brief without the section.

    Not because the screen cannot show a job's text (it can: the job's intermediate messages are saved as the room's
    'reasoning' events, and the result is reported as an ordinary AI message of the target room), but by choice, for
    two reasons in the code: the job has already ended when its report arrives, so an answer to a Choice/Input could
    not reach the job that asked; and the report is cut at 2800 characters, which can cut a part block in the middle.
    (command_handoff is different: it runs the room's own chat turn, whose reply the owner answers in that room, so it
    keeps answer_shapes=True.)"""
    runner = (ROOT / "app/services/command_job_runner.py").read_text(encoding="utf-8")
    call = runner[runner.index("asyncio.to_thread(_build_system_prompt"):runner.index("if parallel:", runner.index("asyncio.to_thread(_build_system_prompt"))]
    assert "answer_shapes=False" in call and "answer_shapes=True" not in runner
    assert "'task':result[:2800]" in runner                      # the report is the result cut at 2800 characters
    assert "'reasoning'" in runner                               # the intermediate messages do reach the room (live work view)
    center = (ROOT / "app/services/command_center.py").read_text(encoding="utf-8")
    assert 'sender_type="ai", message_id=report_message_id' in center   # the report is an ordinary AI message of the room
    for rel in ("app/services/parallel_job_runner.py", "app/services/api_job_runner.py", "app/services/make_job_runner.py"):
        path = ROOT / rel
        if path.exists():
            assert "answer_shapes=True" not in path.read_text(encoding="utf-8"), rel
    handoff = (ROOT / "app/services/command_handoff.py").read_text(encoding="utf-8")
    assert "answer_shapes=True" in handoff
