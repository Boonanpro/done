"""
Shared runtime contract renderer.

This keeps one versioned contract template and injects runtime tool/skill lists.
"""

from pathlib import Path
from typing import Sequence, Optional
import logging


RUNTIME_CONTRACT_TEMPLATE_PATH = Path(__file__).resolve().parent / "core_runtime_contract.md"

DEFAULT_RUNTIME_CONTRACT_TEMPLATE = (
    "## Runtime Contract\n"
    "- You are Dan core. Keep one consistent behavior in this chat.\n"
    "- Use available tools first. If domain-specific procedure is needed, use check_skill.\n\n"
    "### CLI Built-in Tools\n"
    "{{CLI_BUILTIN_TOOLS}}\n\n"
    "### MCP Tools\n"
    "{{MCP_TOOLS}}\n\n"
    "### Available Skills\n"
    "{{AVAILABLE_SKILLS}}\n\n"
    "### Skill Usage Policy\n"
    "1. Call check_skill when a domain-specific flow is likely required.\n"
    "2. If no relevant skill exists, proceed with generic tools.\n"
    "3. Do not stop only because a skill is missing.\n"
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
        "{{AVAILABLE_SKILLS}}": ", ".join(available_skills) if available_skills else "(none)",
    }
    for token, value in replacements.items():
        template = template.replace(token, value)

    return template

