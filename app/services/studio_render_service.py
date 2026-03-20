"""
Studio Render Service - Playwright recording & FFmpeg encoding
Runs in the FastAPI backend process, NOT in Claude Code CLI.
This avoids CLI's 4GB Bun heap limit and subprocess sandbox restrictions.
"""
import os
import asyncio
import logging
import subprocess
import functools
from pathlib import Path
from typing import Optional
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading

logger = logging.getLogger(__name__)

FFMPEG = os.path.expanduser("~/ffmpeg/bin/ffmpeg.exe")
FFPROBE = os.path.expanduser("~/ffmpeg/bin/ffprobe.exe")


class StudioRenderService:

    # ==================== Record ====================

    async def record(
        self,
        html_path: str,
        output_dir: str,
        duration_sec: int,
        width: int = 1920,
        height: int = 1080,
        serve_dir: Optional[str] = None,
        pre_wait_ms: int = 5000,
        js_eval: Optional[str] = None,
    ) -> dict:
        """Playwright headless Chromium で HTML を録画して .webm を生成"""
        os.makedirs(output_dir, exist_ok=True)

        def _do_record():
            from playwright.sync_api import sync_playwright

            http_server = None
            http_thread = None
            url = html_path

            # serve_dir 指定時は一時 HTTP サーバーで配信
            if serve_dir:
                handler = functools.partial(SimpleHTTPRequestHandler, directory=serve_dir)
                http_server = HTTPServer(("127.0.0.1", 0), handler)
                port = http_server.server_address[1]
                http_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
                http_thread.start()
                # html_path が絶対パスなら serve_dir からの相対に変換
                if os.path.isabs(html_path):
                    rel = os.path.relpath(html_path, serve_dir).replace("\\", "/")
                    url = f"http://127.0.0.1:{port}/{rel}"
                else:
                    url = f"http://127.0.0.1:{port}/{html_path}"
                logger.info(f"[studio_record] HTTP server on port {port}, url={url}")
            elif not html_path.startswith("http"):
                # file:// URL に変換
                url = "file:///" + html_path.replace("\\", "/")

            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(
                        viewport={"width": width, "height": height},
                        record_video_dir=output_dir,
                        record_video_size={"width": width, "height": height},
                    )
                    page = context.new_page()
                    page.goto(url, wait_until="networkidle", timeout=30000)
                    page.wait_for_timeout(pre_wait_ms)

                    if js_eval:
                        page.evaluate(js_eval)

                    remaining = max(0, (duration_sec * 1000) - pre_wait_ms)
                    if remaining > 0:
                        page.wait_for_timeout(remaining)

                    video_path = page.video.path()
                    context.close()
                    browser.close()
                    return str(video_path)
            finally:
                if http_server:
                    http_server.shutdown()

        video_path = await asyncio.to_thread(_do_record)
        file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
        logger.info(f"[studio_record] Done: {video_path} ({file_size_mb:.1f}MB)")
        return {
            "success": True,
            "video_path": video_path,
            "file_size_mb": round(file_size_mb, 1),
            "duration_sec": duration_sec,
        }

    # ==================== Encode ====================

    async def encode(
        self,
        input_path: str,
        output_path: str,
        width: int = 1920,
        height: int = 1080,
        codec: str = "libx264",
        crf: int = 20,
        preset: str = "fast",
        extra_args: str = "-pix_fmt yuv420p -movflags +faststart",
    ) -> dict:
        """FFmpeg で動画を変換/エンコード"""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        cmd = [
            FFMPEG, "-y", "-i", input_path,
            "-vf", f"scale={width}:{height}",
            "-c:v", codec, "-preset", preset, "-crf", str(crf),
        ]
        if extra_args:
            cmd.extend(extra_args.split())
        cmd.append(output_path)

        logger.info(f"[studio_encode] Running: {' '.join(cmd)}")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace")[-500:]
            logger.error(f"[studio_encode] Failed: {err}")
            return {
                "success": False,
                "error": f"FFmpeg failed (exit {proc.returncode}): {err}",
            }

        file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
        logger.info(f"[studio_encode] Done: {output_path} ({file_size_mb:.1f}MB)")
        return {
            "success": True,
            "output_path": output_path,
            "file_size_mb": round(file_size_mb, 1),
            "resolution": f"{width}x{height}",
            "codec": codec,
        }

    # ==================== Probe ====================

    async def probe(self, path: str) -> dict:
        """FFprobe で動画メタ情報を取得"""
        if not os.path.exists(path):
            return {"success": False, "error": f"File not found: {path}"}

        cmd = [
            FFPROBE,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,duration",
            "-of", "csv=p=0",
            path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace")
            return {"success": False, "error": f"FFprobe failed: {err}"}

        parts = stdout.decode().strip().split(",")
        file_size_mb = os.path.getsize(path) / (1024 * 1024)
        return {
            "success": True,
            "path": path,
            "codec": parts[0] if len(parts) > 0 else "unknown",
            "width": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0,
            "height": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0,
            "duration_sec": float(parts[3]) if len(parts) > 3 and parts[3].replace(".", "").isdigit() else 0,
            "file_size_mb": round(file_size_mb, 1),
        }

    # ==================== Extract Frame ====================

    async def extract_frame(
        self,
        video_path: str,
        timestamp: str,
        output_path: str,
    ) -> dict:
        """動画から指定時刻のフレームを PNG として抽出"""
        if not os.path.exists(video_path):
            return {"success": False, "error": f"File not found: {video_path}"}

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cmd = [
            FFMPEG, "-y",
            "-ss", timestamp,
            "-i", video_path,
            "-vframes", "1",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0 or not os.path.exists(output_path):
            err = stderr.decode("utf-8", errors="replace")[-300:]
            return {"success": False, "error": f"Frame extraction failed: {err}"}

        file_size_kb = os.path.getsize(output_path) / 1024
        return {
            "success": True,
            "output_path": output_path,
            "file_size_kb": round(file_size_kb, 1),
        }
