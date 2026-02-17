"""
Claude Agent SDK + MCP テスト
Max プランで動くか、カスタムツールが呼ばれるかを検証
"""
import asyncio
import json

# --- Test 1: 基本的な query() ---
async def test_basic_query():
    """SDK 経由で Max プラン認証でクエリが動くか"""
    print("=" * 60)
    print("Test 1: Basic query (Max plan auth)")
    print("=" * 60)

    from claude_agent_sdk import query, ClaudeAgentOptions

    options = ClaudeAgentOptions(
        max_turns=1,
        model="sonnet",
    )

    async for message in query(prompt="Say 'hello world' and nothing else.", options=options):
        print(f"  Type: {type(message).__name__}")
        if hasattr(message, "result"):
            print(f"  Result: {message.result}")
        elif hasattr(message, "session_id"):
            print(f"  Session: {message.session_id}")

    print("  [OK] Basic query works\n")


# --- Test 2: カスタム MCP ツール ---
async def test_mcp_tool():
    """カスタムツールが MCP 経由で呼ばれるか"""
    print("=" * 60)
    print("Test 2: Custom MCP tool")
    print("=" * 60)

    from claude_agent_sdk import query, ClaudeAgentOptions, tool, create_sdk_mcp_server

    @tool(
        name="get_time",
        description="Get the current time in Tokyo",
        input_schema={}
    )
    async def get_time(args):
        from datetime import datetime
        import pytz
        now = datetime.now(pytz.timezone("Asia/Tokyo"))
        return {"content": [{"type": "text", "text": f"Tokyo time: {now.strftime('%H:%M:%S')}"}]}

    server = create_sdk_mcp_server(
        name="test-tools",
        version="1.0.0",
        tools=[get_time]
    )

    options = ClaudeAgentOptions(
        max_turns=3,
        model="sonnet",
        mcp_servers={"test-tools": server},
        allowed_tools=["mcp__test-tools__get_time"],
        system_prompt="You have a tool called get_time. When asked about the time, use it. Reply in one sentence.",
    )

    async for message in query(prompt="What time is it in Tokyo?", options=options):
        print(f"  Type: {type(message).__name__}")
        if hasattr(message, "result"):
            print(f"  Result: {message.result}")

    print("  [OK] MCP tool test done\n")


# --- Test 3: ストリーミング ---
async def test_streaming():
    """ストリーミングイベントが取れるか"""
    print("=" * 60)
    print("Test 3: Streaming events")
    print("=" * 60)

    from claude_agent_sdk import query, ClaudeAgentOptions

    options = ClaudeAgentOptions(
        max_turns=1,
        model="sonnet",
        include_partial_messages=True,
    )

    event_types = set()
    async for message in query(prompt="Count from 1 to 5.", options=options):
        t = type(message).__name__
        event_types.add(t)
        if hasattr(message, "result"):
            print(f"  Final result: {message.result}")

    print(f"  Event types seen: {event_types}")
    print("  [OK] Streaming test done\n")


async def main():
    try:
        await test_basic_query()
    except Exception as e:
        print(f"  [FAIL] {e}\n")

    try:
        await test_mcp_tool()
    except Exception as e:
        print(f"  [FAIL] {e}\n")

    try:
        await test_streaming()
    except Exception as e:
        print(f"  [FAIL] {e}\n")


if __name__ == "__main__":
    asyncio.run(main())
