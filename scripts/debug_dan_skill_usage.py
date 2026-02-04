"""
Debug: Check if Dan uses skills correctly when calling visual_browse
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(name)s - %(levelname)s - %(message)s'
)

# Suppress noisy loggers
for name in ['httpx', 'httpcore', 'hpack', 'grpc', 'asyncio']:
    logging.getLogger(name).setLevel(logging.WARNING)

from app.agent.v2.runner import AgentRunner
from app.agent.v2.tools import get_all_skill_tools, VISUAL_BROWSE_TOOL, CHECK_SKILL_TOOL, SkillRegistry

async def main():
    print("=" * 70)
    print("DEBUG: Check if Dan uses skills correctly")
    print("=" * 70)

    # Check available skills
    print("\n[1] Available Skills in Registry:")
    print("-" * 50)
    all_skills = SkillRegistry.list_all()
    for skill in all_skills:
        print(f"  - {skill.name}: {skill.description}")
        actions = skill.list_available_actions()
        if actions:
            for action in actions[:5]:
                print(f"      action: {action}")

    # Check tools available to Dan
    print("\n[2] Tools available to Dan:")
    print("-" * 50)
    skill_tools = get_all_skill_tools()
    print(f"  Skill tools: {len(skill_tools)}")
    for tool in skill_tools[:5]:
        print(f"    - {tool['name']}")

    print(f"  visual_browse: YES")
    print(f"  check_skill: YES")

    # Create a mock session to trace tool calls
    print("\n[3] Tracing Dan's tool calls for 'Amazonにログインして':")
    print("-" * 50)

    # Patch the runner to capture tool calls
    original_execute = AgentRunner._execute_tool

    tool_calls = []

    async def patched_execute(self, tool_call, credentials=None):
        tool_name = tool_call.get("tool_name")
        params = tool_call.get("params", {})
        tool_calls.append({
            "tool": tool_name,
            "params": params,
        })
        print(f"\n  [TOOL CALL] {tool_name}")
        print(f"    params: {params}")

        # Check specific parameters for visual_browse
        if tool_name == "visual_browse":
            skill_name = params.get("skill_name")
            skill_manual = params.get("skill_manual")
            task = params.get("task")
            site = params.get("site")

            print(f"\n    [VISUAL_BROWSE PARAMS]")
            print(f"      task: {task}")
            print(f"      site: {site}")
            print(f"      skill_name: {skill_name}")
            print(f"      skill_manual present: {bool(skill_manual)}")
            if skill_manual:
                print(f"      skill_manual length: {len(skill_manual)} chars")
                print(f"      skill_manual preview: {skill_manual[:200]}...")

            if not skill_name and not skill_manual:
                print(f"\n    [WARNING] visual_browse called WITHOUT skill_name or skill_manual!")
                print(f"    [WARNING] This means Dan is not using the Amazon skill!")

        # Don't actually execute - just trace
        return {
            "success": True,
            "message": "Test mode - tool not actually executed",
        }

    AgentRunner._execute_tool = patched_execute

    try:
        runner = AgentRunner(
            user_id="test_user",
            session_id="test_session",
        )

        # Run one turn
        print("\n  Sending message: 'Amazonにログインして'")
        result = await runner.run_turn("Amazonにログインして")

        print("\n" + "=" * 70)
        print("[4] Summary of tool calls:")
        print("=" * 70)
        for i, call in enumerate(tool_calls, 1):
            print(f"\n  Call {i}: {call['tool']}")
            if call['tool'] == 'visual_browse':
                print(f"    skill_name: {call['params'].get('skill_name', 'NOT SET')}")
                print(f"    skill_manual: {'SET' if call['params'].get('skill_manual') else 'NOT SET'}")

        # Check if skill was used
        visual_browse_calls = [c for c in tool_calls if c['tool'] == 'visual_browse']
        if visual_browse_calls:
            vb = visual_browse_calls[0]
            if not vb['params'].get('skill_name') and not vb['params'].get('skill_manual'):
                print("\n" + "=" * 70)
                print("[PROBLEM FOUND]")
                print("=" * 70)
                print("Dan called visual_browse WITHOUT using the Amazon skill!")
                print("This explains why login takes many steps - no skill guidance.")
            else:
                print("\n[OK] Dan is using the skill correctly")
        else:
            print("\n[INFO] No visual_browse calls (Dan may have used other tools)")

    finally:
        AgentRunner._execute_tool = original_execute

if __name__ == "__main__":
    asyncio.run(main())
