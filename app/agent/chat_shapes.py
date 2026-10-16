"""Answer shapes: the chat UI parts Dan may put in a reply (a comparison table, choice buttons,
one input, a list of steps, a chart) written as ```openui-lang blocks between sentences.

The instruction text is generated from the frontend's part definitions
(frontend/src/lib/chat-shapes/schema.ts → frontend/scripts/generate-chat-shapes-prompt.mjs) into
chat_shapes_prompt.md next to this file, so the parts the screen can draw and the parts Dan is told
about never drift apart. Every backend (Claude CLI, Codex) gets the same text through
cli_runner._build_system_prompt; Codex also folds it into its per-thread static hash."""
from __future__ import annotations

import logging
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

# --- mirror of frontend/src/lib/chat-shapes/plain.ts scanBlocks (CommonMark fences + HTML blocks) ---
# The screen computes a part's key from the code of each closed ```openui-lang block of the reply, in
# order (split.ts → answers.ts partKeys). The server re-derives the same keys to check that an answer
# points at a part that really is in that reply. Whitespace rules follow JavaScript (\s / trim),
# the hash runs over UTF-16 code units (charCodeAt). tests/fixtures/chat_shapes_part_keys.json pins both.

_JS_WS_CHARS = "\t\n\x0b\x0c\r " + "".join(map(chr, [0x00A0, 0x1680, *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF]))
_JS_WS_RUN = re.compile("[" + re.escape(_JS_WS_CHARS) + "]+")
_HAS_SHAPE_FENCE = re.compile(r"(^|\n) {0,3}(`{3,}|~{3,})[ \t]*(openui-lang|openui)(?=[ \t\r\n]|$)", re.I)
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
_HTML_RAW_START = re.compile(r"^<(script|pre|style|textarea)(?=[\s>]|$)", re.I)
_HTML_RAW_END = re.compile(r"</(script|pre|style|textarea)>", re.I)
_HTML_BLOCK_TAGS = frozenset("""address article aside base basefont blockquote body caption center col colgroup dd
details dialog dir div dl dt fieldset figcaption figure footer form frame frameset h1 h2 h3 h4 h5 h6 head header hr
html iframe legend li link main menu menuitem nav noframes ol optgroup option p param search section summary table
tbody td tfoot th thead title tr track ul""".split())
_HTML_TAG_START = re.compile(r"^</?([A-Za-z][A-Za-z0-9-]*)(?=[\s>]|/>|$)")
_HTML_OPEN_TAG = re.compile(r"^<[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z_:][A-Za-z0-9_.:-]*(?:\s*=\s*(?:[^\s\"'=<>`]+|'[^']*'|\"[^\"]*\"))?)*\s*/?>\s*$")
_HTML_CLOSE_TAG = re.compile(r"^</[A-Za-z][A-Za-z0-9-]*\s*>\s*$")


def _js_norm(s: str) -> str:
    """answers.ts norm(): s.replace(/\\s+/g, ' ').trim() with JavaScript's whitespace set."""
    return _JS_WS_RUN.sub(" ", s or "").strip(_JS_WS_CHARS)


def _js_blank(s: str) -> bool:
    return s.strip(_JS_WS_CHARS) == ""


def _strip_cr(line: str) -> str:
    return line[:-1] if line.endswith("\r") else line


def _fence_open(raw: str):
    line = _strip_cr(raw)
    m = _FENCE_OPEN.match(line)
    if not m:
        return None
    char, info = m.group(1)[0], m.group(2)
    if char == "`" and "`" in info:
        return None
    first = _js_norm(info).split(" ")[0]
    return {"char": char, "size": len(m.group(1)), "lang": first.lower()}


def _fence_close(raw: str, open_: dict) -> bool:
    m = _FENCE_CLOSE.match(_strip_cr(raw))
    return bool(m) and m.group(1)[0] == open_["char"] and len(m.group(1)) >= open_["size"]


def _html_block_start(line: str, after_blank: bool):
    t = re.sub(r"^ {0,3}", "", line, count=1)
    if not t.startswith("<"):
        return None
    if _HTML_RAW_START.match(t):
        return ("until", _HTML_RAW_END)
    if t.startswith("<!--"):
        return ("until", re.compile(r"-->"))
    if t.startswith("<?"):
        return ("until", re.compile(r"\?>"))
    if t.startswith("<![CDATA["):
        return ("until", re.compile(r"\]\]>"))
    if re.match(r"^<![A-Za-z]", t):
        return ("until", re.compile(r">"))
    m = _HTML_TAG_START.match(t)
    if m and m.group(1).lower() in _HTML_BLOCK_TAGS:
        return ("blank", None)
    if after_blank and (_HTML_OPEN_TAG.match(t) or _HTML_CLOSE_TAG.match(t)):
        return ("blank", None)
    return None


def scan_blocks(lines: list[str]) -> list[dict]:
    """Code blocks and HTML blocks of a reply, in order (plain.ts scanBlocks). Lines outside are prose."""
    out: list[dict] = []
    n = len(lines)
    i = 0
    after_blank = True
    while i < n:
        line = _strip_cr(lines[i])
        html = _html_block_start(line, after_blank)
        if html:
            kind, until = html
            if kind == "until":
                j = i
                while j < n and not until.search(_strip_cr(lines[j])):
                    j += 1
                j = min(j + 1, n)
                after_blank = False
            else:
                j = i + 1
                while j < n and not _js_blank(_strip_cr(lines[j])):
                    j += 1
                after_blank = True
            out.append({"kind": "html", "start": i, "end": j})
            i = j
            continue
        open_ = _fence_open(line)
        if open_:
            body: list[str] = []
            j = i + 1
            closed = False
            while j < n:
                if _fence_close(lines[j], open_):
                    closed = True
                    break
                body.append(_strip_cr(lines[j]))
                j += 1
            out.append({"kind": "fence", "start": i, "end": j + 1 if closed else j, "closed": closed, "fence": open_, "body": body})
            i = j + 1 if closed else j
            after_blank = False
            continue
        after_blank = _js_blank(line)
        i += 1
    return out


def shape_codes(text: str, streaming: bool = False) -> list[str]:
    """The code of each part of a reply, in the order the screen draws them (split.ts splitShapeSegments).
    Saved replies: closed blocks only (an unclosed block is broken and stays prose)."""
    if not text or not _HAS_SHAPE_FENCE.search(text):
        return []
    return ["\n".join(b["body"]) for b in scan_blocks(text.split("\n"))
            if b["kind"] == "fence" and b["fence"]["lang"] in SHAPE_FENCE_LANGS and (b["closed"] or streaming)]


def part_key(code: str, ordinal: int = 0) -> str:
    """answers.ts partKey: FNV-1a 32bit over the UTF-16 code units of the normalized code."""
    import struct
    h = 0x811C9DC5
    for (unit,) in struct.iter_unpack("<H", _js_norm(code).encode("utf-16-le", "surrogatepass")):
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
