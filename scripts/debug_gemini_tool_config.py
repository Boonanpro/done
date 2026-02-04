"""
Debug: Gemini tool_config options
Test if we can force Gemini to always call a tool
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
genai.configure(api_key=api_key)

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

async def test_tool_config_modes():
    """Test different tool_config modes"""

    # Test 1: Default mode (AUTO)
    print("=" * 60)
    print("Test 1: Default mode (no tool_config)")
    print("=" * 60)

    model = genai.GenerativeModel(
        model_name="gemini-3-flash-preview",
        tools=tools,
        system_instruction="You are a browser automation AI. Use tools to perform actions.",
    )

    chat = model.start_chat(history=[])
    response = await chat.send_message_async("Click on the button at (100, 200)")

    for part in response.candidates[0].content.parts:
        if hasattr(part, "function_call") and part.function_call:
            print(f"  [TOOL] {part.function_call.name}")
        if hasattr(part, "text") and part.text:
            print(f"  [TEXT] {part.text[:100]}...")

    # Send function_response and check if it calls another tool
    print("\n  Sending function_response...")
    function_response = genai.protos.Part(
        function_response=genai.protos.FunctionResponse(
            name="click",
            response={"result": "Click successful. Now you see a search box."},
        )
    )
    response = await chat.send_message_async([function_response])

    has_tool = False
    for part in response.candidates[0].content.parts:
        if hasattr(part, "function_call") and part.function_call:
            has_tool = True
            print(f"  [TOOL] {part.function_call.name}")
        if hasattr(part, "text") and part.text:
            print(f"  [TEXT] {part.text[:200]}...")

    if not has_tool:
        print("  [WARNING] No tool call after function_response!")

    # Test 2: ANY mode (force tool calling)
    print("\n" + "=" * 60)
    print("Test 2: ANY mode (force tool calling)")
    print("=" * 60)

    try:
        # Check if ANY mode is supported
        tool_config = genai.protos.ToolConfig(
            function_calling_config=genai.protos.FunctionCallingConfig(
                mode=genai.protos.FunctionCallingConfig.Mode.ANY,
            )
        )

        model2 = genai.GenerativeModel(
            model_name="gemini-3-flash-preview",
            tools=tools,
            tool_config=tool_config,
            system_instruction="You are a browser automation AI. Always use a tool.",
        )

        chat2 = model2.start_chat(history=[])
        response = await chat2.send_message_async("Click on the button at (100, 200)")

        for part in response.candidates[0].content.parts:
            if hasattr(part, "function_call") and part.function_call:
                print(f"  [TOOL] {part.function_call.name}")
            if hasattr(part, "text") and part.text:
                print(f"  [TEXT] {part.text[:100]}...")

        # Send function_response
        print("\n  Sending function_response...")
        response = await chat2.send_message_async([function_response])

        has_tool = False
        for part in response.candidates[0].content.parts:
            if hasattr(part, "function_call") and part.function_call:
                has_tool = True
                print(f"  [TOOL] {part.function_call.name}")
            if hasattr(part, "text") and part.text:
                print(f"  [TEXT] {part.text[:200]}...")

        if has_tool:
            print("  [SUCCESS] ANY mode forces tool calling!")
        else:
            print("  [WARNING] ANY mode still didn't call a tool")

    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")

    # Test 3: Add explicit instruction after function_response
    print("\n" + "=" * 60)
    print("Test 3: Add explicit instruction after function_response")
    print("=" * 60)

    model3 = genai.GenerativeModel(
        model_name="gemini-3-flash-preview",
        tools=tools,
        system_instruction="You are a browser automation AI. ALWAYS call a tool. Never respond with only text.",
    )

    chat3 = model3.start_chat(history=[])
    response = await chat3.send_message_async("Click on the button at (100, 200)")

    for part in response.candidates[0].content.parts:
        if hasattr(part, "function_call") and part.function_call:
            print(f"  [TOOL] {part.function_call.name}")

    # Send function_response WITH explicit instruction
    print("\n  Sending function_response with explicit instruction...")
    response = await chat3.send_message_async([
        function_response,
        genai.protos.Part(text="Based on the result, decide and call the next action tool.")
    ])

    has_tool = False
    for part in response.candidates[0].content.parts:
        if hasattr(part, "function_call") and part.function_call:
            has_tool = True
            print(f"  [TOOL] {part.function_call.name}")
        if hasattr(part, "text") and part.text:
            print(f"  [TEXT] {part.text[:200]}...")

    if has_tool:
        print("  [SUCCESS] Explicit instruction works!")
    else:
        print("  [WARNING] Still no tool call")

if __name__ == "__main__":
    asyncio.run(test_tool_config_modes())
