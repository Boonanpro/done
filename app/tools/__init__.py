"""
AI Agent Tools Package
"""
from typing import Optional
from app.tools.browser import (
    browse_website,
    fill_form,
    click_element,
    take_screenshot,
)
from app.tools.email_tool import (
    send_email,
    search_email,
    read_email,
)
from app.tools.line_tool import (
    send_line_message,
)
from app.tools.search import (
    search_web,
)
from app.tools.tavily_search import (
    tavily_search,
    search_with_tavily,
)
from app.tools.travel_search import (
    search_train,
    search_bus,
    search_flight,
)


# ツール名とツールのマッピング
TOOL_REGISTRY = {
    "browse_website": browse_website,
    "fill_form": fill_form,
    "click_element": click_element,
    "take_screenshot": take_screenshot,
    "send_email": send_email,
    "search_email": search_email,
    "read_email": read_email,
    "send_line_message": send_line_message,
    "search_web": search_web,
    "tavily_search": tavily_search,
    "search_train": search_train,
    "search_bus": search_bus,
    "search_flight": search_flight,
}


def get_tools(tool_names: Optional[list[str]] = None):
    """
    指定したツールを取得
    
    Args:
        tool_names: 取得するツール名のリスト。Noneの場合は空のリストを返す
    
    Returns:
        指定されたツールのリスト
    """
    if tool_names is None:
        return []
    
    tools = []
    for name in tool_names:
        if name in TOOL_REGISTRY:
            tools.append(TOOL_REGISTRY[name])
        else:
            raise ValueError(f"Unknown tool: {name}. Available tools: {list(TOOL_REGISTRY.keys())}")
    return tools


def get_all_tools():
    """全てのツールを取得（後方互換性のため維持）"""
    return list(TOOL_REGISTRY.values())


def get_available_tool_names() -> list[str]:
    """利用可能なツール名の一覧を取得"""
    return list(TOOL_REGISTRY.keys())


__all__ = [
    "get_tools",
    "get_all_tools",
    "get_available_tool_names",
    "TOOL_REGISTRY",
    "browse_website",
    "fill_form",
    "click_element",
    "take_screenshot",
    "send_email",
    "search_email",
    "read_email",
    "send_line_message",
    "search_web",
    "tavily_search",
    "search_with_tavily",
    "search_train",
    "search_bus",
    "search_flight",
]

