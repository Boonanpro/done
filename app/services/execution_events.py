"""
Execution event taxonomy for process monitoring.

Policy:
- Keep event types stable for UI/monitoring.
- Do not constrain model behavior or wording.
"""

from __future__ import annotations

from typing import Optional, Tuple

ALLOWED_EVENT_TYPES = {
    "phase",
    "reasoning",
    "tool_use",
    "error",
    "step_verification",
    "done",
}


def normalize_event_type(event_type: Optional[str]) -> Tuple[str, Optional[str]]:
    """
    Normalize event type to the stable monitoring taxonomy.

    Returns:
        (normalized_type, original_type_if_changed)
    """
    value = (event_type or "").strip()
    if value in ALLOWED_EVENT_TYPES:
        return value, None
    return "phase", value or None

