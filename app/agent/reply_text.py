"""返事の本文から、頭に付いた途中の独り言を外す（2026-10-24）。

本番の確認で「尼崎駅の近くで今日やってるカフェを3つ調べて」への返事の頭に、モデルが最後の道具の後に書いた
英語の独り言（「All three verified against official store pages for today ... so I dropped it.」）が1段落
残り、その後に日本語の返事が続いた。作業中の文は画面で隠している（frontend/src/lib/chat-shapes/live-line.ts）が、
終わった後に保存される本文には残っていた。指示（「作業の途中で文を書かない」）だけでは止まらないので、保存の手前で外す。

外すのは次の全部が揃う時だけ:
- 本人の言葉が日本語（英語で話しかけられた時は何も外さない）。
- 返事の先頭から続く、英語が主の普通の文の段落（コード・引用・表・箇条書き・見出し・添付の印は文ではないので外さない）。
- その段落の後に、日本語が主の普通の文の段落が来る（返事の本体が日本語）。

文の言語の決め方は live-line.ts の isJapaneseSentence と同じ（日本語の字が2つ以上で、英字が日本語の字の3倍を超えない）。
どのモデルの経路も cli_runner._save_ai_message_sync の手前でこれを通す（PC・スマホ・開発室は同じ保存済みの本文と
blocks を描くので、ここで直せば全部そろう）。
"""
from __future__ import annotations

import re
from typing import Any, List, Optional

_JA_CHAR = re.compile(r"[぀-ヿ㐀-鿿ｦ-ﾝ]")
_LATIN_CHAR = re.compile(r"[A-Za-z]")
# 本人の言葉を包みから取り出す（_wrap_latest_user_message と並行作業の依頼の包み）
_USER_WRAPPERS = (
    re.compile(r"<latest_user_message>\s*([\s\S]*?)\s*</latest_user_message>"),
    re.compile(r"<user_request>\s*([\s\S]*?)\s*</user_request>"),
)
# 文ではない段落の書き出し（コード・引用・表・箇条書き・見出し・添付の印・部品）
_NOT_PROSE_START = re.compile(r"^\s*(?:```|~~~|>|\||[-*+]\s|\d+[.)]\s|#|\[添付|<)")


def _plain(text: str) -> str:
    t = re.sub(r"`[^`]*`", " ", text)
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", " ", t)
    return t


def is_japanese(text: str) -> bool:
    """日本語が主の文か（live-line.ts の isJapaneseSentence と同じ決まり）"""
    t = _plain(text or "")
    ja = len(_JA_CHAR.findall(t))
    latin = len(_LATIN_CHAR.findall(t))
    return ja >= 2 and latin <= ja * 3


def _is_english_prose(paragraph: str) -> bool:
    if _NOT_PROSE_START.match(paragraph) or "```" in paragraph:
        return False
    t = _plain(paragraph)
    ja = len(_JA_CHAR.findall(t))
    latin = len(_LATIN_CHAR.findall(t))
    return latin >= 12 and latin > ja * 3


def _is_japanese_prose(paragraph: str) -> bool:
    return not _NOT_PROSE_START.match(paragraph) and is_japanese(paragraph)


def user_speaks_japanese(user_text: Optional[str]) -> bool:
    """本人の言葉が日本語か。ダンが付けた包みがあれば、中の本人の言葉だけで決める。"""
    s = user_text or ""
    for pat in _USER_WRAPPERS:
        found = pat.findall(s)
        if found:
            s = found[-1]
            break
    return is_japanese(s)


def drop_foreign_preamble(text: str, user_text: Optional[str]) -> str:
    """本人が日本語で話していて、返事の本体が日本語なら、頭に付いた英語の独り言の段落を外す。それ以外はそのまま。"""
    if not text or not user_speaks_japanese(user_text):
        return text
    paragraphs = re.split(r"\n\s*\n", text.lstrip())
    i = 0
    while i < len(paragraphs) and _is_english_prose(paragraphs[i]):
        i += 1
    if i == 0 or i >= len(paragraphs) or not _is_japanese_prose(paragraphs[i]):
        return text
    rest = text.lstrip()
    for _ in range(i):
        rest = re.split(r"\n\s*\n", rest, maxsplit=1)[1]
    return rest.lstrip("\n")


def tidy_reply(text: str, blocks: Optional[List[Any]], user_text: Optional[str]) -> tuple[str, Optional[List[Any]]]:
    """保存する本文と、画面（スマホは blocks から描く）の文のブロックの両方に同じ決まりを当てる。"""
    text = drop_foreign_preamble(text, user_text)
    if blocks:
        blocks = [
            {**b, "text": drop_foreign_preamble(b.get("text", ""), user_text)}
            if isinstance(b, dict) and b.get("type") == "text"
            else b
            for b in blocks
        ]
    return text, blocks
