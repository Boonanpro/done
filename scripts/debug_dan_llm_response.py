"""
Debug: Capture Dan's LLM response to see what tools he calls
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import logging
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')

# Suppress noisy loggers
for name in ['httpx', 'httpcore', 'hpack', 'grpc', 'asyncio']:
    logging.getLogger(name).setLevel(logging.WARNING)

from app.agent.v2.session import Session
from app.agent.v2.tools import get_all_skill_tools, SkillRegistry

async def main():
    print("=" * 70)
    print("DEBUG: Capture Dan's LLM response")
    print("=" * 70)

    # Load skills
    SkillRegistry.load()
    print(f"\n[1] Loaded skills: {[s.name for s in SkillRegistry.list_all()]}")

    # Get all tools
    tools = get_all_skill_tools()
    tool_names = [t['name'] for t in tools]
    print(f"\n[2] Available tools: {tool_names}")

    # Build system prompt directly from file
    from pathlib import Path
    system_prompt_path = Path(__file__).parent.parent / "app" / "agent" / "v2" / "prompts" / "system.md"
    system_prompt = system_prompt_path.read_text(encoding="utf-8")
    print(f"\n[3] System prompt length: {len(system_prompt)} chars")

    # Check if Amazon skill info is in system prompt
    if "amazon" in system_prompt.lower():
        print("    Amazon mentioned in system prompt: YES")
    else:
        print("    Amazon mentioned in system prompt: NO")

    # Call LLM directly to see response
    print("\n[4] Calling LLM with message: 'Amazonにログインして'")
    print("-" * 50)

    import anthropic
    from app.config import settings

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    messages = [
        {"role": "user", "content": "Amazonにログインして"}
    ]

    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=system_prompt,
        tools=tools,
        messages=messages,
    )

    print(f"\n[5] LLM Response:")
    print("-" * 50)

    for block in response.content:
        if block.type == "text":
            print(f"  [TEXT] {block.text[:200]}...")
        elif block.type == "tool_use":
            print(f"  [TOOL_USE] {block.name}")
            print(f"    id: {block.id}")
            print(f"    input: {json.dumps(block.input, ensure_ascii=False, indent=4)}")

            # Check if skill_name is passed for visual_browse
            if block.name == "visual_browse":
                skill_name = block.input.get("skill_name")
                skill_manual = block.input.get("skill_manual")
                print(f"\n    [ANALYSIS]")
                print(f"      skill_name: {skill_name if skill_name else 'NOT SET!'}")
                print(f"      skill_manual: {'SET' if skill_manual else 'NOT SET!'}")

                if not skill_name and not skill_manual:
                    print(f"\n    [WARNING] Dan is NOT using the Amazon skill!")
                    print(f"    [WARNING] This will result in inefficient login process!")

if __name__ == "__main__":
    asyncio.run(main())
