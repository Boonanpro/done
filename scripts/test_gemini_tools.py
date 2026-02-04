"""
Test Gemini tool calling (click, type, scroll)
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
api_key = os.getenv("GOOGLE_GEMINI_API_KEY")

if not api_key:
    print("ERROR: GOOGLE_GEMINI_API_KEY not found in .env")
    sys.exit(1)

genai.configure(api_key=api_key)

tools = [
    genai.protos.Tool(
        function_declarations=[
            genai.protos.FunctionDeclaration(
                name="click",
                description="Click at specified coordinates on screen",
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
                name="type",
                description="Type text into focused element",
                parameters=genai.protos.Schema(
                    type="OBJECT",
                    properties={
                        "text": genai.protos.Schema(type="STRING", description="Text to type"),
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
                    },
                    required=["direction"],
                ),
            ),
        ]
    )
]

async def test_gemini_tools():
    model = genai.GenerativeModel(
        model_name="gemini-3-flash-preview",
        tools=tools,
        system_instruction="You are a browser automation AI. Use tools to perform actions.",
    )

    chat = model.start_chat(history=[])

    # Test 1: Click
    print("=" * 50)
    print("Test 1: Click on search box")
    print("=" * 50)
    response = await chat.send_message_async(
        "Click on the search box at coordinates (512, 300)."
    )

    for part in response.candidates[0].content.parts:
        if hasattr(part, "function_call") and part.function_call:
            print(f"[OK] Tool call: {part.function_call.name}")
            print(f"     Args: {dict(part.function_call.args)}")
        elif hasattr(part, "text") and part.text:
            print(f"     Text: {part.text[:100]}")

    # Test 2: Type (after sending function_response)
    print("\n" + "=" * 50)
    print("Test 2: Type 'whiteboard'")
    print("=" * 50)

    function_response = genai.protos.Part(
        function_response=genai.protos.FunctionResponse(
            name="click",
            response={"result": "Click successful. Search box is now focused."},
        )
    )
    response = await chat.send_message_async([function_response])

    # Check if it auto-continues or needs another prompt
    has_tool_call = False
    for part in response.candidates[0].content.parts:
        if hasattr(part, "function_call") and part.function_call:
            has_tool_call = True
            print(f"[OK] Tool call: {part.function_call.name}")
            print(f"     Args: {dict(part.function_call.args)}")
        elif hasattr(part, "text") and part.text:
            print(f"     Text: {part.text[:100]}")

    if not has_tool_call:
        # Send explicit instruction
        response = await chat.send_message_async("Now type 'whiteboard' into the search box.")
        for part in response.candidates[0].content.parts:
            if hasattr(part, "function_call") and part.function_call:
                print(f"[OK] Tool call: {part.function_call.name}")
                print(f"     Args: {dict(part.function_call.args)}")
            elif hasattr(part, "text") and part.text:
                print(f"     Text: {part.text[:100]}")

    # Test 3: Scroll
    print("\n" + "=" * 50)
    print("Test 3: Scroll down")
    print("=" * 50)

    response = await chat.send_message_async("Scroll down the page.")

    for part in response.candidates[0].content.parts:
        if hasattr(part, "function_call") and part.function_call:
            print(f"[OK] Tool call: {part.function_call.name}")
            print(f"     Args: {dict(part.function_call.args)}")
        elif hasattr(part, "text") and part.text:
            print(f"     Text: {part.text[:100]}")

    print("\n" + "=" * 50)
    print("Test complete")
    print("=" * 50)

if __name__ == "__main__":
    asyncio.run(test_gemini_tools())
