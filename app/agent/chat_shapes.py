"""Answer shapes: the chat UI parts Dan may put in a reply (a comparison table, choice buttons,
one input, a list of steps, a chart) written as ```openui-lang blocks between sentences.

The instruction text is generated from the frontend's part definitions
(frontend/src/lib/chat-shapes/schema.ts → frontend/scripts/generate-chat-shapes-prompt.mjs) into
chat_shapes_prompt.md next to this file, so the parts the screen can draw and the parts Dan is told
about never drift apart. Every backend (Claude CLI, Codex) gets the same text through
cli_runner._build_system_prompt; Codex also folds it into its per-thread static hash."""
from __future__ import annotations

import logging
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
