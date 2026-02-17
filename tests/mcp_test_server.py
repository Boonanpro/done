"""MCP test server - stdio transport"""
import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

server = Server("test-tools")

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_time",
            description="Get current time in a location",
            inputSchema={
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name"}
                },
                "required": ["location"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "get_time":
        loc = arguments.get("location", "unknown")
        return [types.TextContent(type="text", text=f"Current time in {loc}: 14:30:00 JST")]
    raise ValueError(f"Unknown tool: {name}")

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
