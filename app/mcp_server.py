"""
MCP Server - DAN の全ツールを MCP プロトコルで公開

Agent SDK から stdio 接続で使用される。
コンテキスト（user_id, session_id, credentials）は環境変数で受け取る。

起動方法（Agent SDK が自動で起動）:
    python app/mcp_server.py
"""

import os
import sys
import json
import asyncio
import logging

# プロジェクトルートをパスに追加（import 用）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

logger = logging.getLogger(__name__)

# コンテキスト: 環境変数から取得
USER_ID = os.environ.get("DAN_USER_ID", "")
SESSION_ID = os.environ.get("DAN_SESSION_ID", "")
CREDENTIALS = json.loads(os.environ.get("DAN_CREDENTIALS", "{}"))

app = Server("dan-tools")


# CLI組込ツールと重複するため MCP では公開しないツール
# CLI の Read/Write/Edit/Bash の方が高品質なのでそちらを使わせる
_CLI_BUILTIN_TOOLS = {"read_file", "write_file", "edit_file", "bash"}


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """既存のツール定義を MCP 形式に変換して返す（CLI重複分は除外）"""
    from app.agent.v2.tools import get_all_skill_tools

    anthropic_tools = get_all_skill_tools()
    mcp_tools = []
    for tool in anthropic_tools:
        if tool["name"] in _CLI_BUILTIN_TOOLS:
            continue
        mcp_tools.append(
            types.Tool(
                name=tool["name"],
                description=tool.get("description", ""),
                inputSchema=tool.get("input_schema", {"type": "object", "properties": {}}),
            )
        )
    return mcp_tools


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent | types.ImageContent]:
    """ツールを実行し、結果を MCP コンテンツとして返す"""
    from app.agent.v2.tools import execute_tool, parse_tool_name, format_tool_result, SkillRegistry

    # ツール名をパース
    parsed = parse_tool_name(name)
    if not parsed:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

    skill_name, action = parsed
    tool_call = {
        "tool_use_id": f"mcp_{name}",
        "skill": skill_name,
        "action": action,
        "params": arguments,
    }

    # execute_tool を呼び出し
    result = await execute_tool(
        tool_call=tool_call,
        user_id=USER_ID,
        credentials=CREDENTIALS,
        session_id=SESSION_ID,
    )

    # format_tool_result で整形（Progressive Disclosure 対応）
    skill = SkillRegistry.get(skill_name)
    formatted = format_tool_result(result, skill_name, action, skill=skill)

    contents: list[types.TextContent | types.ImageContent] = []

    # 画像（ブラウザスクリーンショット等）
    if formatted.has_images():
        for img in formatted.images:
            if isinstance(img, dict) and img.get("type") == "image":
                source = img.get("source", {})
                if source.get("type") == "base64":
                    contents.append(
                        types.ImageContent(
                            type="image",
                            data=source["data"],
                            mimeType=source.get("media_type", "image/png"),
                        )
                    )

    # テキスト
    if formatted.text:
        contents.append(types.TextContent(type="text", text=formatted.text))

    # フォールバック: 何も返せない場合
    if not contents:
        contents.append(types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str)))

    return contents


async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
