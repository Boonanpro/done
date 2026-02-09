"""
Anthropic tool definitions → Gemini function_declarations converter.

Maps the existing tool definitions (used by Claude) into Gemini's
FunctionDeclaration format so the same tools work with both models.
"""

import copy
import logging
from typing import List, Dict, Any

from google.genai import types as genai_types

logger = logging.getLogger(__name__)


def _convert_schema(input_schema: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an Anthropic input_schema to Gemini-compatible OpenAPI schema.

    Gemini function declarations use OpenAPI 3.0-style schemas.
    The main differences:
    - Anthropic uses "input_schema", Gemini uses "parameters"
    - Both use standard JSON Schema / OpenAPI format internally
    - Remove unsupported fields if any
    """
    schema = copy.deepcopy(input_schema)

    # Gemini doesn't support 'additionalProperties' in some contexts
    schema.pop("additionalProperties", None)

    # Recursively clean properties
    properties = schema.get("properties", {})
    for prop_name, prop_def in properties.items():
        prop_def.pop("additionalProperties", None)
        # Ensure enum values are strings for Gemini
        if "enum" in prop_def:
            prop_def["enum"] = [str(v) for v in prop_def["enum"]]

    return schema


def anthropic_tool_to_gemini(tool: Dict[str, Any]) -> genai_types.FunctionDeclaration:
    """Convert a single Anthropic tool definition to a Gemini FunctionDeclaration.

    Args:
        tool: Anthropic tool dict with "name", "description", "input_schema"

    Returns:
        Gemini FunctionDeclaration
    """
    name = tool["name"]
    description = tool.get("description", "")
    input_schema = tool.get("input_schema", {"type": "object", "properties": {}})

    # Convert schema
    parameters = _convert_schema(input_schema)

    return genai_types.FunctionDeclaration(
        name=name,
        description=description,
        parameters=parameters,
    )


def convert_all_tools(anthropic_tools: List[Dict[str, Any]]) -> List[genai_types.Tool]:
    """Convert all Anthropic tool definitions to Gemini tools.

    Also adds google_search as a built-in tool (replaces Anthropic's web_search).

    Args:
        anthropic_tools: List of Anthropic tool dicts from get_all_skill_tools()

    Returns:
        List of Gemini Tool objects ready for Live API config
    """
    function_declarations = []

    for tool in anthropic_tools:
        # Skip Anthropic server-side tools (web_search)
        if tool.get("type", "").startswith("web_search"):
            continue

        try:
            fd = anthropic_tool_to_gemini(tool)
            function_declarations.append(fd)
        except Exception as e:
            logger.warning("Failed to convert tool '%s': %s", tool.get("name"), e)

    tools = []

    # Add function declarations as a single Tool
    if function_declarations:
        tools.append(genai_types.Tool(function_declarations=function_declarations))

    # Add Google Search as built-in tool (replaces Anthropic web_search)
    tools.append(genai_types.Tool(google_search=genai_types.GoogleSearch()))

    logger.info(
        "Converted %d function declarations + google_search",
        len(function_declarations),
    )
    return tools
