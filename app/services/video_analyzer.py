"""
Video analysis service using Gemini.

Sends video files to Gemini for multimodal understanding
(visual content, audio, screen operations, human movements, etc.)
and returns a text description.
"""

import asyncio
import logging
import os
from typing import Optional

from google import genai
from google.genai import types as genai_types

from app.config import settings

logger = logging.getLogger(__name__)

MODEL = "gemini-3.1-pro-preview"

ANALYSIS_PROMPT = (
    "この動画の内容を詳細に分析してください。以下を含めてください:\n"
    "- 映像の内容（画面操作、UI操作、人の動き、表情、ジェスチャー等）\n"
    "- 音声の内容（会話、ナレーション、効果音等）\n"
    "- 時系列に沿った要約\n"
    "- 重要なポイントや意図の推測\n"
    "日本語で回答してください。"
)


def _analyze_sync(file_path: str, prompt: str) -> Optional[str]:
    """Synchronous Gemini video analysis (runs in thread pool)."""
    import time

    client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)

    logger.info("Uploading video to Gemini: %s", file_path)
    video_file = client.files.upload(file=file_path)

    # Wait for file to become ACTIVE (video processing takes time)
    for _ in range(60):
        video_file = client.files.get(name=video_file.name)
        if video_file.state.name == "ACTIVE":
            break
        logger.info("Waiting for video processing... (state: %s)", video_file.state.name)
        time.sleep(2)
    else:
        raise RuntimeError(f"Video file did not become ACTIVE after 120s (state: {video_file.state.name})")

    logger.info("Analyzing video with %s (file: %s)", MODEL, video_file.name)
    response = client.models.generate_content(
        model=MODEL,
        contents=[
            genai_types.Content(
                parts=[
                    genai_types.Part.from_uri(
                        file_uri=video_file.uri,
                        mime_type=video_file.mime_type,
                    ),
                    genai_types.Part(text=prompt),
                ]
            )
        ],
    )

    return response.text


async def analyze_video(file_path: str, prompt: str = ANALYSIS_PROMPT) -> Optional[str]:
    """Analyze a video file using Gemini and return text description.

    Args:
        file_path: Absolute path to the video file on disk.
        prompt: Analysis prompt to send with the video.

    Returns:
        Text description of video content, or None on failure.
    """
    if not settings.GOOGLE_GEMINI_API_KEY:
        logger.warning("GOOGLE_GEMINI_API_KEY not set, skipping video analysis")
        return None

    if not os.path.exists(file_path):
        logger.error("Video file not found: %s", file_path)
        return None

    try:
        result = await asyncio.to_thread(_analyze_sync, file_path, prompt)
        logger.info("Video analysis complete (%d chars)", len(result) if result else 0)
        return result
    except Exception as e:
        logger.error("Video analysis failed: %s", e, exc_info=True)
        return None
