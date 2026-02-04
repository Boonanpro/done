"""
Debug: Trace skill_manual from skill load to VisualAgent
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from app.agent.v2.tools import SkillRegistry

def main():
    print("=" * 70)
    print("DEBUG: Skill Manual Flow")
    print("=" * 70)

    # Load skills
    SkillRegistry.load()

    # Get Amazon skill
    skill = SkillRegistry.get("amazon")
    if not skill:
        print("[ERROR] Amazon skill not found!")
        return

    print(f"\n[1] Skill loaded: {skill.name}")
    print("-" * 50)
    print(f"  description: {skill.description}")
    print(f"  domain: {skill.domain}")
    print(f"  skill_dir: {skill.skill_dir}")

    print(f"\n[2] Raw content length: {len(skill.raw_content)} chars")
    print("-" * 50)
    print(f"  First 500 chars:\n{skill.raw_content[:500]}")

    print(f"\n[3] Markdown content length: {len(skill.markdown_content)} chars")
    print("-" * 50)
    print(f"  First 500 chars:\n{skill.markdown_content[:500]}")

    print(f"\n[4] Available actions:")
    print("-" * 50)
    actions = skill.list_available_actions()
    for action in actions:
        manual = skill.get_action_manual(action)
        print(f"  - {action}: {len(manual) if manual else 0} chars")

    # Get login action manual
    print(f"\n[5] Login action manual:")
    print("-" * 50)
    login_manual = skill.get_action_manual("login")
    if login_manual:
        print(login_manual[:1000])
    else:
        print("  NOT FOUND!")

    # Simulate what _execute_visual_browse does
    print(f"\n[6] Simulating _execute_visual_browse:")
    print("-" * 50)
    skill_manual = skill.markdown_content or skill.raw_content
    print(f"  skill_manual length: {len(skill_manual)} chars")
    print(f"  skill_manual would be passed to VisualAgent")

    # Check if login info is in skill_manual
    if "login" in skill_manual.lower():
        print(f"  'login' mentioned in skill_manual: YES")
    else:
        print(f"  'login' mentioned in skill_manual: NO")

    # Check what VisualAgent does with skill_manual
    print(f"\n[7] Checking VisualAgent system prompt:")
    print("-" * 50)

    # Read agent.py to find skill_manual usage
    agent_path = Path(__file__).parent.parent / "app" / "executors" / "visual" / "agent.py"
    agent_code = agent_path.read_text(encoding="utf-8")

    if "skill_manual_section" in agent_code:
        print("  VisualAgent has skill_manual_section: YES")
    else:
        print("  VisualAgent has skill_manual_section: NO")

    if "_skill_manual" in agent_code:
        print("  VisualAgent uses _skill_manual: YES")
    else:
        print("  VisualAgent uses _skill_manual: NO")

if __name__ == "__main__":
    main()
