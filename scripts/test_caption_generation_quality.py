from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api import production_asset_routes as routes  # noqa: E402


def _words(parts: list[str], step: float = 0.32) -> list[dict]:
    out = []
    t = 0.0
    for i, text in enumerate(parts):
        out.append({
            "text": text,
            "start": round(t, 3),
            "end": round(t + step, 3),
            "segment_index": 0 if i < 10 else 1,
        })
        t += step
    return out


def test_glossary_and_caption_lengths() -> None:
    words = _words([
        "ライン", "追加を", "促す", "CTAを", "最後に", "入れて",
        "視聴者が", "迷わない", "形に", "してください",
    ])
    seq = {"tracks": [{"id": "v1", "type": "video", "clips": []}]}
    grouped = routes._group_caption_words(words, glossary=[("ライン", "LINE")])
    assert grouped
    assert routes._caption_apply_glossary("ライン追加", [("ライン", "LINE")]) == "LINE追加"
    seq2, count = routes._generate_caption_sequence_from_words(seq, words)
    assert count > 0
    captions = next(t for t in seq2["tracks"] if t["type"] == "caption")["clips"]
    assert all(routes._caption_text_len(c["text"]) <= 36 for c in captions)
    assert all(len(str(c["text"]).splitlines()) <= 2 for c in captions)
    assert any((c["timeline_end"] - c["timeline_start"]) >= 0.55 for c in captions)


def test_natural_boundaries_do_not_make_long_blocks() -> None:
    words = _words([
        "これは", "かなり", "重要です", "なので", "先に", "全体像を",
        "説明します", "そのあと", "具体的な", "編集に", "入ります",
    ])
    groups = routes._group_caption_words(words)
    texts = [routes._caption_join_words(g) for g in groups]
    assert len(texts) >= 2
    assert all(routes._caption_text_len(t) <= 24 for t in texts)
    assert any(t.endswith("重要です") or t.endswith("なので") for t in texts)


def test_display_text_prefers_two_balanced_lines() -> None:
    text = "これはかなり重要ですなので先に全体像を説明します"
    display = routes._caption_display_text(text, max_line_chars=16)
    lines = display.splitlines()
    assert len(lines) == 2
    assert all(4 <= routes._caption_text_len(line) <= 19 for line in lines)


if __name__ == "__main__":
    tests = [
        test_glossary_and_caption_lengths,
        test_natural_boundaries_do_not_make_long_blocks,
        test_display_text_prefers_two_balanced_lines,
    ]
    for test in tests:
        test()
    print("caption generation quality tests passed")
