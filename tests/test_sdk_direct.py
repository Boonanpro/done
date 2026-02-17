"""Direct SDK runner test - run with CLAUDECODE cleared"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Clear CLAUDECODE to avoid nesting restriction
os.environ.pop("CLAUDECODE", None)
print(f"CLAUDECODE={os.environ.get('CLAUDECODE', 'NOT SET')}")

async def test():
    from claude_agent_sdk import query, ClaudeAgentOptions

    stderr_lines = []
    def on_stderr(line):
        stderr_lines.append(line)

    options = ClaudeAgentOptions(
        model="sonnet",
        system_prompt="You are a test assistant. Say hello.",
        permission_mode="bypassPermissions",
        max_turns=1,
        cwd="D:\\done",
        cli_path=r"C:\Users\Owner\AppData\Roaming\npm\claude.cmd",
        stderr=on_stderr,
        debug_stderr=None,
        env={"ANTHROPIC_API_KEY": ""},
    )

    print("Starting SDK query...")
    try:
        async for message in query(prompt="Say hello", options=options):
            print(f"  Message: {type(message).__name__}")
            if hasattr(message, "result"):
                print(f"  Result: {message.result}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")

    print(f"\nStderr ({len(stderr_lines)} lines):")
    for line in stderr_lines:
        print(f"  {line}")
    print("Done.")

asyncio.run(test())
