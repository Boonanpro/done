"""
Artifact vision extraction service using Gemini.

Extracts structured text descriptions from visual media (images, HTML, videos)
using Gemini Vision API and saves them as persistent markdown files.
Dan can reference these across CLI sessions via system prompt injection.

Supports:
- HTML artifacts (proposal, dashboard, HP) — screenshot + source analysis
- User-uploaded images — direct image analysis
- User-uploaded videos — via video_analyzer integration
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types as genai_types

from app.config import settings

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-pro"

# Prompt for HTML artifact extraction (full re-implementation level)
HTML_EXTRACTION_PROMPT = """\
この成果物のスクリーンショットとHTMLソースから、再実装に必要な全情報を構造化して記述せよ。
この記述だけで同一の成果物を再現できるレベルの具体性が必要。

## レイアウト構造
- ページ全体の構成（セクション名・順序・各セクションの役割）
- 各セクションの内部レイアウト（グリッド構成、カラム数、配置パターン）
- ヘッダー/フッター/ナビゲーションの構造

## 配色・ビジュアル
- 背景色（メイン、セクション別、カード）: 具体的なカラーコードまたはCSS変数値
- テキスト色（見出し、本文、muted）
- アクセント色とその使用箇所
- グラデーション・シャドウ・ボーダーの詳細
- フォント（ファミリー、サイズの段階、ウェイト）

## テキストコンテンツ（全文）
セクション順に全てのテキストを記載:
- 見出し（レベルを区別: H1/H2/H3）
- 本文・説明文
- ラベル、バッジテキスト、ボタンテキスト
- 数値・KPI（数字とそのラベル）
- リスト項目
- 注釈・免責事項

## 機能仕様・ビジネス要件
- 記載されている機能の詳細（箇条書き）
- 価格・プラン構成
- ロードマップ・フェーズ・スケジュール
- API連携・技術スタックの言及
- ダッシュボードの場合: KPI定義、グラフ種類、データソース

## インタラクション・CTA
- ボタンの文言と想定アクション
- フォーム入力欄の種類とラベル
- ナビゲーション構造（タブ、サイドバー等）
- CTAの内容・配置・デザイン
"""

# Prompt for user-uploaded images (reference material, screenshots, etc.)
IMAGE_EXTRACTION_PROMPT = """\
この画像の内容を詳細に記述せよ。以下の情報を可能な限り抽出すること:

## 画像の概要
- 画像の種類（スクリーンショット、写真、図表、デザインモック等）
- 全体的な構成と目的

## ビジュアル詳細
- レイアウト・構成要素の配置
- 色使い（主要な色、アクセント色）
- フォント・タイポグラフィの特徴
- UIコンポーネントの種類（ボタン、カード、ナビゲーション等）

## テキストコンテンツ
画像内の全てのテキストを読み取って記載:
- 見出し、本文、ラベル、ボタンテキスト
- 数値、日付、URL

## 機能・コンテキスト
- 画像が示している機能や操作フロー
- デザインパターンやスタイルの特徴
- 参考情報として重要なポイント

日本語で回答してください。
"""

ARTIFACTS_DIR = Path.home() / ".dan" / "workspace" / "artifacts"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
HTML_EXTS = {".html", ".htm"}


# ============================================
# Core Gemini extraction functions
# ============================================

def _take_screenshot_sync(html_path: str) -> Optional[bytes]:
    """Open HTML file in headless Playwright and capture full-page screenshot."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(f"file:///{html_path.replace(chr(92), '/')}", wait_until="networkidle")
            page.wait_for_timeout(1000)
            screenshot_bytes = page.screenshot(full_page=True)
            browser.close()
            return screenshot_bytes
    except Exception as e:
        logger.error("Screenshot capture failed: %s", e, exc_info=True)
        return None


def _extract_html_sync(screenshot_bytes: bytes, html_source: str) -> Optional[str]:
    """Call Gemini Vision API with screenshot + HTML source."""
    client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)
    html_truncated = html_source[:50000]

    logger.info("Extracting HTML artifact description with %s", MODEL)
    response = client.models.generate_content(
        model=MODEL,
        contents=[
            genai_types.Content(
                parts=[
                    genai_types.Part.from_bytes(data=screenshot_bytes, mime_type="image/png"),
                    genai_types.Part(text=f"HTMLソース:\n```html\n{html_truncated}\n```"),
                    genai_types.Part(text=HTML_EXTRACTION_PROMPT),
                ]
            )
        ],
    )
    return response.text


def _extract_image_sync(image_bytes: bytes, mime_type: str) -> Optional[str]:
    """Call Gemini Vision API with a single image."""
    client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)

    logger.info("Extracting image description with %s", MODEL)
    response = client.models.generate_content(
        model=MODEL,
        contents=[
            genai_types.Content(
                parts=[
                    genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    genai_types.Part(text=IMAGE_EXTRACTION_PROMPT),
                ]
            )
        ],
    )
    return response.text


# ============================================
# Save / version management
# ============================================

def _save_description(
    room_id: str,
    artifact_name: str,
    description: str,
    artifact_type: str,
    artifact_path: str,
) -> Path:
    """Save extracted description as versioned markdown file."""
    artifacts_dir = ARTIFACTS_DIR / room_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    filepath = artifacts_dir / f"{artifact_name}.md"

    # Version backup if file already exists
    if filepath.exists():
        existing_versions = list(artifacts_dir.glob(f"{artifact_name}.v*.md"))
        next_version = len(existing_versions) + 1
        backup_path = artifacts_dir / f"{artifact_name}.v{next_version}.md"
        filepath.rename(backup_path)
        version = next_version + 1
        logger.info("Backed up previous version to %s", backup_path)
    else:
        version = 1

    now = datetime.now(timezone.utc).isoformat()
    content = f"""---
artifact_name: {artifact_name}
artifact_type: {artifact_type}
artifact_path: {artifact_path}
version: {version}
extracted_at: {now}
room_id: {room_id}
---

{description}
"""
    filepath.write_text(content, encoding="utf-8")
    logger.info("Saved artifact description: %s (version %d)", filepath, version)
    return filepath


# ============================================
# Public API: HTML artifact extraction (tool)
# ============================================

async def extract_and_save_artifact(
    artifact_file_path: str,
    artifact_name: str,
    artifact_type: str,
    room_id: str,
) -> dict:
    """Extract visual+text description from HTML artifact and save persistently.

    Called by: extract_artifact_memory tool (build skill)
    """
    if not settings.GOOGLE_GEMINI_API_KEY:
        return {"success": False, "error": "GOOGLE_GEMINI_API_KEY not set"}

    artifact_path = Path(artifact_file_path)
    if not artifact_path.exists():
        return {"success": False, "error": f"File not found: {artifact_file_path}"}

    try:
        html_source = artifact_path.read_text(encoding="utf-8")
    except Exception as e:
        return {"success": False, "error": f"Failed to read HTML: {e}"}

    screenshot_bytes = await asyncio.to_thread(_take_screenshot_sync, str(artifact_path))
    if not screenshot_bytes:
        return {"success": False, "error": "Screenshot capture failed"}

    try:
        description = await asyncio.to_thread(_extract_html_sync, screenshot_bytes, html_source)
    except Exception as e:
        logger.error("Gemini extraction failed: %s", e, exc_info=True)
        return {"success": False, "error": f"Gemini extraction failed: {e}"}

    if not description:
        return {"success": False, "error": "Gemini returned empty response"}

    saved_path = _save_description(
        room_id=room_id,
        artifact_name=artifact_name,
        description=description,
        artifact_type=artifact_type,
        artifact_path=artifact_file_path,
    )

    return {
        "success": True,
        "path": str(saved_path),
        "preview": description[:500] + "..." if len(description) > 500 else description,
        "message": f"アーティファクトメモリを保存しました: {saved_path.name}",
    }


# ============================================
# Public API: Image extraction (pre-CLI)
# ============================================

def _get_mime_type(ext: str) -> str:
    """Map file extension to MIME type."""
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".svg": "image/svg+xml",
    }.get(ext.lower(), "image/png")


async def extract_and_save_image(
    image_path: str,
    room_id: str,
) -> Optional[Path]:
    """Extract description from an image file and save as artifact.

    Called by: chat_routes.py before CLI invocation.
    Returns the saved file path, or None on failure.
    """
    if not settings.GOOGLE_GEMINI_API_KEY:
        logger.warning("GOOGLE_GEMINI_API_KEY not set, skipping image extraction")
        return None

    path = Path(image_path)
    if not path.exists():
        logger.warning("Image file not found: %s", image_path)
        return None

    ext = path.suffix.lower()
    if ext not in IMAGE_EXTS:
        logger.debug("Not an image file: %s", image_path)
        return None

    try:
        image_bytes = path.read_bytes()
    except Exception as e:
        logger.error("Failed to read image: %s", e)
        return None

    mime_type = _get_mime_type(ext)

    try:
        description = await asyncio.to_thread(_extract_image_sync, image_bytes, mime_type)
    except Exception as e:
        logger.error("Gemini image extraction failed: %s", e, exc_info=True)
        return None

    if not description:
        return None

    # Use filename stem as artifact name
    artifact_name = f"img-{path.stem}"

    saved_path = _save_description(
        room_id=room_id,
        artifact_name=artifact_name,
        description=description,
        artifact_type="image",
        artifact_path=image_path,
    )
    return saved_path


async def extract_and_save_video(
    video_path: str,
    room_id: str,
    analysis_text: Optional[str] = None,
) -> Optional[Path]:
    """Save video analysis as artifact.

    If analysis_text is provided (from video_analyzer), saves it directly.
    Otherwise, runs video analysis first.

    Called by: chat_routes.py before CLI invocation.
    """
    if not analysis_text:
        # Run video analysis via existing service
        try:
            from app.services.video_analyzer import analyze_video
            analysis_text = await analyze_video(video_path)
        except Exception as e:
            logger.error("Video analysis failed: %s", e, exc_info=True)
            return None

    if not analysis_text:
        return None

    path = Path(video_path)
    artifact_name = f"video-{path.stem}"

    saved_path = _save_description(
        room_id=room_id,
        artifact_name=artifact_name,
        description=analysis_text,
        artifact_type="video",
        artifact_path=video_path,
    )
    return saved_path


async def extract_and_save_media_batch(
    image_paths: list[str],
    video_paths: list[str],
    video_analyses: dict[str, str],
    room_id: str,
    html_paths: list[str] | None = None,
) -> list[Path]:
    """Extract and save all media from a user message in parallel.

    Args:
        image_paths: List of image file paths
        video_paths: List of video file paths
        video_analyses: {video_path: analysis_text} from _enrich_content_with_video_analysis
        room_id: Current room ID
        html_paths: List of HTML file paths

    Returns:
        List of saved artifact paths
    """
    tasks = []

    for img_path in image_paths:
        tasks.append(extract_and_save_image(img_path, room_id))

    for vid_path in video_paths:
        analysis = video_analyses.get(vid_path)
        tasks.append(extract_and_save_video(vid_path, room_id, analysis_text=analysis))

    for html_path in (html_paths or []):
        name = Path(html_path).stem
        tasks.append(extract_and_save_artifact(
            artifact_file_path=html_path,
            artifact_name=name,
            artifact_type="proposal",
            room_id=room_id,
        ))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    saved = []
    for r in results:
        if isinstance(r, Exception):
            logger.error("Media extraction failed: %s", r)
        elif isinstance(r, Path):
            saved.append(r)
        elif isinstance(r, dict) and r.get("success"):
            # extract_and_save_artifact returns dict
            saved.append(Path(r["path"]))

    if saved:
        logger.info("Saved %d artifact descriptions for room %s", len(saved), room_id)

    return saved
