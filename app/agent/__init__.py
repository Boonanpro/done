"""AI Agent package exports.

Legacy v2 exports are kept for compatibility but loaded lazily so active
runtime paths do not import v2 runner at module import time.
"""

from __future__ import annotations

from typing import Any
import warnings

__all__ = ["AgentRunner", "create_runner"]


def __getattr__(name: str) -> Any:
    if name in {"AgentRunner", "create_runner"}:
        warnings.warn(
            "Importing AgentRunner/create_runner from app.agent is deprecated. "
            "Use app.agent.v2.runner directly while migration completes.",
            DeprecationWarning,
            stacklevel=2,
        )
        from app.agent.v2.runner import AgentRunner, create_runner

        return {"AgentRunner": AgentRunner, "create_runner": create_runner}[name]
    raise AttributeError(f"module 'app.agent' has no attribute '{name}'")
