# -*- coding: utf-8 -*-
"""アップロードされた MP4/MOV を「faststart」（moov を先頭へ）に組み替える。

スマホの録画（Samsung / iPhone とも）は moov（再生に必要な索引）がファイル末尾にある。
Chrome は Range で末尾を先読みして再生できるが、iOS Safari はこの形式のストリーミング再生に
弱く「再生できない」になりやすい。再エンコードせず箱の並びだけ変える（-c copy）ので数秒・無劣化。
ffmpeg は imageio_ffmpeg 同梱のもの → PATH → 既知の場所 の順で探す。無ければ何もしない。
"""
from __future__ import annotations

import logging
import os
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_FFMPEG: Optional[str] = None
VIDEO_EXTS = {".mp4", ".m4v", ".mov"}


def find_ffmpeg() -> Optional[str]:
    global _FFMPEG
    if _FFMPEG:
        return _FFMPEG
    try:
        import imageio_ffmpeg  # type: ignore
        _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
        return _FFMPEG
    except Exception:
        pass
    exe = shutil.which("ffmpeg")
    if exe:
        _FFMPEG = exe
        return exe
    for cand in (r"C:\Users\Owner\ffmpeg\bin\ffmpeg.exe", r"C:\ffmpeg\bin\ffmpeg.exe"):
        if os.path.exists(cand):
            _FFMPEG = cand
            return cand
    return None


def needs_faststart(path: Path) -> bool:
    """moov が mdat より後ろにあるか（先頭の箱を辿るだけ。巨大ファイルでも一瞬）。"""
    try:
        with open(path, "rb") as f:
            pos = 0
            size_total = path.stat().st_size
            seen_mdat = False
            while pos < size_total:
                f.seek(pos)
                head = f.read(16)
                if len(head) < 8:
                    return False
                size, typ = struct.unpack(">I4s", head[:8])
                if size == 1:
                    size = struct.unpack(">Q", head[8:16])[0]
                elif size == 0:
                    size = size_total - pos
                if typ == b"moov":
                    return seen_mdat
                if typ == b"mdat":
                    seen_mdat = True
                if size <= 0:
                    return False
                pos += size
    except Exception:
        return False
    return False


def faststart_inplace(path: Path, timeout: int = 300) -> bool:
    """必要なら moov を先頭へ。成功時 True。失敗しても元ファイルは残す。"""
    if path.suffix.lower() not in VIDEO_EXTS or not needs_faststart(path):
        return False
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        logger.warning("[faststart] ffmpeg not found; skip %s", path.name)
        return False
    tmp = path.with_name(path.stem + ".faststart" + path.suffix)
    try:
        # Windows(uvicorn) では asyncio.create_subprocess_exec が使えないため同期 run（呼び出し側で to_thread）
        r = subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-i", str(path), "-c", "copy", "-movflags", "+faststart", str(tmp)],
            capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
            logger.warning("[faststart] ffmpeg failed for %s: %s", path.name, r.stderr.decode("utf-8", "replace")[:300])
            if tmp.exists():
                tmp.unlink()
            return False
        os.replace(tmp, path)
        logger.info("[faststart] remuxed %s", path.name)
        return True
    except Exception:
        logger.warning("[faststart] error for %s", path.name, exc_info=True)
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        return False
