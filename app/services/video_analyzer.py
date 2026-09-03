"""
Video analysis service using Gemini (agentic video understanding).

Sends video files to Gemini for multimodal understanding
(visual content, audio, screen operations, human movements, etc.)
and returns a text description.

2026-09-03: switched from static 1fps processing (generate_content on
gemini-3.1-pro-preview) to *agentic* video understanding via the
Interactions API (`processing: "agentic"`). The model navigates the
video itself (frames / audio / transcript on demand) instead of
ingesting every frame — up to 88% fewer tokens on long videos.
Agentic mode is only offered on Flash-family models, hence the model
change. Single code path by design (no length-based branching); if the
agentic call fails we fall back to static processing on the same model.
Requires google-genai >= 2.3.0 (Interactions API v2 schema).

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

from app.config import settings

logger = logging.getLogger(__name__)

MODEL = "gemini-3.8-flash"
# "agentic" = model-driven navigation of the video (Flash models only).
VIDEO_PROCESSING = "agentic"

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
    r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]+)'
)
_LOOM_RE = re.compile(
    r'https?://(?:www\.)?loom\.com/share/([\w-]+)'
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


def _video_input(uri: str, mime_type: Optional[str], processing: Optional[str]) -> dict:
    item: dict = {"type": "video", "uri": uri}
    if mime_type:
        item["mime_type"] = mime_type
    if processing:
        item["processing"] = processing
    return item


def _extract_text(interaction) -> Optional[str]:
    """Final answer text only: model_output steps, never thought steps.

    `interaction.output_text` occasionally carried a leaked "thought" preamble
    (observed 2026-09-04 on gemini-3.8-flash), so we build the text ourselves
    and strip such a preamble defensively.
    """
    parts: list[str] = []
    for step in getattr(interaction, "steps", None) or []:
        if getattr(step, "type", None) != "model_output":
            continue
        for content in getattr(step, "content", None) or []:
            if getattr(content, "type", None) == "text" and getattr(content, "text", None):
                parts.append(content.text)
    text = "".join(parts) if parts else (getattr(interaction, "output_text", None) or "")
    NL = chr(10)
    if text.lstrip().lower().startswith("thought"):
        for marker in (NL + "# ", NL + "---", NL + NL):
            i = text.find(marker)
            if i > 0:
                text = text[i:].lstrip()
                break
    return text or None


def _run_interaction(client: "genai.Client", uri: str, mime_type: Optional[str], prompt: str, label: str) -> Optional[str]:
    """Call the Interactions API with agentic processing; fall back to static on failure."""
    import time

    t0 = time.time()
    try:
        interaction = client.interactions.create(
            model=MODEL,
            input=[_video_input(uri, mime_type, VIDEO_PROCESSING), {"type": "text", "text": prompt}],
        )
        usage = getattr(interaction, "usage", None)
        logger.info(
            "Video analysis done (%s, %s/%s, %.1fs, tokens=%s)",
            label, MODEL, VIDEO_PROCESSING, time.time() - t0,
            getattr(usage, "total_tokens", None),
        )
        return _extract_text(interaction)
    except Exception as e:
        logger.warning(
            "Agentic video analysis failed (%s, %.1fs): %s — retrying with static processing",
            label, time.time() - t0, e,
        )
        t1 = time.time()
        interaction = client.interactions.create(
            model=MODEL,
            input=[_video_input(uri, mime_type, None), {"type": "text", "text": prompt}],
        )
        logger.info("Video analysis done (%s, %s/static, %.1fs)", label, MODEL, time.time() - t1)
        return _extract_text(interaction)


def _analyze_file_sync(file_path: str, prompt: str) -> Optional[str]:
    """Upload a local file to Gemini Files API and analyze (agentic)."""
    import time

    client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)

    logger.info("Uploading video to Gemini: %s", file_path)
    video_file = client.files.upload(file=file_path)

    # Large files (hundreds of MB, 1h+) can take several minutes to become ACTIVE.
    for _ in range(300):
        video_file = client.files.get(name=video_file.name)
        if video_file.state.name == "ACTIVE":
            break
        if video_file.state.name == "FAILED":
            raise RuntimeError(f"Gemini rejected the video file: {video_file.name}")
        logger.info("Waiting for video processing... (state: %s)", video_file.state.name)
        time.sleep(2)
    else:
        raise RuntimeError(f"Video file did not become ACTIVE after 600s (state: {video_file.state.name})")

    logger.info("Analyzing video with %s/%s (file: %s)", MODEL, VIDEO_PROCESSING, video_file.name)
    return _run_interaction(client, video_file.uri, video_file.mime_type, prompt, os.path.basename(file_path))


def _analyze_youtube_sync(video_url: str, prompt: str) -> Optional[str]:
    """Analyze YouTube video by passing URL directly to Gemini (no download)."""
    client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)

    logger.info("Analyzing YouTube video with %s/%s: %s", MODEL, VIDEO_PROCESSING, video_url)
    return _run_interaction(client, video_url, None, prompt, video_url)


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
