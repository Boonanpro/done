"""Test asyncio subprocess creation - verifying Claude CLI can be spawned"""
import asyncio
import os

os.environ.pop("CLAUDECODE", None)

async def test():
    loop = asyncio.get_running_loop()
    print(f"Event loop: {type(loop).__name__}")

    # Test 1: basic subprocess
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        print(f"claude --version: {stdout.decode().strip()}")
        print(f"Return code: {proc.returncode}")
    except Exception as e:
        print(f"Subprocess error: {type(e).__name__}: {e}")

    # Test 2: SDK query
    try:
        from claude_agent_sdk import query, ClaudeAgentOptions
        options = ClaudeAgentOptions(max_turns=1, model="haiku")
        async for msg in query(prompt="Say OK", options=options):
            if hasattr(msg, "result"):
                print(f"SDK result: {msg.result}")
    except Exception as e:
        print(f"SDK error: {type(e).__name__}: {e}")

asyncio.run(test())
