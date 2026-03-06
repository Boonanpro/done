"""
Shared runtime contract renderer.

This keeps one versioned contract template and injects runtime tool/skill lists.
"""

from pathlib import Path
from typing import Sequence, Optional
import logging


RUNTIME_CONTRACT_TEMPLATE_PATH = Path(__file__).resolve().parent / "core_runtime_contract.md"

DEFAULT_RUNTIME_CONTRACT_TEMPLATE = (
    "## Available Tools\n\n"
    "### CLI Built-in Tools\n"
    "{{CLI_BUILTIN_TOOLS}}\n\n"
    "### MCP Tools\n"
    "{{MCP_TOOLS}}\n\n"
    "### Available Skills\n"
    "{{AVAILABLE_SKILLS}}\n"
)


def render_runtime_contract(
    *,
    cli_builtin_tools: Sequence[str],
    mcp_tools: Sequence[str],
    available_skills: Sequence[str],
    logger: Optional[logging.Logger] = None,
) -> str:
    """
    Render runtime contract from one template file with runtime replacements.
    """
    template = DEFAULT_RUNTIME_CONTRACT_TEMPLATE
    try:
        if RUNTIME_CONTRACT_TEMPLATE_PATH.exists():
            template = RUNTIME_CONTRACT_TEMPLATE_PATH.read_text(encoding="utf-8")
        elif logger:
            logger.warning(
                "Runtime contract template not found: %s",
                RUNTIME_CONTRACT_TEMPLATE_PATH,
            )
    except Exception as e:
        if logger:
            logger.warning("Failed to load runtime contract template: %s", e)

    replacements = {
        "{{CLI_BUILTIN_TOOLS}}": ", ".join(cli_builtin_tools) if cli_builtin_tools else "(none)",
        "{{MCP_TOOLS}}": ", ".join(mcp_tools) if mcp_tools else "(none)",
        "{{AVAILABLE_SKILLS}}": "\n".join(f"- {s}" for s in available_skills) if available_skills else "(none)",
    }
    for token, value in replacements.items():
        template = template.replace(token, value)

    return template

