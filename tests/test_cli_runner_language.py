from app.agent.cli_runner import _build_language_alignment_section, _detect_user_language


def test_detect_user_language_japanese() -> None:
    assert _detect_user_language("やっぱりこの方針で進めてください") == "Japanese"


def test_detect_user_language_korean() -> None:
    assert _detect_user_language("이 방향으로 계속 진행해 주세요") == "Korean"


def test_detect_user_language_defaults_to_english() -> None:
    assert _detect_user_language("Please continue with the current plan.") == "English"


def test_language_alignment_section_uses_latest_message_language() -> None:
    section = _build_language_alignment_section(
        latest_user_message="한국어로 계속 설명해 주세요",
        user_messages="Earlier messages were in English.",
    )

    assert "Korean" in section
    assert "visible reasoning/thinking text" in section
