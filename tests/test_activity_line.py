"""The one line the chat shows while Dan works (app/agent/activity_line.py, 2026-10-23)."""
from app.agent.activity_line import activity_phrase


def test_plain_words_for_common_tools() -> None:
    assert activity_phrase("mcp__dan-tools__browser", {"action": "open_target", "url": "https://www.ubereats.com/jp/store/x"}) == "ubereats.com を開いています"
    assert activity_phrase("mcp__dan-tools__browser", {"action": "click", "ref": "@e3"}) == "ページを操作しています"
    assert activity_phrase("mcp__dan-tools__browser", {"action": "fill_credential"}) == "ログインしています"
    assert activity_phrase("mcp__dan-tools__web_search", {"query": "尼崎 ハンバーガー"}) == "「尼崎 ハンバーガー」を調べています"
    assert activity_phrase("WebFetch", {"url": "https://example.com/a"}) == "example.com を読んでいます"
    assert activity_phrase("mcp__dan-tools__lookup", {"source": "mail"}) == "メールを見ています"
    assert activity_phrase("Read", {"file_path": "/x/y.py"}) == "資料を読んでいます"
    assert activity_phrase("Edit", {}) == "書いています"
    assert activity_phrase("Bash", {"command": "rm -rf /tmp/x"}) == "作業しています"


def test_background_work_keeps_the_previous_line() -> None:
    for name in ("mcp__dan-tools__watch", "mcp__dan-tools__remember_personal_info", "mcp__dan-tools__get_credentials",
                 "mcp__dan-tools__preference", "mcp__dan-tools__attach_image", "TodoWrite"):
        assert activity_phrase(name, {}) == ""


def test_never_shows_commands_paths_or_long_queries() -> None:
    assert "rm" not in activity_phrase("Bash", {"command": "rm -rf /"})
    assert "/x/y.py" not in activity_phrase("Write", {"file_path": "/x/y.py"})
    long = activity_phrase("mcp__dan-tools__web_search", {"query": "あ" * 80})
    assert len(long) < 40 and long.endswith("を調べています")
    assert activity_phrase("unknown_tool", None) == "作業しています"
