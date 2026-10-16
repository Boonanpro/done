"""The server's reader of the parts of a reply (app.agent.chat_shapes.top_level_fences / shape_codes / part_keys)
gives the same answers as remark-parse (the screen's Markdown reader) and the screen's own code, on the corpus
tests/fixtures/chat_shapes_markdown_corpus.json (written from remark-parse's syntax tree by
make_chat_shapes_markdown_corpus.mjs, which first checks that plain.ts agrees). The corpus holds the verifier's
27 inputs (HTML block edges, whitespace), boundary cases (paragraphs, containers, HTML kinds 1-7, tabs, line
endings, language names, link reference definitions) and generated documents."""
import json
from pathlib import Path

from app.agent import chat_shapes

ROOT = Path(__file__).resolve().parents[1]
CORPUS = json.loads((ROOT / "tests" / "fixtures" / "chat_shapes_markdown_corpus.json").read_text(encoding="utf-8"))


def test_top_level_fences_match_remark_parse() -> None:
    assert len(CORPUS) > 600
    for row in CORPUS:
        got = [{"closed": f["closed"], "shape": f["lang"] in chat_shapes.SHAPE_FENCE_LANGS, "code": f["code"]}
               for f in chat_shapes.top_level_fences(row["text"])]
        assert got == row["fences"], (row["name"], row["text"])


def test_shape_codes_and_keys_match_the_screen() -> None:
    with_parts = 0
    for row in CORPUS:
        codes = chat_shapes.shape_codes(row["text"])
        assert codes == row["shape_codes"], (row["name"], row["text"])
        assert chat_shapes.part_keys(codes) == row["keys"], row["name"]
        for key in row["keys"]:
            assert chat_shapes.part_in_reply(row["text"], key), (row["name"], key)
        with_parts += bool(codes)
    assert with_parts >= 80   # 84 when written (722 cases)


def test_the_verifiers_27_inputs_are_all_there_and_agree() -> None:
    rows = [r for r in CORPUS if r["name"].startswith("verifier:")]
    assert len(rows) == 27
    by_name = {r["name"]: r for r in rows}
    # the cases the verifier found the server and the screen disagreeing on (NEL / BOM in a tag): now equal
    for name in ("verifier:html-ws-nel", "verifier:html-ws-bom"):
        assert len(by_name[name]["shape_codes"]) == 1
        assert chat_shapes.shape_codes(by_name[name]["text"]) == by_name[name]["shape_codes"]
    # HTML blocks after a heading / closed fence / comment / indented code hide the part, on both sides
    for name in ("verifier:htmlAfterHeading", "verifier:htmlAfterFence", "verifier:htmlAfterComment", "verifier:indented"):
        assert chat_shapes.shape_codes(by_name[name]["text"]) == [] == by_name[name]["shape_codes"], name


def test_markdown_whitespace_is_space_and_tab_only() -> None:
    fence = '```openui-lang\nroot = Choice("Q", ["A", "B"])\n```'
    for w in ("\u0085", "\ufeff", "\u00a0", "\u2028", "\u2029", "\u3000"):
        assert len(chat_shapes.shape_codes(f"<span{w}x>\n{fence}\n</span>")) == 1, repr(w)   # not a tag: the part is drawn
    assert chat_shapes.shape_codes(f"<span\tx>\n{fence}\n</span>") == []                     # a tab separates attributes
    assert chat_shapes.shape_codes(f"<div>\n\u3000\n{fence}") == []      # an ideographic space line is not blank
    assert len(chat_shapes.shape_codes(f"<div>\n \t\n{fence}")) == 1     # spaces and tabs only: blank, the block ends
