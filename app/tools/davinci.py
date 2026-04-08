"""
DaVinci Resolve Python API ラッパー

重要: このモジュールはPython 3.13で実行する必要がある。
fusionscript.dllがPython 3.10と非互換のため、
全てのResolve操作はsubprocessでPython 3.13を呼び出して実行する。
"""
import subprocess
import json
import os
import tempfile
import logging
from typing import Optional

logger = logging.getLogger(__name__)

PYTHON313 = r"C:\Users\Owner\AppData\Local\Programs\Python\Python313\python.exe"

# Resolve操作スクリプトのパス
_WORKER_SCRIPT = os.path.join(os.path.dirname(__file__), "davinci_worker.py")


def _run_worker(command: str, params: dict | None = None, timeout: int = 120) -> dict:
    """
    Python 3.13のワーカースクリプトを呼び出してResolve操作を実行する。

    Args:
        command: 実行するコマンド名
        params: コマンドに渡すパラメータ
        timeout: タイムアウト秒数

    Returns:
        {"ok": True, "data": ...} or {"ok": False, "error": "..."}
    """
    payload = json.dumps({"command": command, "params": params or {}})

    try:
        result = subprocess.run(
            [PYTHON313, _WORKER_SCRIPT],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Timeout after {timeout}s"}
    except FileNotFoundError:
        return {"ok": False, "error": f"Python 3.13 not found: {PYTHON313}"}

    if result.returncode != 0:
        stderr = result.stderr.strip()[-500:] if result.stderr else ""
        return {"ok": False, "error": f"Worker crashed (code {result.returncode}): {stderr}"}

    # ワーカーの標準出力からJSON結果を取得（最後の行）
    lines = result.stdout.strip().split("\n")
    for line in reversed(lines):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    return {"ok": False, "error": f"No JSON output from worker. stdout: {result.stdout[-300:]}"}


# --- 公開API ---

def connect() -> dict:
    """Resolveに接続して情報を返す"""
    return _run_worker("connect")


def create_project(name: str) -> dict:
    """新規プロジェクトを作成"""
    return _run_worker("create_project", {"name": name})


def get_current_project() -> dict:
    """現在のプロジェクト情報を返す"""
    return _run_worker("get_current_project")


def create_timeline(name: str, width: int = 1920, height: int = 1080,
                    fps: str = "30") -> dict:
    """タイムラインを作成"""
    return _run_worker("create_timeline", {
        "name": name, "width": width, "height": height, "fps": fps,
    })


def insert_title(text: str, duration_frames: int = 150,
                 font_size: float = 0.1, position_y: float = 0.5,
                 font: str = "Yu Gothic UI",
                 color: dict | None = None) -> dict:
    """Fusion Title (Text+) をタイムラインに挿入し、テキストを設定"""
    params = {
        "text": text,
        "duration_frames": duration_frames,
        "font_size": font_size,
        "font": font,
        "position_y": position_y,
    }
    if color:
        params["color"] = color
    return _run_worker("insert_title", params)


def import_media(file_paths: list[str]) -> dict:
    """メディアファイルをメディアプールに読み込む"""
    return _run_worker("import_media", {"file_paths": file_paths})


def append_to_timeline(clip_names: list[str] | None = None) -> dict:
    """メディアプールのクリップをタイムラインに追加"""
    return _run_worker("append_to_timeline", {"clip_names": clip_names})


def render(output_dir: str, filename: str = "output",
           format: str = "mp4", width: int = 1920, height: int = 1080) -> dict:
    """タイムラインをレンダリングして書き出す"""
    return _run_worker("render", {
        "output_dir": output_dir,
        "filename": filename,
        "format": format,
        "width": width,
        "height": height,
    }, timeout=300)


def close_project(delete: bool = False) -> dict:
    """プロジェクトを閉じる（deleteがTrueなら削除も）"""
    return _run_worker("close_project", {"delete": delete})
