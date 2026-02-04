"""
Debug VisualAgent with detailed logging at each step
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

# Patch the agent to add detailed logging
import google.generativeai as genai
from app.executors.visual.agent import VisualAgent
from app.executors.visual.recorder import BrowserRecorder

# Store original method
_original_extract = VisualAgent._extract_action_from_gemini

def _patched_extract(self, response):
    """Patched version with detailed logging"""
    print("\n" + "=" * 50)
    print("[DEBUG] _extract_action_from_gemini called")
    print("=" * 50)

    if not response.candidates:
        print("[DEBUG] No candidates in response")
        return None, ""

    candidate = response.candidates[0]
    print(f"[DEBUG] Candidate finish_reason: {candidate.finish_reason}")

    if not candidate.content or not candidate.content.parts:
        print("[DEBUG] No content or parts in candidate")
        return None, ""

    print(f"[DEBUG] Number of parts: {len(candidate.content.parts)}")

    reasoning = ""
    action = None

    for i, part in enumerate(candidate.content.parts):
        print(f"\n[DEBUG] Part {i}:")

        if hasattr(part, "text") and part.text:
            text = part.text
            print(f"  [TEXT] Length: {len(text)} chars")
            print(f"  [TEXT] First 200: {repr(text[:200])}")
            reasoning = text

            # Check for suspicious patterns
            if '<' in text and '>' in text:
                print("  [WARNING] Contains angle brackets!")
                import re
                html_like = re.findall(r'<[^>]{0,50}>', text)
                if html_like:
                    print(f"  [WARNING] HTML-like patterns: {html_like[:3]}")

            if 'storage.googleapis.com' in text:
                print("  [WARNING] Contains storage.googleapis.com!")

        if hasattr(part, "function_call") and part.function_call:
            func_call = part.function_call
            action = {
                "name": func_call.name,
                "params": dict(func_call.args) if func_call.args else {},
            }
            print(f"  [TOOL] name: {action['name']}")
            print(f"  [TOOL] params: {action['params']}")
            break

    if action:
        print(f"\n[DEBUG] Returning action: {action['name']}")
    else:
        print(f"\n[DEBUG] No action found, returning None")
        print(f"[DEBUG] Reasoning length: {len(reasoning)}")

    return action, reasoning

# Apply patch
VisualAgent._extract_action_from_gemini = _patched_extract

async def main():
    print("=" * 70)
    print("DEBUG: VisualAgent with detailed logging")
    print("=" * 70)

    recorder = BrowserRecorder(user_id="debug_test")

    agent = VisualAgent(
        recorder=recorder,
        max_steps=3,
    )

    print(f"\nModel: {agent.model}")

    result = await agent.execute_task(
        task="Search for whiteboard on Amazon",
        site="amazon.co.jp",
        initial_url="https://www.amazon.co.jp",
    )

    print("\n" + "=" * 70)
    print("FINAL RESULT:")
    print("=" * 70)
    print(f"Success: {result.get('success')}")
    print(f"Message: {result.get('message', result.get('error'))[:200] if result.get('message') or result.get('error') else 'N/A'}")
    print(f"Steps: {result.get('steps')}")

if __name__ == "__main__":
    asyncio.run(main())
