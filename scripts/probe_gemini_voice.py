"""Read model availability and validate Live setup without sending user audio."""
import asyncio
import json
from pathlib import Path

from google import genai
from app.config import settings

MODEL = 'gemini-3.8-live-extended-thinking'


async def main():
    client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)
    result = {'model': MODEL}
    try:
        model = await client.aio.models.get(model=MODEL)
        result['available'] = model.name
        async with client.aio.live.connect(model=MODEL, config={
            'response_modalities': ['AUDIO'],
            'thinking_config': {'thinking_level': 'low'},
        }):
            result['setup_connected'] = True
    except Exception as error:
        result['error_type'] = type(error).__name__
        result['error'] = str(error).replace(settings.GOOGLE_GEMINI_API_KEY, '[redacted]')[:600]
    finally:
        await client.aio.aclose()
    Path('.tmp/gemini-voice-probe.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    asyncio.run(main())
