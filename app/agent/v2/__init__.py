"""
Agent v2 compatibility exports.
"""

from __future__ import annotations

import warnings
from typing import Any

from app.agent.v2.session import Session, State

__all__ = ["Session", "State", "AgentRunner"]


def __getattr__(name: str) -> Any:
    if name == "AgentRunner":
        warnings.warn(
            "Importing AgentRunner from app.agent.v2 is deprecated. "
            "Use app.agent.cli_runner (or route-level CLI entrypoints) instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from app.agent.v2.runner import AgentRunner

        return AgentRunner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")