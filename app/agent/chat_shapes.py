"""Answer shapes: the chat UI parts Dan may put in a reply (a comparison table, choice buttons,
one input, a list of steps, a chart) written as ```openui-lang blocks between sentences.

The instruction text is generated from the frontend's part definitions
(frontend/src/lib/chat-shapes/schema.ts → frontend/scripts/generate-chat-shapes-prompt.mjs) into
chat_shapes_prompt.md next to this file, so the parts the screen can draw and the parts Dan is told
about never drift apart. Every backend (Claude CLI, Codex) gets the same text through
cli_runner._build_system_prompt; Codex also folds it into its per-thread static hash."""
from __future__ import annotations

import logging
import math
import re
from pathlib import Path

logger = logging.getLogger(__name__)

CHAT_SHAPES_PROMPT_PATH = Path(__file__).resolve().parent / "chat_shapes_prompt.md"

# The fence language the screen looks for (frontend/src/lib/chat-shapes/split.ts).
SHAPE_FENCE_LANG = "openui-lang"


def chat_shapes_section() -> str:
    """The system-prompt section, or "" when the generated file is missing (Dan then simply
    answers in prose; nothing else changes)."""
    try:
        text = CHAT_SHAPES_PROMPT_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.warning("chat shapes prompt not found: %s", CHAT_SHAPES_PROMPT_PATH)
        return ""
    except Exception as e:  # noqa: BLE001
        logger.warning("chat shapes prompt unreadable: %s", e)
        return ""
    if f"`{SHAPE_FENCE_LANG}`" not in text:
        logger.warning("chat shapes prompt does not mention the %s fence; ignoring it", SHAPE_FENCE_LANG)
        return ""
    return text


# ---------------------------------------------------------------------------------------------------
# The owner's answer to a part: the contract shared with the screen.
#
# A pressed Choice / submitted Input is saved as the owner's message「<問い> → <答え>」 plus
# ai_context.answer_to = {message_id, part, kind, value, question?} (chat_routes._answer_to_context,
# chat_schemas.AnswerToLink). The limits below are the same on both sides (frontend
# src/lib/chat-shapes/schema.ts exports the same numbers; tests/test_chat_shapes_answer_to.py pins them):
# a part the screen draws never has an option / label longer than these, the input box refuses longer
# values, the server rejects (never silently cuts) anything longer, and the screen matches on the full value.
# ---------------------------------------------------------------------------------------------------

ANSWER_VALUE_MAX = 200       # a Choice option / an Input value with its unit (answer_to.value)
ANSWER_QUESTION_MAX = 200    # a Choice question / an Input label (answer_to.question)
# answers.ts partKey: "p" + FNV-1a (32bit, hex) of the part's code, "-<n>" for the n-th identical code
PART_KEY_RE = re.compile(r"^p[0-9a-f]{8}(?:-[1-9][0-9]*)?$")
SHAPE_FENCE_LANGS = frozenset({"openui-lang", "openui"})

# ---------------------------------------------------------------------------------------------------
# Where the parts of a reply are: a line-for-line mirror of frontend/src/lib/chat-shapes/plain.ts
# topLevelFences, which copies the steps of the screen's Markdown reader remark-parse + remark-gfm (micromark): a
# part is a fenced code block at the top level of the document (not inside a block quote, a list item or a GFM
# footnote definition) whose language is exactly openui-lang / openui. The rules are written out in plain.ts's
# header; in short:
# - lines end at \n, \r\n or \r; a BOM at the very start is skipped; NUL reads as U+FFFD
# - whitespace is the space and the tab only (NBSP, ideographic space, NEL, BOM, U+2028... are ordinary
#   characters). A tab advances to the next multiple of 4 columns; indentation is counted in columns.
#   Python's str.strip / \s are never used for Markdown syntax
# - containers (> and list items) with lazy continuation; what may interrupt a paragraph (headings, thematic
#   breaks, setext underlines, HTML kinds 1-6, fences; HTML kind 7 only on a lazy line); indented code;
#   link reference definitions (a setext underline after definitions only is a new paragraph)
# - GFM: tables (a head row + delimiter row interrupts a paragraph; what may follow a table) and footnote
#   definitions (a container that may interrupt a paragraph, continued by blank or 4-column indented lines)
# tests/fixtures/chat_shapes_markdown_corpus.json (written from remark-parse + remark-gfm's own syntax tree) pins
# this file, plain.ts, its mobile copy and remark-parse + remark-gfm to the same answers.
# ---------------------------------------------------------------------------------------------------

_HT = -2   # a tab: HT, then VS up to the next tab stop (micromark's preprocessing)
_VS = -1
_EOLC = -4  # line break inside a paragraph's content (link reference definitions)


class _Line:
    __slots__ = ("codes", "chars", "start", "end", "next", "eol")

    def __init__(self, codes, chars, start, end, next_, eol):
        self.codes, self.chars, self.start, self.end, self.next, self.eol = codes, chars, start, end, next_, eol


def _read_lines(text: str) -> list[_Line]:
    lines: list[_Line] = []
    n = len(text)
    i = 1 if text[:1] == "\ufeff" else 0
    while i < n:
        start = i
        codes: list[int] = []
        chars: list[str] = []
        column = 1
        while i < n:
            ch = text[i]
            if ch in "\n\r":
                break
            if ch == "\t":
                stop = math.ceil(column / 4) * 4
                codes.append(_HT)
                chars.append("\t")
                while column < stop:
                    column += 1
                    codes.append(_VS)
                    chars.append("")
                column += 1
            elif ch == "\0":
                codes.append(0xFFFD)
                chars.append("\ufffd")
                column += 1
            else:
                codes.append(ord(ch))
                chars.append(ch)
                column += 2 if ord(ch) > 0xFFFF else 1   # columns are counted in UTF-16 units, like the screen
            i += 1
        end = i
        eol = "\r\n" if text[i:i + 2] == "\r\n" else text[i:i + 1]
        i += len(eol)
        lines.append(_Line(codes, chars, start, end, i, eol))
    return lines


def _at(c: list[int], i: int):
    return c[i] if 0 <= i < len(c) else None


def _is_space(c) -> bool:
    return c == 32 or c == _HT or c == _VS


def _is_digit(c) -> bool:
    return c is not None and 48 <= c <= 57


def _is_alpha(c) -> bool:
    return c is not None and (65 <= c <= 90 or 97 <= c <= 122)


def _is_alnum(c) -> bool:
    return _is_digit(c) or _is_alpha(c)


def _spaces(c: list[int], p: int, limit: float = math.inf) -> int:
    n = 0
    while n < limit and _is_space(_at(c, p + n)):
        n += 1
    return n


def _blank_from(c: list[int], p: int) -> bool:
    return p + _spaces(c, p) >= len(c)


def _slice(L: _Line, p: int, q: int | None = None) -> str:
    out = []
    at_tab = False
    for k in range(p, len(L.codes) if q is None else min(q, len(L.codes))):
        code = L.codes[k]
        if code == _VS:
            if at_tab:
                continue
            out.append(" ")
        else:
            out.append(L.chars[k])
        at_tab = code == _HT
    return "".join(out)


_ESCAPE_OR_REFERENCE = re.compile(r"\\([!-/:-@\[-`{-~])|&(#(?:[0-9]{1,7}|[xX][0-9A-Fa-f]{1,6})|[0-9A-Za-z]{1,31});")


def _numeric_reference(n: int) -> str:
    if (n < 9 or n == 11 or 13 < n < 32 or 126 < n < 160 or 55295 < n < 57344 or 64975 < n < 65008
            or (n & 65535) == 65535 or (n & 65535) == 65534 or n > 1114111):
        return "\ufffd"
    return chr(n)


def _decode_string(s: str) -> str:
    def decode(m: re.Match) -> str:
        if m.group(1):
            return m.group(1)
        ref = m.group(2)
        if ref[0] == "#":
            hexa = ref[1] in "xX"
            return _numeric_reference(int(ref[2:] if hexa else ref[1:], 16 if hexa else 10))
        return m.group(0)   # named references stay as written: none of them decodes to openui-lang / openui
    return _ESCAPE_OR_REFERENCE.sub(decode, s)


def _thematic_break_at(c: list[int], q: int) -> bool:
    marker = c[q]
    count = 0
    i = q
    while i < len(c):
        if c[i] == marker:
            count += 1
        elif not _is_space(c[i]):
            return False
        i += 1
    return count >= 3


def _atx_at(c: list[int], q: int) -> bool:
    n = 0
    while _at(c, q + n) == 35:
        n += 1
    if n > 6:
        return False
    after = _at(c, q + n)
    return after is None or _is_space(after)


def _setext_at(c: list[int], q: int) -> bool:
    marker = c[q]
    i = q
    while _at(c, i) == marker:
        i += 1
    return _blank_from(c, i)


class _Fence:
    __slots__ = ("marker", "size_open", "prefix", "lang", "top", "start_line", "last_line", "lines", "eols")

    def __init__(self, marker, size_open, prefix, lang, line):
        self.marker, self.size_open, self.prefix, self.lang = marker, size_open, prefix, lang
        self.top, self.start_line, self.last_line, self.lines, self.eols = False, line, line, [], []


def _fence_at(L: _Line, q: int, prefix: int, line: int):
    c = L.codes
    marker = c[q]
    i = q
    while _at(c, i) == marker:
        i += 1
    size_open = i - q
    if size_open < 3:
        return None
    i += _spaces(c, i)
    info_start = i
    while i < len(c) and not _is_space(c[i]):
        if marker == 96 and c[i] == 96:
            return None
        i += 1
    info = _slice(L, info_start, i)
    while i < len(c):
        if marker == 96 and c[i] == 96:
            return None
        i += 1
    return _Fence(marker, size_open, prefix, _decode_string(info), line)


def _closes_fence(c: list[int], p: int, f: _Fence) -> bool:
    i = p + _spaces(c, p, 3)
    if _at(c, i) != f.marker:
        return False
    n = 0
    while _at(c, i) == f.marker:
        i += 1
        n += 1
    return n >= f.size_open and _blank_from(c, i)


_HTML_RAW = frozenset({"pre", "script", "style", "textarea"})
_HTML_BLOCK = frozenset("""address article aside base basefont blockquote body caption center col colgroup dd
details dialog dir div dl dt fieldset figcaption figure footer form frame frameset h1 h2 h3 h4 h5 h6 head header hr
html iframe legend li link main menu menuitem nav noframes ol optgroup option p param search section summary table
tbody td tfoot th thead title tr track ul""".split())
_HTML_END = {
    1: re.compile(r"</(?:script|pre|style|textarea)>", re.I | re.A), 2: re.compile(r"-->"), 3: re.compile(r"\?>"),
    4: re.compile(r">"), 5: re.compile(r"\]\]>"),
}


def _complete_tag(c: list[int], i: int, closing: bool) -> bool:
    if closing:
        i += _spaces(c, i)
        return _at(c, i) == 62 and _blank_from(c, i + 1)
    s = "nameBefore"
    while True:
        ch = _at(c, i)
        if s == "nameBefore":
            if ch == 47:
                i += 1
                s = "end"
            elif ch == 58 or ch == 95 or _is_alpha(ch):
                i += 1
                s = "name"
            elif _is_space(ch):
                i += 1
            else:
                s = "end"
        elif s == "name":
            if ch in (45, 46, 58, 95) or _is_alnum(ch):
                i += 1
            else:
                s = "nameAfter"
        elif s == "nameAfter":
            if ch == 61:
                i += 1
                s = "valueBefore"
            elif _is_space(ch):
                i += 1
            else:
                s = "nameBefore"
        elif s == "valueBefore":
            if ch is None or ch in (60, 61, 62, 96):
                return False
            if ch == 34 or ch == 39:
                i += 1
                while _at(c, i) != ch:
                    if i >= len(c):
                        return False
                    i += 1
                i += 1
                s = "quotedAfter"
            elif _is_space(ch):
                i += 1
            else:
                s = "unquoted"
        elif s == "unquoted":
            if ch is None or ch in (34, 39, 47, 60, 61, 62, 96) or _is_space(ch):
                s = "nameAfter"
            else:
                i += 1
        elif s == "quotedAfter":
            if ch == 47 or ch == 62 or _is_space(ch):
                s = "nameBefore"
            else:
                return False
        else:   # end
            return ch == 62 and _blank_from(c, i + 1)


def _html_at(L: _Line, q: int, interrupt: bool, lazy: bool) -> int:
    c = L.codes
    i = q + 1
    if _at(c, i) == 33:
        if _at(c, i + 1) == 45:
            return 2 if _at(c, i + 2) == 45 else 0
        if _at(c, i + 1) == 91:
            return 5 if _slice(L, i + 2, i + 8) == "CDATA[" else 0
        return 4 if _is_alpha(_at(c, i + 1)) else 0
    if _at(c, i) == 63:
        return 3
    closing = _at(c, i) == 47
    if closing:
        i += 1
    if not _is_alpha(_at(c, i)):
        return 0
    name = []
    while _at(c, i) == 45 or _is_alnum(_at(c, i)):
        name.append(L.chars[i])
        i += 1
    after = _at(c, i)
    if not (after is None or after == 47 or after == 62 or _is_space(after)):
        return 0
    lower = "".join(name).lower()
    if after != 47 and not closing and lower in _HTML_RAW:
        return 1
    if lower in _HTML_BLOCK:
        return (6 if _at(c, i + 1) == 62 else 0) if after == 47 else 6
    if interrupt and not lazy:
        return 0
    return 7 if _complete_tag(c, i, closing) else 0


def _quote_at(c: list[int], p: int) -> int:
    q = p + _spaces(c, p, 3)
    if _at(c, q) != 62:
        return -1
    return q + 2 if _is_space(_at(c, q + 1)) else q + 1


class _List:
    __slots__ = ("ordered", "marker", "size", "initial_blank_line", "further_blank_lines", "close_flow")

    def __init__(self, ordered, marker, size, initial_blank_line):
        self.ordered, self.marker, self.size = ordered, marker, size
        self.initial_blank_line, self.further_blank_lines, self.close_flow = initial_blank_line, False, False


def _list_at(c: list[int], p: int, cur: _List | None, interrupt: bool):
    initial = _spaces(c, p, 3)
    q = p + initial
    prefix_start = q
    ch = _at(c, q)
    bullet = ch in (42, 43, 45)
    ordered = cur.ordered if cur else not bullet
    if not ordered:
        if (ch != cur.marker) if cur else not bullet:
            return None
        if ch in (42, 45) and _thematic_break_at(c, q):
            return None
    else:
        if not _is_digit(ch):
            return None
        if interrupt and ch != 49:
            return None
        size = 0
        while _is_digit(_at(c, q)):
            size += 1
            if size >= 10:
                break
            q += 1
        d = _at(c, q)
        if not ((not interrupt or size < 2) and ((d == cur.marker) if cur else d in (41, 46))):
            return None
    marker = c[q]
    q += 1
    initial_size = initial
    initial_blank_line = False
    if _blank_from(c, q):
        if interrupt:
            return None   # an empty item cannot interrupt a paragraph
        initial_blank_line = True
        initial_size += 1
    else:
        w = _spaces(c, q, 4)
        if w >= 1 and not _is_space(_at(c, q + w)):
            q += w
        elif _is_space(_at(c, q)):
            q += 1
        else:
            return None
    return q, _List(ordered, cur.marker if cur else marker, initial_size + (q - prefix_start), initial_blank_line)


def _list_continue(st: _List, c: list[int], p: int) -> int:
    st.close_flow = False
    if _blank_from(c, p):
        st.further_blank_lines = st.further_blank_lines or st.initial_blank_line
        return p + _spaces(c, p, st.size)
    further = st.further_blank_lines
    st.further_blank_lines = False
    st.initial_blank_line = False
    if not further and _is_space(_at(c, p)):
        n = _spaces(c, p, st.size)
        if n == st.size:
            return p + n
    st.close_flow = True
    nxt = _list_at(c, p, st, False)
    if not nxt:
        return -1
    q, item = nxt
    st.ordered, st.marker, st.size = item.ordered, item.marker, item.size
    st.initial_blank_line, st.further_blank_lines, st.close_flow = item.initial_blank_line, False, True
    return q


def _footnote_at(c: list[int], p: int) -> int:
    """GFM footnote definition marker (micromark-extension-gfm-footnote): up to 3 spaces, [^label]: with a non-empty
    label without space, tab, [ or line end (\\ before [ \\ ] keeps them in the label); the whitespace after : is part
    of the marker. It can interrupt a paragraph. The position after it, or -1."""
    i = p + _spaces(c, p, 3)
    if _at(c, i) != 91 or _at(c, i + 1) != 94:
        return -1
    i += 2
    size = 0
    while True:
        ch = _at(c, i)
        if size > 999 or (ch == 93 and size == 0) or ch is None or ch == 91 or _is_space(ch):
            return -1
        if ch == 93:
            i += 1
            break
        size += 1
        i += 1
        if ch == 92 and _at(c, i) in (91, 92, 93):
            size += 1
            i += 1
    if _at(c, i) != 58:
        return -1
    i += 1
    return i + _spaces(c, i)


def _footnote_continue(c: list[int], p: int) -> int:
    """A footnote definition goes on over a blank line, or a line indented exactly 4 columns (taken as its marker)."""
    if _blank_from(c, p):
        return p
    return p + 4 if _spaces(c, p, 4) == 4 else -1


def _container_at(c: list[int], p: int, interrupt: bool):
    ch = _at(c, p + _spaces(c, p, 3))
    if ch == 62:
        return _quote_at(c, p), "quote"
    if ch in (42, 43, 45) or _is_digit(ch):
        return _list_at(c, p, None, interrupt)
    if ch == 91:
        q = _footnote_at(c, p)
        return None if q < 0 else (q, "footnote")
    return None


# GFM tables (micromark-extension-gfm-table syntax.js; the screen draws with remark-gfm). A table starts with a head
# row and the next line, a delimiter row (- : | only, at least one | or :, as many cells as the head), and can
# interrupt a paragraph. The delimiter row may not be a lazy line. After it, a line ends the table if it is blank or
# lazy; otherwise it is whatever can start there (heading, thematic break, HTML of any kind, fence, indented code,
# containers including empty items and 2.) or else a row of the table.

def _table_head_at(c: list[int], q: int) -> int:
    """The number of cells of a head row starting at q (after its indent), or 0 if it is not one."""
    i = q
    size = 0
    size_b = 0
    seen = False
    if _at(c, i) != 124:
        seen = True   # the first character that is not | counts twice
        size_b += 1
    while True:
        ch = _at(c, i)
        if ch is None:
            return size if size_b > 1 else 0
        if _is_space(ch):
            i += 1
            continue
        size_b += 1
        if seen:
            seen = False
            size += 1
        if ch == 124:
            seen = True
            i += 1
            continue
        while True:   # cell data up to | / space / end; \ before \ or | keeps it in the data
            d = _at(c, i)
            if d is None or d == 124 or _is_space(d):
                break
            i += 1
            if d == 92 and _at(c, i) in (92, 124):
                i += 1


def _table_delimiter_at(c: list[int], p: int) -> int:
    """The number of cells of a delimiter row at p (after the container markers), or -1 if it is not one."""
    i = p + _spaces(c, p, 3)
    size_b = 0
    seen = False
    if _at(c, i) == 124:
        seen = True
        i += 1
        i += _spaces(c, i)
    elif _at(c, i) not in (45, 58):
        return -1
    while True:
        ch = _at(c, i)
        if ch in (58, 45):
            size_b += 1
            if ch == 58:
                seen = True
                i += 1
                if _at(c, i) != 45:
                    return -1
            while _at(c, i) == 45:
                i += 1
            if _at(c, i) == 58:
                seen = True
                i += 1
            i += _spaces(c, i)
        elif ch is not None:
            return -1
        if _at(c, i) == 124:
            seen = True
            i += 1
            i += _spaces(c, i)
            if _at(c, i) is None:
                break
            if _at(c, i) not in (45, 58):
                return -1
            continue
        if _at(c, i) is None:
            break
        return -1
    return size_b if seen else -1


def _is_control(c) -> bool:
    return c is not None and (c < 32 or c == 127)


def _after_line(c: list[int], i: int) -> int:
    while _is_space(_at(c, i)):
        i += 1
    return i if _at(c, i) in (None, _EOLC) else -1


def _definition_at(c: list[int], i: int) -> int:
    if _at(c, i) != 91:
        return -1
    i += 1
    size = 0
    seen = False
    while True:
        ch = _at(c, i)
        if size > 999 or ch is None or ch == 91 or (ch == 93 and not seen):
            return -1
        if ch == 93:
            i += 1
            break
        if ch == _EOLC:
            i += 1
            continue
        while True:
            d = _at(c, i)
            if d is None or d in (91, 93, _EOLC):
                break
            size += 1
            if size - 1 > 999:
                break
            i += 1
            if not seen:
                seen = not _is_space(d)
            if d == 92 and _at(c, i) in (91, 92, 93):
                i += 1
                size += 1
    if _at(c, i) != 58:
        return -1
    i += 1
    while _at(c, i) == _EOLC or _is_space(_at(c, i)):
        i += 1
    if _at(c, i) == 60:
        i += 1
        while True:
            d = _at(c, i)
            if d == 62:
                i += 1
                break
            if d is None or d == 60 or d == _EOLC:
                return -1
            i += 1
            if d == 92 and _at(c, i) in (60, 62, 92):
                i += 1
    else:
        first = _at(c, i)
        if first is None or first == 32 or first == 41 or _is_control(first):
            return -1
        balance = 0
        while True:
            d = _at(c, i)
            if not balance and (d is None or d == 41 or d == _EOLC or _is_space(d)):
                break
            if d == 40:
                i += 1
                balance += 1
                continue
            if d == 41:
                i += 1
                balance -= 1
                continue
            if d is None or d == 32 or _is_control(d):
                return -1
            i += 1
            if d == 92 and _at(c, i) in (40, 41, 92):
                i += 1
    after_destination = i
    if _at(c, i) == _EOLC or _is_space(_at(c, i)):
        while _at(c, i) == _EOLC or _is_space(_at(c, i)):
            i += 1
        opener = _at(c, i)
        if opener in (34, 39, 40):
            close = 41 if opener == 40 else opener
            i += 1
            while True:
                d = _at(c, i)
                if d == close:
                    i += 1
                    break
                if d is None:
                    i = -1
                    break
                i += 1
                if d == 92 and _at(c, i) in (close, 92):
                    i += 1
            end = -1 if i < 0 else _after_line(c, i)
            if end >= 0:
                return end
    return _after_line(c, after_destination)


def _definitions_only(c: list[int]) -> bool:
    i = 0
    while True:
        j = _definition_at(c, i)
        if j < 0:
            return False
        if j >= len(c):
            return True
        i = j + 1
        while _is_space(_at(c, i)):
            i += 1


def top_level_fences(text: str) -> list[dict]:
    """The fenced code blocks at the top level of a reply, in order, any language (plain.ts topLevelFences).
    Each is {start, end, next, closed, lang, code}; start/end/next are positions in `text`; an unclosed
    block runs to the end of the text."""
    lines = _read_lines(text)
    out: list[dict] = []
    stack: list = []
    st = {"cur": None, "has_flow": False}

    def finish_fence(f: _Fence, closed_at):
        if not f.top:
            return
        last = f.last_line if closed_at is None else closed_at
        n = len(f.lines) - 1 if (closed_at is None and f.lines and f.lines[-1] == "" and f.eols[-1] == "") else len(f.lines)
        code = "".join(s + f.eols[k] if k < n - 1 else s for k, s in enumerate(f.lines[:n]))
        out.append({"start": lines[f.start_line].start, "end": lines[last].end, "next": lines[last].next,
                    "closed": closed_at is not None, "lang": f.lang, "code": code})

    def close_flow():
        if isinstance(st["cur"], _Fence):
            finish_fence(st["cur"], None)
        st["cur"] = None
        st["has_flow"] = False

    def open_containers(c, p, interrupt):
        while True:
            r = _container_at(c, p, interrupt)
            if not r:
                return p
            stack.append(r[1])
            p = r[0]

    def interrupts(L, q, lazy):
        c = L.codes
        ch = _at(c, q)
        if ch == 35:
            return "other" if _atx_at(c, q) else None
        if ch in (42, 95):
            return "other" if _thematic_break_at(c, q) else None
        if ch == 45:
            return "setext" if (not lazy and _setext_at(c, q)) else ("other" if _thematic_break_at(c, q) else None)
        if ch == 61:
            return "setext" if (not lazy and _setext_at(c, q)) else None
        if ch == 60:
            k = _html_at(L, q, True, lazy)
            return "html7" if k == 7 else ("other" if k else None)
        if ch in (96, 126):
            return "other" if _fence_at(L, q, 0, -1) else None
        return None

    def head_of(L, q, pre):
        # a paragraph line seen as a table head row: its number of cells (0: not one), and whether outside a
        # paragraph it would start an HTML block of kind 7 (then that block wins over the table)
        if pre >= 4:
            return 0, False
        return _table_head_at(L.codes, q), _html_at(L, q, False, False) == 7

    def fresh(li, L, p, lazy, after_paragraph, in_table=False):
        # in_table: the line after a table (a row of it unless something else starts there)
        c = L.codes
        if _blank_from(c, p):
            st["cur"] = None
            return
        # indented code; one that starts on a lazy line ends with that line (micromark checks "is this line
        # lazy" at the line ending before looking at the next line)
        if _is_space(_at(c, p)) and _spaces(c, p, 4) >= 4:
            st["cur"] = None if lazy else ("indented",)
            return
        pre = _spaces(c, p)
        q = p + pre
        ch = _at(c, q)
        if ch == 35 and _atx_at(c, q):
            st["cur"] = None
            return
        if ch in (42, 95) and _thematic_break_at(c, q):
            st["cur"] = None
            return
        if ch == 45 and ((after_paragraph and not lazy and _setext_at(c, q)) or _thematic_break_at(c, q)):
            st["cur"] = None
            return
        if ch == 61 and after_paragraph and not lazy and _setext_at(c, q):
            st["cur"] = None
            return
        if ch == 60:
            kind = _html_at(L, q, False, lazy)
            if kind:
                st["cur"] = None if (kind <= 5 and _HTML_END[kind].search(_slice(L, q))) else ("html", kind)
                return
        if ch in (96, 126):
            f = _fence_at(L, q, pre, li)
            if f:
                st["cur"] = f
                return
        if in_table:
            st["cur"] = ("table",)
            return
        # a paragraph: ["content", codes, head cells of its last line, that line starts HTML kind 7]
        st["cur"] = ["content", c[q:], *head_of(L, q, 0)]

    def feed(li, L, p, lazy) -> bool:
        c = L.codes
        after_paragraph = False
        now = st["cur"]
        if now is not None:
            if isinstance(now, _Fence):
                if lazy:
                    finish_fence(now, None)
                    st["cur"] = None
                elif _closes_fence(c, p, now):
                    finish_fence(now, li)
                    st["cur"] = None
                    return False
                else:
                    q = p + _spaces(c, p, now.prefix) if now.prefix > 0 else p
                    now.lines.append(_slice(L, q))
                    now.eols.append(L.eol)
                    now.last_line = li
                    return False
            elif now[0] == "content":
                if _blank_from(c, p):
                    st["cur"] = None
                elif not lazy and now[2] > 0 and _table_delimiter_at(c, p) == now[2]:
                    # a GFM table: the paragraph's last line is its head, this line its delimiter row; the paragraph
                    # ends before the head. If the head line starts HTML of kind 7, that HTML block starts there
                    # instead (up to a blank line, this line included)
                    st["cur"] = ("html", 7) if now[3] else ("table",)
                    return False
                else:
                    pre = _spaces(c, p)
                    r = None if pre >= 4 else interrupts(L, p + pre, lazy)
                    if not r:
                        now[1].append(_EOLC)
                        now[1].extend(c[p:])
                        now[2], now[3] = head_of(L, p + pre, pre)
                        return True
                    st["cur"] = None
                    if r == "html7":
                        st["cur"] = ("html", 7)   # stays in the containers this line (micromark resolves it later)
                        return True
                    after_paragraph = r == "setext" and not _definitions_only(now[1])
            elif now[0] == "indented":
                if not lazy and (_blank_from(c, p) or _spaces(c, p, 4) >= 4):
                    return False
                st["cur"] = None
            elif now[0] == "table":
                # a table ends at a blank line; a lazy line is never a row; another line is a row unless
                # something else starts there
                if _blank_from(c, p) or lazy:
                    st["cur"] = None
                else:
                    fresh(li, L, p, False, False, True)
                    return False
            elif now[1] in (6, 7) and _blank_from(c, p):
                st["cur"] = None
            elif lazy:
                st["cur"] = None
            else:
                if now[1] <= 5 and _HTML_END[now[1]].search(_slice(L, p)):
                    st["cur"] = None
                return False
        fresh(li, L, p, lazy, after_paragraph)
        return False

    def flow_line(li, L, p, lazy, continued):
        st["has_flow"] = True
        keep = feed(li, L, p, lazy)
        if lazy and not keep:
            del stack[continued:]
        now = st["cur"]
        if isinstance(now, _Fence) and now.start_line == li:
            now.top = not stack

    for li, L in enumerate(lines):
        c = L.codes
        p = 0
        continued = 0
        while continued < len(stack):
            k = stack[continued]
            q = _quote_at(c, p) if k == "quote" else _footnote_continue(c, p) if k == "footnote" else _list_continue(k, c, p)
            if q < 0:
                break
            p = q
            continued += 1
            if isinstance(k, _List) and k.close_flow:   # the next item of the same list: close the previous item's flow
                k.close_flow = False
                close_flow()
                del stack[continued:]
                break
        interrupt = False
        if continued == len(stack):
            if not st["has_flow"]:
                flow_line(li, L, open_containers(c, p, False), False, continued)
                continue
            now = st["cur"]
            if isinstance(now, _Fence) or (now is not None and now[0] == "html"):
                flow_line(li, L, p, False, continued)
                continue
            interrupt = now is not None and now[0] != "table"   # after a table, empty items and 2. lists may start
        if _container_at(c, p, interrupt):
            close_flow()
            del stack[continued:]
            flow_line(li, L, open_containers(c, p, interrupt), False, len(stack))
        else:
            flow_line(li, L, p, continued != len(stack), continued)
    close_flow()
    return out


def shape_codes(text: str, streaming: bool = False) -> list[str]:
    """The code of each part of a reply, in the order the screen draws them (split.ts splitShapeSegments →
    plain.ts shapeFences). Saved replies: closed blocks only (an unclosed block is broken and stays prose)."""
    if not text or ("```" not in text and "~~~" not in text):
        return []
    return [f["code"] for f in top_level_fences(text) if f["lang"] in SHAPE_FENCE_LANGS and (f["closed"] or streaming)]


# --- the part key (answers.ts partKey / partKeys) ------------------------------------------------------
# Not Markdown syntax: the key normalizes the part's code like answers.ts norm(), whose whitespace set is the
# same explicit list (JavaScript's \s: tab, LF, VT, FF, CR, space, NBSP, U+1680, U+2000-U+200A, U+2028, U+2029,
# U+202F, U+205F, U+3000, U+FEFF), and hashes UTF-16 code units (charCodeAt).
KEY_SPACE_CHARS = "\t\n\x0b\x0c\r " + "".join(map(chr, [0x00A0, 0x1680, *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF]))
_KEY_SPACE_RUN = re.compile("[" + re.escape(KEY_SPACE_CHARS) + "]+")


def _key_norm(s: str) -> str:
    return _KEY_SPACE_RUN.sub(" ", s or "").strip(KEY_SPACE_CHARS)


def part_key(code: str, ordinal: int = 0) -> str:
    """answers.ts partKey: FNV-1a 32bit over the UTF-16 code units of the normalized code."""
    import struct
    h = 0x811C9DC5
    for (unit,) in struct.iter_unpack("<H", _key_norm(code).encode("utf-16-le", "surrogatepass")):
        h ^= unit
        h = (h * 0x01000193) & 0xFFFFFFFF
    return f"p{h:08x}" + (f"-{ordinal}" if ordinal else "")


def part_keys(codes: list[str]) -> list[str]:
    """answers.ts partKeys: identical codes in one reply get -1, -2, … in order."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for code in codes:
        base = part_key(code)
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.append(f"{base}-{n}" if n else base)
    return out


def part_in_reply(texts, part: str) -> bool:
    """Does `part` (a key the screen made) name a part of this reply? `texts` is the reply's content and,
    when it was saved with blocks, each text block (the screen keys parts per rendered text; the hash is
    the same either way, so the check is on the hash and tolerant of where the ordinal was counted)."""
    if not isinstance(part, str) or not PART_KEY_RE.match(part):
        return False
    base, _, suffix = part.partition("-")
    n = int(suffix) if suffix else 0
    if isinstance(texts, str):
        texts = [texts]
    count = 0
    for text in texts:
        count = max(count, sum(1 for code in shape_codes(text or "") if part_key(code) == base))
    return n < count
