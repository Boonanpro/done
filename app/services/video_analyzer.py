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
_YOUTUBE_RE = re.compile(r'https?://(?:www\.|m\.)?(?:youtube\.com|youtu\.be)/\S+')
_LOOM_RE = re.compile(
    r'https?://(?:www\.)?loom\.com/share/([\w-]+)'
)

UPLOADS_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "uploads"))

# Dan looks at a video when the work needs it, as much as it needs (owner, 2026-10-11). Before: every message with a
# YouTube/Loom URL or a video attachment was analysed here before Dan started, with one fixed summary prompt cut at
# 5,000 characters. Two 11-14 minute videos took longer than the relay keeps a silent connection (about 2 minutes), the
# request was cancelled and Dan never started (2026-10-09, twice, no error anywhere).
TOOL = {
    'name': 'video',
    'description': ('動画の中身を知る。action で2つのやり方を選ぶ。どちらを・何回・どの順で使うかは自由。\n'
                    'captions: YouTube が保存している字幕を全文そのまま返す（約30秒ごとの時刻つき）。動画は見ないので数秒で、何分の動画でも同じ。無料。'
                    '投稿者が付けた字幕か、YouTube が音声から自動で作った字幕かは結果に書く。自動の字幕は所々聞き取りを間違える。'
                    '字幕を持っているのは YouTube だけで、無い動画もある。\n'
                    'ask: Gemini が映像と音声を実際に見て question に答える。YouTube / Loom の URL と動画ファイルに使える。'
                    '1回ごとに料金がかかり、同じ質問でも毎回ばらつく（14分の動画の30秒の区間を4回聞いて22〜91秒・1〜12円）。'
                    '字幕からは分からないこと（画面の操作・表情・テロップ・編集）、字幕の無い動画、字幕の言葉を確かめたい時に。'),
    'input_schema': {'type': 'object', 'properties': {
        'action': {'type': 'string', 'enum': ['captions', 'ask']},
        'source': {'type': 'string', 'description': 'YouTube / Loom の URL、または動画ファイル（絶対パス、添付動画の名前や /api/v1/files/… の URL）'},
        'question': {'type': 'string', 'description': 'ask の時: 動画について知りたいこと。時刻や場面を絞って具体的に書くほど答えも具体的になる'},
    }, 'required': ['action', 'source'], 'additionalProperties': False},
}

# Gemini's agentic video mode writes its working notes into the output and, with no mark to aim for, runs the answer on
# straight after them; one call in two ended with no answer at all (two calls with the same question, 2026-10-11).
# With these marks the answer could be told from the notes in both calls that had them. Kept here, not in
# _run_interaction: other callers send their own prompts.
ANSWER_MARKS = '\n\n最終的な答えは必ず <answer> と </answer> で囲んで出力してください。考えている途中のメモは囲みの外に書いてください。'


def _final_answer(text: Optional[str]) -> str:
    """What Gemini wrote after its last <answer> mark, up to the closing one; everything it wrote when it used none.
    It opens the mark more than once and does not always close it (seen 2026-10-11)."""
    return (text or "").rsplit("<answer>", 1)[-1].split("</answer>")[0].strip()


def _youtube_captions_sync(url: str) -> Optional[str]:
    """The captions YouTube already holds for the video (the uploader's, else the automatic ones in the spoken
    language), with a time mark about every 30 seconds. None when it has none. The video itself is not fetched."""
    import json
    import yt_dlp

    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True, "socket_timeout": 20}) as ydl:
        info = ydl.extract_info(url, download=False)
        manual, auto = info.get("subtitles") or {}, info.get("automatic_captions") or {}
        spoken = next((k for k in auto if k.endswith("-orig")), None)   # the automatic track that is not a translation
        lang = info.get("language") or (spoken[:-5] if spoken else None)
        by_uploader = next((manual[k] for k in manual if lang and k.split("-")[0] == lang.split("-")[0]), None)
        tracks = by_uploader or auto.get(spoken or "") or auto.get(lang or "") or []
        track = next((t for t in tracks if t.get("ext") == "json3"), None)
        if not track:
            return None
        events = json.loads(ydl.urlopen(track["url"]).read()).get("events") or []

    lines, start, parts = [], None, []
    for event in events:
        text = "".join(seg.get("utf8", "") for seg in event.get("segs") or [])
        if not text.strip():
            continue
        at = int(event.get("tStartMs") or 0) // 1000
        if start is None or at - start >= 30:
            if parts:
                lines.append(f"[{start // 60}:{start % 60:02d}] " + " ".join("".join(parts).split()))
            start, parts = at, []
        parts.append(text)
    if parts:
        lines.append(f"[{start // 60}:{start % 60:02d}] " + " ".join("".join(parts).split()))
    if not lines:
        return None
    seconds = int(info.get("duration") or 0)
    kind = "投稿者が付けた字幕" if by_uploader else "自動生成の字幕（聞き取り間違いを含む）"
    return f"{info.get('title') or url}（{seconds // 60}分{seconds % 60:02d}秒）\n{kind}\n\n" + "\n".join(lines)


def _local_video(source: str) -> Optional[str]:
    """A video on this PC: a path, or an attachment given by its name or its /api/v1/files/… URL."""
    if os.path.isfile(source):
        return source
    path = os.path.join(UPLOADS_DIR, source.split("?")[0].rstrip("/").replace("\\", "/").split("/")[-1])
    return path if os.path.isfile(path) else None


async def tool(params: dict) -> dict:
    action = str(params.get("action") or "").strip()
    source = str(params.get("source") or "").strip()
    question = str(params.get("question") or "").strip()
    if not source:
        return {"success": False, "error": "source が空"}
    youtube, loom = _YOUTUBE_RE.search(source), _LOOM_RE.search(source)

    if action == "captions":
        if not youtube:
            return {"success": False, "error": "字幕を持っているのは YouTube だけ。この動画は ask で Gemini に見てもらう"}
        try:
            captions = await asyncio.to_thread(_youtube_captions_sync, youtube.group(0))
        except Exception as e:
            return {"success": False, "error": f"字幕を取れなかった: {e}"}
        if not captions:
            return {"success": False, "error": "この動画に字幕は無い"}
        return {"success": True, "output": captions}

    if action != "ask":
        return {"success": False, "error": "action は captions か ask"}
    if not question:
        return {"success": False, "error": "ask には question が要る"}
    if not settings.GOOGLE_GEMINI_API_KEY:
        return {"success": False, "error": "GOOGLE_GEMINI_API_KEY が設定されていない"}
    if youtube:
        look = (_analyze_youtube_sync, youtube.group(0))
    elif loom:
        look = (_analyze_loom_sync, loom.group(1))
    else:
        path = _local_video(source)
        if not path:
            return {"success": False, "error": f"動画が見つからない: {source}（YouTube / Loom の URL か、この PC 上の動画ファイルを渡す）"}
        look = (_analyze_file_sync, path)
    answer = ""
    for _ in range(2):   # an empty answer is asked once more; a second empty one is reported, not hidden
        try:
            answer = _final_answer(await asyncio.to_thread(*look, question + ANSWER_MARKS))
        except Exception as e:
            return {"success": False, "error": f"Gemini が動画を見られなかった: {e}"}
        if answer:
            return {"success": True, "output": answer}
    return {"success": False, "error": "Gemini が2回とも答えを返さなかった"}


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
