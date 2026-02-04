"""
Test skill_generator_claude.py directly
"""
import asyncio
import sys
sys.path.insert(0, "D:/done")

from app.services.skill_generator_claude import (
    analyze_session_for_skill,
    generate_skill,
)


async def test_analyze():
    """Test analyze_session_for_skill"""
    yaml_path = "D:/done/app/logs/browser/8f2a82b3/20260127_014932_Yahoo! Japanで「天気」と検索する.yaml"

    print("=" * 50)
    print("Testing analyze_session_for_skill")
    print("=" * 50)

    proposal = await analyze_session_for_skill(yaml_path)

    if proposal:
        print("[OK] Success!")
        print(f"  skill_name: {proposal.skill_name}")
        print(f"  description: {proposal.description}")
        print(f"  site: {proposal.site}")
        print(f"  actions: {proposal.actions}")
        print(f"  parameters: {proposal.parameters}")
    else:
        print("[FAIL] Failed to analyze session")


async def test_generate():
    """Test generate_skill"""
    yaml_path = "D:/done/app/logs/browser/8f2a82b3/20260127_014932_Yahoo! Japanで「天気」と検索する.yaml"

    print("\n" + "=" * 50)
    print("Testing generate_skill")
    print("=" * 50)

    result = await generate_skill(
        yaml_log_path=yaml_path,
        skill_name="yahoo_search_claude_test",
    )

    if result.success:
        print("[OK] Success!")
        print(f"  skill_name: {result.skill_name}")
        print(f"  skill_path: {result.skill_path}")
        print(f"  files_created: {result.files_created}")
    else:
        print(f"[FAIL] Failed: {result.error}")
        if result.output:
            print(f"  output: {result.output[:500]}")


async def main():
    # Test analyze first
    await test_analyze()

    # Uncomment to test generate (takes longer)
    # await test_generate()


if __name__ == "__main__":
    asyncio.run(main())
