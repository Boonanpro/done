"""
Video analysis service using Gemini.

Sends video files to Gemini for multimodal understanding
(visual content, audio, screen operations, human movements, etc.)
and returns a text description.

Supports:
- Local file paths (upload to Gemini Files API)
- YouTube URLs (native Gemini support, no download needed)
- Loom URLs (download via Loom API, then upload to Gemini)
"""

import asyncio
import logging
import os
import re
import tempfile
from typing import Optional

import requests
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

# URL patterns
_YOUTUBE_RE = re.compile(
    r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]+)',
    re.IGNORECASE,
)
_LOOM_RE = re.compile(
    r'https?://(?:www\.)?loom\.com/share/([\w-]+)',
    re.IGNORECASE,
)


def extract_video_urls(text: str) -> list[dict]:
    """Extract YouTube and Loom URLs from text.

    Returns list of {"platform": "youtube"|"loom", "url": str, "video_id": str}.
    """
    results = []
    seen = set()
    for m in _YOUTUBE_RE.finditer(text):
        vid = m.group(1)
        if vid not in seen:
            seen.add(vid)
            results.append({"platform": "youtube", "url": m.group(0), "video_id": vid})
    for m in _LOOM_RE.finditer(text):
        vid = m.group(1)
        if vid not in seen:
            seen.add(vid)
            results.append({"platform": "loom", "url": m.group(0), "video_id": vid})
    return results


def _download_loom_video(video_id: str) -> str:
    """Download Loom video to a temp file via their transcoded-url API.

    Returns path to the downloaded file.
    Raises RuntimeError on failure.
    """
    api_url = f"https://www.loom.com/api/campaigns/sessions/{video_id}/transcoded-url"
    resp = requests.post(api_url, json={}, headers={
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
    }, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"Loom API returned {resp.status_code}")

    mp4_url = resp.json().get("url")
    if not mp4_url:
        raise RuntimeError("Loom API returned no URL")

    logger.info("Downloading Loom video: %s", video_id)
    video_resp = requests.get(mp4_url, timeout=300, stream=True)
    video_resp.raise_for_status()

    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    for chunk in video_resp.iter_content(chunk_size=8192):
        tmp.write(chunk)
    tmp.close()
    logger.info("Loom video downloaded: %s (%d bytes)", tmp.name, os.path.getsize(tmp.name))
    return tmp.name


def _analyze_file_sync(file_path: str, prompt: str) -> Optional[str]:
    """Upload a local file to Gemini Files API and analyze."""
    import time

    client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)

    logger.info("Uploading video to Gemini: %s", file_path)
    video_file = client.files.upload(file=file_path)

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


def _analyze_youtube_sync(video_url: str, prompt: str) -> Optional[str]:
    """Analyze YouTube video by passing URL directly to Gemini (no download)."""
    client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)

    logger.info("Analyzing YouTube video: %s", video_url)
    response = client.models.generate_content(
        model=MODEL,
        contents=[
            genai_types.Content(
                parts=[
                    genai_types.Part.from_uri(
                        file_uri=video_url,
                        mime_type="video/mp4",
                    ),
                    genai_types.Part(text=prompt),
                ]
            )
        ],
    )
    return response.text


def _analyze_loom_sync(video_id: str, prompt: str) -> Optional[str]:
    """Download Loom video, upload to Gemini, and analyze."""
    tmp_path = None
    try:
        tmp_path = _download_loom_video(video_id)
        return _analyze_file_sync(tmp_path, prompt)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def analyze_video(file_path: str, prompt: str = ANALYSIS_PROMPT) -> Optional[str]:
    """Analyze a local video file using Gemini.

    Args:
        file_path: Absolute path to the video file on disk.
        prompt: Analysis prompt to send with the video.
    """
    if not settings.GOOGLE_GEMINI_API_KEY:
        logger.warning("GOOGLE_GEMINI_API_KEY not set, skipping video analysis")
        return None

    if not os.path.exists(file_path):
        logger.error("Video file not found: %s", file_path)
        return None

    try:
        result = await asyncio.to_thread(_analyze_file_sync, file_path, prompt)
        logger.info("Video analysis complete (%d chars)", len(result) if result else 0)
        return result
    except Exception as e:
        logger.error("Video analysis failed: %s", e, exc_info=True)
        return None


async def analyze_video_url(platform: str, video_id: str, url: str, prompt: str = ANALYSIS_PROMPT) -> Optional[str]:
    """Analyze a video from URL (YouTube or Loom).

    Args:
        platform: "youtube" or "loom"
        video_id: Platform-specific video ID
        url: Original URL
        prompt: Analysis prompt
    """
    if not settings.GOOGLE_GEMINI_API_KEY:
        logger.warning("GOOGLE_GEMINI_API_KEY not set, skipping video analysis")
        return None

    try:
        if platform == "youtube":
            result = await asyncio.to_thread(_analyze_youtube_sync, url, prompt)
        elif platform == "loom":
            result = await asyncio.to_thread(_analyze_loom_sync, video_id, prompt)
        else:
            logger.warning("Unsupported video platform: %s", platform)
            return None
        logger.info("Video URL analysis complete (%s, %d chars)", platform, len(result) if result else 0)
        return result
    except Exception as e:
        logger.error("Video URL analysis failed (%s): %s", platform, e, exc_info=True)
        return None
