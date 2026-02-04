"""
Debug Gemini Visual Agent - check what's being sent and received
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

if not api_key:
    print("ERROR: GOOGLE_GEMINI_API_KEY not found")
    sys.exit(1)

genai.configure(api_key=api_key)

# Simple tool definition
tools = [
    genai.protos.Tool(
        function_declarations=[
            genai.protos.FunctionDeclaration(
                name="click",
                description="Click at specified coordinates",
                parameters=genai.protos.Schema(
                    type="OBJECT",
                    properties={
                        "x": genai.protos.Schema(type="NUMBER", description="X coordinate"),
                        "y": genai.protos.Schema(type="NUMBER", description="Y coordinate"),
                    },
                    required=["x", "y"],
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

async def test_with_screenshot():
    """Test sending a screenshot to Gemini and getting action back"""

    # Create a simple test image (1x1 red pixel PNG)
    # This is a minimal valid PNG
    test_png_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="

    model = genai.GenerativeModel(
        model_name="gemini-3-flash-preview",
        tools=tools,
        system_instruction="You are a browser automation AI. Use tools to perform actions. Always use a tool.",
    )

    chat = model.start_chat(history=[])

    # Test 1: Send text + image (initial request)
    print("=" * 60)
    print("Test 1: Initial request with image")
    print("=" * 60)

    content_parts = [
        {"text": "Click on the search box in the center of the screen."},
        {
            "inline_data": {
                "mime_type": "image/png",
                "data": test_png_base64,
            }
        }
    ]

    response = await chat.send_message_async(content_parts)

    print(f"Response candidates: {len(response.candidates)}")
    for i, candidate in enumerate(response.candidates):
        print(f"\nCandidate {i}:")
        for j, part in enumerate(candidate.content.parts):
            print(f"  Part {j}:")
            if hasattr(part, "function_call") and part.function_call:
                print(f"    [FUNCTION CALL] {part.function_call.name}")
                print(f"    Args: {dict(part.function_call.args)}")
            if hasattr(part, "text") and part.text:
                text = part.text[:200] + "..." if len(part.text) > 200 else part.text
                print(f"    [TEXT] {repr(text)}")

    # Test 2: Send function_response with image (like in agent.py)
    print("\n" + "=" * 60)
    print("Test 2: function_response with image (like agent.py)")
    print("=" * 60)

    # Decode base64 to bytes (like the fixed code does)
    image_bytes = base64.b64decode(test_png_base64)

    function_response_parts = [
        genai.protos.Part(
            function_response=genai.protos.FunctionResponse(
                name="click",
                response={"result": "Click successful at (512, 300)"},
            )
        ),
        genai.protos.Part(
            inline_data=genai.protos.Blob(
                mime_type="image/png",
                data=image_bytes,  # This should be bytes, not base64 string
            )
        ),
    ]

    response = await chat.send_message_async(function_response_parts)

    print(f"Response candidates: {len(response.candidates)}")
    for i, candidate in enumerate(response.candidates):
        print(f"\nCandidate {i}:")
        for j, part in enumerate(candidate.content.parts):
            print(f"  Part {j}:")
            if hasattr(part, "function_call") and part.function_call:
                print(f"    [FUNCTION CALL] {part.function_call.name}")
                print(f"    Args: {dict(part.function_call.args)}")
            if hasattr(part, "text") and part.text:
                text = part.text[:200] + "..." if len(part.text) > 200 else part.text
                print(f"    [TEXT] {repr(text)}")

    # Test 3: Check what happens with WRONG format (base64 string encoded to bytes)
    print("\n" + "=" * 60)
    print("Test 3: WRONG format - base64.encode() instead of b64decode()")
    print("=" * 60)

    # This is what the OLD buggy code did
    wrong_bytes = test_png_base64.encode()  # This is WRONG - just UTF-8 bytes of base64 string

    print(f"Correct bytes length: {len(image_bytes)}")
    print(f"Wrong bytes length: {len(wrong_bytes)}")
    print(f"Correct bytes start: {image_bytes[:20]}")
    print(f"Wrong bytes start: {wrong_bytes[:20]}")

    try:
        function_response_parts_wrong = [
            genai.protos.Part(
                function_response=genai.protos.FunctionResponse(
                    name="click",
                    response={"result": "Click successful"},
                )
            ),
            genai.protos.Part(
                inline_data=genai.protos.Blob(
                    mime_type="image/png",
                    data=wrong_bytes,  # WRONG!
                )
            ),
        ]

        # Start a new chat for this test
        chat2 = model.start_chat(history=[])
        await chat2.send_message_async([{"text": "Click on the button"}])
        response = await chat2.send_message_async(function_response_parts_wrong)

        print("Response received (unexpectedly)")
        for part in response.candidates[0].content.parts:
            if hasattr(part, "text") and part.text:
                print(f"  [TEXT] {repr(part.text[:300])}")
    except Exception as e:
        print(f"Error (expected): {type(e).__name__}: {str(e)[:200]}")

if __name__ == "__main__":
    asyncio.run(test_with_screenshot())
