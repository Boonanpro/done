"""Minimal FastAPI test to verify SDK works from uvicorn"""
import os
os.environ.pop("CLAUDECODE", None)

from fastapi import FastAPI
from starlette.responses import StreamingResponse
import json
import asyncio

app = FastAPI()

@app.get("/test-sdk")
async def test_sdk():
    async def generate():
        try:
            from claude_agent_sdk import query, ClaudeAgentOptions
            options = ClaudeAgentOptions(max_turns=1, model="haiku")
            async for msg in query(prompt="Say OK and nothing else", options=options):
                if hasattr(msg, "result"):
                    yield f"data: {json.dumps({'result': msg.result})}\n\n"
        except Exception as e:
            import traceback
            yield f"data: {json.dumps({'error': f'{type(e).__name__}: {e}', 'tb': traceback.format_exc()})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

if __name__ == "__main__":
    print("Starting test server on port 8899...")
    print("Test: curl http://127.0.0.1:8899/test-sdk")
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "httpx", "http://127.0.0.1:8899/test-sdk"], timeout=30)
