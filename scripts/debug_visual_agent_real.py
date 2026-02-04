"""
Debug VisualAgent with real Amazon page
Capture all LLM interactions for analysis
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import logging
logging.basicConfig(level=logging.DEBUG, format='%(name)s - %(levelname)s - %(message)s')

from app.executors.visual.agent import VisualAgent
from app.executors.visual.recorder import BrowserRecorder

async def main():
    print("=" * 70)
    print("DEBUG: VisualAgent with Amazon")
    print("=" * 70)

    # Create recorder
    recorder = BrowserRecorder(user_id="debug_test")

    # Track all interactions
    interactions = []

    async def on_thinking(reasoning: str):
        print(f"\n[THINKING] {reasoning[:500]}...")
        interactions.append({"type": "thinking", "content": reasoning})

    async def on_step(step_num: int, action_name: str, result):
        success = getattr(result, "success", result.get("success", True) if isinstance(result, dict) else True)
        print(f"\n[STEP {step_num}] {action_name} - {'OK' if success else 'FAIL'}")
        interactions.append({
            "type": "step",
            "step": step_num,
            "action": action_name,
            "success": success,
        })

    async def on_plan(plan: dict):
        print(f"\n[PLAN] {plan}")
        interactions.append({"type": "plan", "content": plan})

    agent = VisualAgent(
        recorder=recorder,
        on_thinking=on_thinking,
        on_step=on_step,
        on_plan=on_plan,
        max_steps=5,  # Limit steps for debugging
    )

    print(f"\nModel: {agent.model}")
    print(f"Max steps: {agent.max_steps}")

    # Execute task
    result = await agent.execute_task(
        task="Amazon.co.jp for whiteboard, find and report the name of the first product",
        site="amazon.co.jp",
        initial_url="https://www.amazon.co.jp",
    )

    print("\n" + "=" * 70)
    print("RESULT:")
    print("=" * 70)
    print(f"Success: {result.get('success')}")
    print(f"Message: {result.get('message', result.get('error'))}")
    print(f"Steps: {result.get('steps')}")

    print("\n" + "=" * 70)
    print("ALL INTERACTIONS:")
    print("=" * 70)
    for i, interaction in enumerate(interactions):
        print(f"\n--- Interaction {i+1} ---")
        print(f"Type: {interaction['type']}")
        if interaction['type'] == 'thinking':
            content = interaction['content']
            # Check for HTML-like content
            if '<' in content and '>' in content:
                print("WARNING: Contains HTML-like content!")
            print(f"Content (first 300 chars): {content[:300]}")
        elif interaction['type'] == 'step':
            print(f"Action: {interaction['action']}, Success: {interaction['success']}")
        elif interaction['type'] == 'plan':
            print(f"Plan: {interaction['content']}")

if __name__ == "__main__":
    asyncio.run(main())
