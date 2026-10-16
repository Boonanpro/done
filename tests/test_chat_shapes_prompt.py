"""The answer-shapes section (``` openui-lang parts) reaches every backend's system prompt."""
from pathlib import Path

from app.agent import chat_shapes
from app.agent.chat_shapes import chat_shapes_section


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


def test_system_prompt_contains_section_for_both_engines(monkeypatch) -> None:
    """Claude and Codex share _build_system_prompt (codex_runner receives the same string), and
    Codex's per-thread fingerprint changes when the section changes."""
    from app.agent import cli_runner, codex_runner

    prompt = cli_runner._build_system_prompt("t", "", "in_progress", include_room_role=False)
    section = chat_shapes_section()
    assert section and section in prompt
    assert prompt.index(cli_runner._ABSOLUTE_RULES) < prompt.index(section) < prompt.index(cli_runner._BROWSER_AUTH_RULES)

    before = codex_runner.compute_static_hash("")
    monkeypatch.setattr(chat_shapes, "CHAT_SHAPES_PROMPT_PATH", Path("missing.md"))
    after = codex_runner.compute_static_hash("")
    assert before and after and before != after
