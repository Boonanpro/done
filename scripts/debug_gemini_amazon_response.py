"""
Debug: Detailed logging of Gemini responses with real Amazon screenshots
"""
import asyncio
import base64
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
api_key = os.getenv("GOOGLE_GEMINI_API_KEY")
genai.configure(api_key=api_key)

# Same tools as VisualAgent
TOOLS = [
    genai.protos.Tool(
        function_declarations=[
            genai.protos.FunctionDeclaration(
                name="click",
                description="Click at specified coordinates on screen",
                parameters=genai.protos.Schema(
                    type="OBJECT",
                    properties={
                        "x": genai.protos.Schema(type="NUMBER", description="X coordinate (pixels)"),
                        "y": genai.protos.Schema(type="NUMBER", description="Y coordinate (pixels)"),
                        "description": genai.protos.Schema(type="STRING", description="Description of element"),
                    },
                    required=["x", "y"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="type",
                description="Type text into focused element",
                parameters=genai.protos.Schema(
                    type="OBJECT",
                    properties={
                        "text": genai.protos.Schema(type="STRING", description="Text to type"),
                        "press_enter": genai.protos.Schema(type="BOOLEAN", description="Press Enter after typing"),
                    },
                    required=["text"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="scroll",
                description="Scroll the page",
                parameters=genai.protos.Schema(
                    type="OBJECT",
                    properties={
                        "direction": genai.protos.Schema(type="STRING", description="up or down"),
                        "amount": genai.protos.Schema(type="NUMBER", description="Pixels to scroll"),
                    },
                    required=["direction"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="done",
                description="Task completed",
                parameters=genai.protos.Schema(
                    type="OBJECT",
                    properties={
                        "success": genai.protos.Schema(type="BOOLEAN", description="Success"),
                        "message": genai.protos.Schema(type="STRING", description="Message"),
                    },
                    required=["success", "message"],
                ),
            ),
        ]
    )
]

SYSTEM_PROMPT = """You are a browser automation AI.

# Screen info
- Resolution: 1024x768 pixels
- Coordinate system: top-left is (0, 0), bottom-right is (1024, 768)

# Instructions
1. Look at the screenshot and decide the next action
2. ALWAYS call a tool - never respond with only text
3. Call 'done' when the task is complete

# Rules
- One action at a time
- Use coordinates, not CSS selectors
"""

async def test_with_real_page():
    """Test with real Amazon page"""
    from app.tools.browser import get_executor_page

    print("=" * 70)
    print("Testing Gemini with real Amazon page")
    print("=" * 70)

    # Get browser page
    page = await get_executor_page()
    await page.goto("https://www.amazon.co.jp")
    await page.wait_for_timeout(3000)

    # Take screenshot
    screenshot_data = await page.screenshot_base64()
    screenshot_base64 = screenshot_data.get("base64", "")

    print(f"Screenshot size: {len(screenshot_base64)} chars")

    # Create model
    model = genai.GenerativeModel(
        model_name="gemini-3-flash-preview",
        tools=TOOLS,
        system_instruction=SYSTEM_PROMPT,
    )

    chat = model.start_chat(history=[])

    # Step 1: Initial request
    print("\n" + "-" * 50)
    print("Step 1: Initial request")
    print("-" * 50)

    task = "Search for 'whiteboard' on this page"
    content_parts = [
        {"text": f"Task: {task}\n\nLook at the screenshot and decide the first action."},
        {
            "inline_data": {
                "mime_type": "image/png",
                "data": screenshot_base64,
            }
        }
    ]

    response = await chat.send_message_async(
        content_parts,
        generation_config=genai.types.GenerationConfig(max_output_tokens=1024),
    )

    print(f"\nResponse parts: {len(response.candidates[0].content.parts)}")

    action = None
    reasoning = ""
    for i, part in enumerate(response.candidates[0].content.parts):
        print(f"\nPart {i}:")
        if hasattr(part, "function_call") and part.function_call:
            action = {
                "name": part.function_call.name,
                "params": dict(part.function_call.args),
            }
            print(f"  [TOOL] {action['name']}: {action['params']}")
        if hasattr(part, "text") and part.text:
            reasoning = part.text
            print(f"  [TEXT] ({len(part.text)} chars): {part.text[:200]}...")
            # Check for HTML-like content
            if '<' in part.text and '>' in part.text:
                print("  [WARNING] Text contains HTML-like content!")
                # Find HTML patterns
                import re
                html_patterns = re.findall(r'<[^>]+>', part.text)
                if html_patterns:
                    print(f"  [WARNING] Found HTML tags: {html_patterns[:5]}")

    if not action:
        print("\n[ERROR] No tool call in Step 1!")
        return

    # Simulate action execution
    print(f"\n[Executing action: {action['name']}]")

    # Take new screenshot (simulating page change)
    await page.wait_for_timeout(500)
    screenshot_data = await page.screenshot_base64()
    screenshot_base64 = screenshot_data.get("base64", "")

    # Step 2: Send function_response
    print("\n" + "-" * 50)
    print("Step 2: Send function_response with new screenshot")
    print("-" * 50)

    function_response_parts = [
        genai.protos.Part(
            function_response=genai.protos.FunctionResponse(
                name=action['name'],
                response={"result": f"Action '{action['name']}' completed successfully."},
            )
        ),
        genai.protos.Part(
            inline_data=genai.protos.Blob(
                mime_type="image/png",
                data=base64.b64decode(screenshot_base64),
            )
        ),
    ]

    response = await chat.send_message_async(
        function_response_parts,
        generation_config=genai.types.GenerationConfig(max_output_tokens=1024),
    )

    print(f"\nResponse parts: {len(response.candidates[0].content.parts)}")

    action = None
    for i, part in enumerate(response.candidates[0].content.parts):
        print(f"\nPart {i}:")
        if hasattr(part, "function_call") and part.function_call:
            action = {
                "name": part.function_call.name,
                "params": dict(part.function_call.args),
            }
            print(f"  [TOOL] {action['name']}: {action['params']}")
        if hasattr(part, "text") and part.text:
            print(f"  [TEXT] ({len(part.text)} chars): {part.text[:300]}...")
            if '<' in part.text and '>' in part.text:
                print("  [WARNING] Text contains HTML-like content!")
                import re
                html_patterns = re.findall(r'<[^>]+>', part.text)
                if html_patterns:
                    print(f"  [WARNING] Found HTML tags: {html_patterns[:5]}")

    if not action:
        print("\n[ERROR] No tool call in Step 2! This is the bug.")
        print("\nFull response text:")
        for part in response.candidates[0].content.parts:
            if hasattr(part, "text") and part.text:
                print(part.text[:500])
    else:
        print(f"\n[SUCCESS] Got tool call: {action['name']}")

if __name__ == "__main__":
    asyncio.run(test_with_real_page())
