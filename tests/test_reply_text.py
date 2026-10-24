"""返事の頭に付いた途中の英語の独り言を外す（app/agent/reply_text.py、2026-10-24 本番確認の不具合）"""
from app.agent.reply_text import drop_foreign_preamble, tidy_reply, user_speaks_japanese

JA_ASK = "尼崎駅の近くで今日やってるカフェを3つ調べて"
MONO = ("All three verified against official store pages for today (Saturday, Oct 24). The Nishimura Coffee "
        "result near the station is stale: that Q's Mall branch closed in 2019, so I dropped it.")
BODY = ("今日（土曜）やってる JR尼崎駅の近くのカフェ3つ。営業時間は各店の公式ページで確かめた。\n\n"
        "```openui-lang\nroot = Compare([\"店\"], [[\"ドトール\"]])\n```\n\n"
        "- [ドトール JR尼崎駅前店（公式）](https://shop.doutor.co.jp/doutor/spot/detail?code=2012054)")


def test_drops_english_monologue_before_japanese_reply():
    assert drop_foreign_preamble(f"{MONO}\n\n{BODY}", JA_ASK) == BODY


def test_drops_several_leading_paragraphs_and_keeps_the_rest_verbatim():
    text = f"Checked the pages.\nAll good now, writing the answer.\n\nOne more note on sources here.\n\n{BODY}\n\nThat's all."
    assert drop_foreign_preamble(text, JA_ASK) == f"{BODY}\n\nThat's all."


def test_english_user_keeps_everything():
    text = "Here's the translation:\n\n私は猫が大好きです。"
    assert drop_foreign_preamble(text, "Is this natural Japanese? 私は猫が好き") == text
    assert drop_foreign_preamble(f"{MONO}\n\n{BODY}", "find three cafes near Amagasaki station") == f"{MONO}\n\n{BODY}"


def test_english_only_reply_is_untouched():
    text = "The quick brown fox jumps over the lazy dog.\n\nAnother English paragraph."
    assert drop_foreign_preamble(text, JA_ASK) == text


def test_code_quote_and_list_at_the_head_are_kept():
    for head in ("```python\nprint('hello world from the code')\n```",
                 "> To be, or not to be, that is the question.",
                 "- Starbucks Amagasaki Q's Mall store opens at seven",
                 "[添付ファイル: report.pdf (/api/v1/files/report.pdf)]"):
        text = f"{head}\n\n日本語で説明します。上の部分はそのまま残します。"
        assert drop_foreign_preamble(text, JA_ASK) == text


def test_english_head_followed_by_code_is_kept():
    text = "Here is the script you asked for.\n\n```bash\nls\n```\n\n説明は以上です。"
    assert drop_foreign_preamble(text, JA_ASK) == text


def test_japanese_with_english_terms_is_japanese():
    text = "GitHub の PR を作ってマージしました。\n\n続きです。"
    assert drop_foreign_preamble(text, JA_ASK) == text


def test_user_language_reads_the_wrapped_message():
    wrapped = ("<conversation_so_far>前の話の流れがここに入ります。</conversation_so_far>\n\n"
               "<latest_user_message>\nplease find three cafes near the station\n</latest_user_message>")
    assert not user_speaks_japanese(wrapped)
    assert user_speaks_japanese(f"<room_state>Room state in English wrapper text.</room_state>\n<latest_user_message>{JA_ASK}</latest_user_message>")
    assert user_speaks_japanese(f"Internal recovery context.\n<user_request>{JA_ASK}</user_request>")
    assert not user_speaks_japanese(None)


def test_tidy_reply_applies_to_text_blocks_only():
    blocks = [{"type": "tool", "name": "web_search"}, {"type": "text", "text": "Checking the official pages now."},
              {"type": "text", "text": f"{MONO}\n\n{BODY}"}]
    text, out = tidy_reply(f"{MONO}\n\n{BODY}", blocks, JA_ASK)
    assert text == BODY
    assert out[0] == blocks[0]
    assert out[1]["text"] == "Checking the official pages now."
    assert out[2]["text"] == BODY
