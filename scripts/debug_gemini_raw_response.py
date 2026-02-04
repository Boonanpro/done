"""
Debug: Dump raw Gemini response structure
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
genai.configure(api_key=os.getenv("GOOGLE_GEMINI_API_KEY"))

TOOLS = [
    genai.protos.Tool(
        function_declarations=[
            genai.protos.FunctionDeclaration(
                name="click",
                description="Click at coordinates",
                parameters=genai.protos.Schema(
                    type="OBJECT",
                    properties={
                        "x": genai.protos.Schema(type="NUMBER"),
                        "y": genai.protos.Schema(type="NUMBER"),
                    },
                    required=["x", "y"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="type",
                description="Type text",
                parameters=genai.protos.Schema(
                    type="OBJECT",
                    properties={
                        "text": genai.protos.Schema(type="STRING"),
                    },
                    required=["text"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="done",
                description="Task complete",
                parameters=genai.protos.Schema(
                    type="OBJECT",
                    properties={
                        "success": genai.protos.Schema(type="BOOLEAN"),
                        "message": genai.protos.Schema(type="STRING"),
                    },
                    required=["success", "message"],
                ),
            ),
        ]
    )
]

async def main():
    from app.tools.browser import get_executor_page

    page = await get_executor_page()
    await page.goto("https://www.amazon.co.jp")
    await page.wait_for_timeout(3000)

    screenshot_data = await page.screenshot_base64()
    screenshot_base64 = screenshot_data.get("base64", "")

    model = genai.GenerativeModel(
        model_name="gemini-3-flash-preview",
        tools=TOOLS,
        system_instruction="You are a browser AI. Always use a tool.",
    )

    chat = model.start_chat(history=[])

    # Initial request
    print("=" * 70)
    print("INITIAL REQUEST")
    print("=" * 70)

    response = await chat.send_message_async([
        {"text": "Click on the search bar"},
        {"inline_data": {"mime_type": "image/png", "data": screenshot_base64}}
    ])

    print("\n[RAW RESPONSE STRUCTURE]")
    print(f"candidates: {len(response.candidates)}")
    for i, cand in enumerate(response.candidates):
        print(f"\nCandidate {i}:")
        print(f"  finish_reason: {cand.finish_reason}")
        print(f"  parts: {len(cand.content.parts)}")
        for j, part in enumerate(cand.content.parts):
            print(f"\n  Part {j}:")
            print(f"    type: {type(part).__name__}")
            print(f"    dir: {[a for a in dir(part) if not a.startswith('_')][:10]}")

            if hasattr(part, 'text'):
                print(f"    has text: {part.text is not None}")
                if part.text:
                    print(f"    text value: {repr(part.text)}")
                    print(f"    text length: {len(part.text)}")

            if hasattr(part, 'function_call'):
                print(f"    has function_call: {part.function_call is not None}")
                if part.function_call:
                    print(f"    function_call.name: {part.function_call.name}")
                    print(f"    function_call.args: {dict(part.function_call.args)}")

    # Send function_response and get next response
    print("\n" + "=" * 70)
    print("AFTER FUNCTION RESPONSE")
    print("=" * 70)

    await page.wait_for_timeout(500)
    screenshot_data = await page.screenshot_base64()
    screenshot_base64 = screenshot_data.get("base64", "")

    response = await chat.send_message_async([
        genai.protos.Part(
            function_response=genai.protos.FunctionResponse(
                name="click",
                response={"result": "Clicked successfully"},
            )
        ),
        genai.protos.Part(
            inline_data=genai.protos.Blob(
                mime_type="image/png",
                data=base64.b64decode(screenshot_base64),
            )
        ),
    ])

    print("\n[RAW RESPONSE STRUCTURE]")
    print(f"candidates: {len(response.candidates)}")
    for i, cand in enumerate(response.candidates):
        print(f"\nCandidate {i}:")
        print(f"  finish_reason: {cand.finish_reason}")
        print(f"  parts: {len(cand.content.parts)}")
        for j, part in enumerate(cand.content.parts):
            print(f"\n  Part {j}:")

            if hasattr(part, 'text'):
                if part.text:
                    print(f"    [TEXT] {repr(part.text)}")

            if hasattr(part, 'function_call'):
                if part.function_call:
                    print(f"    [FUNCTION_CALL] {part.function_call.name}")
                    print(f"    args: {dict(part.function_call.args)}")

    # One more step
    print("\n" + "=" * 70)
    print("THIRD RESPONSE")
    print("=" * 70)

    await page.wait_for_timeout(500)
    screenshot_data = await page.screenshot_base64()
    screenshot_base64 = screenshot_data.get("base64", "")

    response = await chat.send_message_async([
        genai.protos.Part(
            function_response=genai.protos.FunctionResponse(
                name="type",
                response={"result": "Typed successfully"},
            )
        ),
        genai.protos.Part(
            inline_data=genai.protos.Blob(
                mime_type="image/png",
                data=base64.b64decode(screenshot_base64),
            )
        ),
    ])

    print("\n[RAW RESPONSE STRUCTURE]")
    for i, cand in enumerate(response.candidates):
        print(f"parts: {len(cand.content.parts)}")
        for j, part in enumerate(cand.content.parts):
            if hasattr(part, 'text') and part.text:
                print(f"  Part {j}: [TEXT] {repr(part.text)}")
            if hasattr(part, 'function_call') and part.function_call:
                print(f"  Part {j}: [FUNCTION_CALL] {part.function_call.name}")

if __name__ == "__main__":
    asyncio.run(main())
