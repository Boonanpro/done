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
# 本人の言葉を包みから取り出す（内側の包みから。cli_runner._wrap_latest_user_message と codex_runner.wrap_turn_content）
_USER_WRAPPERS = ("latest_user_message", "user_request")
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
    for tag in _USER_WRAPPERS:
        # 最後の開きの印から。指示文の中に印の名前が書かれていても、本物の包みは一番後ろにある
        start = s.rfind(f"<{tag}>")
        if start < 0:
            continue
        inner = s[start + len(tag) + 2:]
        end = inner.find(f"</{tag}>")
        s = inner if end < 0 else inner[:end]
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


# 「本人に伝えることは無い」の印（2026-10-25）。見張りや付箋の部屋どうしの連絡で起こされたダンは、伝える新しいことが
# 無ければこの印だけを返す。今までは保存した後で app/services/followup_poller.py が消していたので、消すまでの間に画面と
# 通知に「WATCH_NO_CHANGE」が出た（本人「そのWATCH_NO_CHANGEもいらん」）。印の返事は、どの経路でも保存しない。
SILENT_MARKS = ("WATCH_NO_CHANGE",)
# 印を包むだけの飾り（コードの囲み・太字）。中身が印と完全に同じ時だけ「印だけ」と見る。印について話す普通の返事
# （「『WATCH_NO_CHANGE』は表示されなくなりました」）は捨てない（10-25 確かめたダンの指摘）。
_WRAP = re.compile(r"^(?:```[\w-]*\s*|`+|\*+|_+)?\s*(.*?)\s*(?:```|`+|\*+|_+)?$", re.S)


def is_silent_reply(text: Optional[str]) -> bool:
    """本人に何も見せない返事か。前後の空白・改行と、印を包む飾りを除いて、本文が印と完全に同じ時だけ。"""
    t = (text or "").strip()
    if not t:
        return False
    m = _WRAP.match(t)
    inner = (m.group(1) if m else t).strip()
    return inner in SILENT_MARKS


# 「前に書いた返事のままでよい」の印（2026-11-09）。終わり際の関所（scripts/hook_*.py の Stop hook）に止められた後に
# 書いた文が、本人に届く返事の全部になる（Claude の result も Codex の最後の agent_message も最後の文だけ）。
# 11/9 17:55、関所の取り違えに「上の返事のままにします」とだけ答え、その一言がエディターの調べ結果の返事の代わりに
# 保存された。関所に止められて返事を変えない時は、この印だけを書く。保存の手前で、印の前に書いた最後の返事に戻す。
KEEP_MARK = "REPLY_UNCHANGED"


def _inner(text: Optional[str]) -> str:
    t = (text or "").strip()
    m = _WRAP.match(t)
    return (m.group(1) if m else t).strip()


def is_keep_reply(text: Optional[str]) -> bool:
    """本文が「前の返事のまま」の印だけか（印を包む飾りは除く）。"""
    return _inner(text) == KEEP_MARK


def is_marker_only(text: Optional[str]) -> bool:
    """画面へ流さない印だけの文か（伝えることは無い・前の返事のまま）。"""
    return is_silent_reply(text) or is_keep_reply(text)


def resolve_reply(text: Optional[str], parts: Optional[List[str]]) -> str:
    """本文が「前の返事のまま」の印なら、印の前に書いた最後の返事に戻す。前に返事が無ければ「伝えることは無い」の印。
    それ以外はそのまま。どのモデルの経路も、保存と画面への result の手前でこれを通す。"""
    if not is_keep_reply(text):
        return text or ""
    for part in reversed(parts or []):
        if part and part.strip() and not is_marker_only(part):
            # 印が前の文の末尾に続けて書かれた時（同じ文の塊）も、印の行は落とす
            return re.sub(r"\n*\s*`*\*?" + KEEP_MARK + r"\*?`*\s*$", "", part).rstrip() or part
    return SILENT_MARKS[0]
