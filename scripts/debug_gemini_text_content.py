"""
Debug: Check actual text content in Gemini responses
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
                parameters=genai.protos.Schema(type="OBJECT", properties={
                    "x": genai.protos.Schema(type="NUMBER"),
                    "y": genai.protos.Schema(type="NUMBER"),
                }, required=["x", "y"]),
            ),
            genai.protos.FunctionDeclaration(
                name="type",
                description="Type text",
                parameters=genai.protos.Schema(type="OBJECT", properties={
                    "text": genai.protos.Schema(type="STRING"),
                }, required=["text"]),
            ),
            genai.protos.FunctionDeclaration(
                name="done",
                description="Task complete",
                parameters=genai.protos.Schema(type="OBJECT", properties={
                    "success": genai.protos.Schema(type="BOOLEAN"),
                    "message": genai.protos.Schema(type="STRING"),
                }, required=["success", "message"]),
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
        system_instruction="You are a browser AI. Explain your reasoning before calling a tool.",
    )

    chat = model.start_chat(history=[])

    # Multiple iterations to see text patterns
    for step in range(1, 6):
        print(f"\n{'='*60}")
        print(f"STEP {step}")
        print("=" * 60)

        if step == 1:
            response = await chat.send_message_async([
                {"text": "Login to Amazon. Click the login button."},
                {"inline_data": {"mime_type": "image/png", "data": screenshot_base64}}
            ])
        else:
            await page.wait_for_timeout(300)
            screenshot_data = await page.screenshot_base64()
            screenshot_base64 = screenshot_data.get("base64", "")

            response = await chat.send_message_async([
                genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=last_action,
                        response={"result": "Action completed"},
                    )
                ),
                genai.protos.Part(
                    inline_data=genai.protos.Blob(
                        mime_type="image/png",
                        data=base64.b64decode(screenshot_base64),
                    )
                ),
            ])

        last_action = None
        for i, part in enumerate(response.candidates[0].content.parts):
            print(f"\nPart {i}:")

            # Check text
            text_val = getattr(part, 'text', None)
            if text_val is not None:
                print(f"  TEXT present: True")
                print(f"  TEXT length: {len(text_val)}")
                print(f"  TEXT repr: {repr(text_val[:100] if len(text_val) > 100 else text_val)}")

                # Analyze content
                if len(text_val) < 10:
                    print(f"  [WARNING] Very short text!")
                if '<' in text_val and '>' in text_val:
                    print(f"  [WARNING] Contains HTML-like content!")
            else:
                print(f"  TEXT present: False")

            # Check function_call
            fc = getattr(part, 'function_call', None)
            if fc:
                print(f"  FUNCTION_CALL: {fc.name}")
                print(f"  ARGS: {dict(fc.args)}")
                last_action = fc.name

                if fc.name == "done":
                    print("\n[DONE - Stopping]")
                    return

        if not last_action:
            print("\n[No tool call - Stopping]")
            return

if __name__ == "__main__":
    asyncio.run(main())
