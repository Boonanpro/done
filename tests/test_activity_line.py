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


def test_thinking_text_keeps_japanese_only():
    from app.agent.activity_line import thinking_text
    assert thinking_text("まず画面を確かめる。次にお店のページを開きます。") == "まず画面を確かめる。次にお店のページを開きます。"
    assert thinking_text("Let me check the cart first.") == ""
    assert thinking_text("") == "" and thinking_text(None) == ""
    long = "あ" * 900
    assert len(thinking_text(long)) == 600


def test_save_thinking_event_marks_kind_and_skips_english(monkeypatch):
    from app.agent import cli_runner
    saved = []
    monkeypatch.setattr(cli_runner, "_save_execution_event_sync", lambda *a, **k: saved.append((a, k)))
    cli_runner._save_thinking_event("room", "proj", "run", "turn", "次にお店のページを開きます。")
    cli_runner._save_thinking_event("room", "proj", "run", "turn", "Let me open the page.")
    cli_runner._save_thinking_event("room", None, "run", "turn", "日本語でも部屋の記録が無ければ残さない。")
    assert len(saved) == 1
    args, kwargs = saved[0]
    assert args == ("room", "reasoning") and kwargs["kind"] == "thinking" and kwargs["content"] == "次にお店のページを開きます。"


# 2026-10-25: Dan's own words for the work line (progress tool, Japanese command descriptions)
def test_own_activity_and_done_note():
    from app.agent.activity_line import done_note, own_activity
    p = "mcp__dan-tools__progress"
    assert own_activity(p, {"doing": "アプリが自分の版を知らせているか確かめています。"}) == "アプリが自分の版を知らせているか確かめています"
    assert done_note(p, {"done": "✓ サーバーの記録を見ました。スマホは 1.0.75 と 1.0.76 を落としていました。"}) == \
        "サーバーの記録を見ました。スマホは 1.0.75 と 1.0.76 を落としていました。"
    assert done_note(p, {"done": "3つの店を調べました。"}) == "3つの店を調べました。"
    # English, or a doing line that is not 「〜しています」, is not Dan's line
    assert own_activity(p, {"doing": "Checking the app version"}) == ""
    assert own_activity(p, {"doing": "版を確かめる"}) == ""
    assert done_note(p, {"done": "Checked the server log."}) == ""
    assert own_activity("Bash", {"description": "サーバーの記録を探しています", "command": "rg x"}) == "サーバーの記録を探しています"
    assert own_activity("Bash", {"description": "Search the server log"}) == ""
    assert own_activity("mcp__dan-tools__web_search", {"query": "記録を探しています"}) == ""
    assert done_note("Bash", {"done": "見ました。"}) == ""
    # the progress call itself does not change the line by kind
    assert activity_phrase(p, {"done": "見ました。"}) == ""


def test_tool_event_carries_dans_words(monkeypatch):
    from app.agent import cli_runner
    rows = []

    class _T:
        def insert(self, row):
            rows.append(row)
            return self

        def execute(self):
            return None

    class _C:
        client = type("X", (), {"table": lambda self, name: _T()})()

    monkeypatch.setattr("app.services.supabase_client.get_supabase_client", lambda: _C())
    cli_runner._save_execution_event_sync("room", "tool_use", tool_name="mcp__dan-tools__progress",
                                          tool_input={"done": "記録を見ました。", "doing": "版を確かめています"})
    cli_runner._save_execution_event_sync("room", "tool_use", tool_name="Read", tool_input={"file_path": "/a"})
    assert rows[0]["metadata"] == {"activity": "版を確かめています", "activity_kind": "dan", "done": "記録を見ました。"}
    assert rows[1]["metadata"] == {"activity": "資料を読んでいます"}


def test_web_addresses_show_only_the_site() -> None:
    """2026-10-25: a GPT room showed 「「https://…」を調べています」 (Codex reports opening a page with the address as its words)."""
    from app.agent.activity_line import done_note, own_activity, thinking_text
    assert activity_phrase("WebSearch", {"query": "https://tabelog.com/hyogo/A2803/A280301/28001234/"}) == "tabelog.com を読んでいます"
    assert activity_phrase("WebSearch", {"query": "www.ramen-ichitetsu.jp/menu"}) == "ramen-ichitetsu.jp を読んでいます"
    assert activity_phrase("WebSearch", {"query": "site:tabelog.com 尼崎 ラーメン 日曜"}) == "「尼崎 ラーメン 日曜」を調べています"
    assert "http" not in activity_phrase("mcp__dan-tools__web_search", {"query": "営業時間 https://example.com/a/b"})
    assert own_activity("mcp__dan-tools__progress", {"doing": "https://tabelog.com/hyogo/x/ の営業時間を確かめています"}) == "tabelog.com の営業時間を確かめています"
    assert done_note("progress", {"done": "公式（https://www.newold.jp/shop）を見ました。日曜も23時まででした。"}) == "公式（newold.jp）を見ました。日曜も23時まででした。"
    assert "http" not in thinking_text("次に https://tabelog.com/hyogo/x を開きます。")


def test_codex_page_open_is_reading_that_page() -> None:
    from app.agent.codex_runner import _item_to_events
    ev = _item_to_events({"type": "web_search", "id": "w1", "query": "https://tabelog.com/hyogo/x/",
                          "action": {"type": "open_page", "url": "https://tabelog.com/hyogo/x/"}})
    assert ev[0]["name"] == "WebFetch" and activity_phrase(ev[0]["name"], ev[0]["input"]) == "tabelog.com を読んでいます"
