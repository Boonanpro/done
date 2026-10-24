"""
ダンが使うフォルダの場所

Windows では今までどおり D: の下を使う。Mac / Linux ではホームフォルダの下に
同じ名前で置く（~/done, ~/dan-workspace, ~/dan-archive, ~/done-artifacts）。
環境変数があればそれを優先する。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_WINDOWS = sys.platform == "win32"


def _place(env: str, windows: str, name: str) -> Path:
    value = os.environ.get(env)
    if value:
        return Path(value)
    return Path(windows) if _WINDOWS else Path.home() / name


# ダン自身のコード（このファイルが置かれている木）
DONE_ROOT = Path(__file__).resolve().parent.parent
# CLI が作業するフォルダ（提案書・ジョブの作業場所など）
DAN_WORKSPACE = _place("DAN_WORKSPACE_DIR", "D:/dan-workspace", "dan-workspace")
DAN_ARCHIVE_ROOT = _place("DAN_ARCHIVE_ROOT", "D:/dan-archive", "dan-archive")
DONE_ARTIFACTS = _place("DAN_ARTIFACTS_REPO", "D:/done-artifacts", "done-artifacts")


def posix(path: Path) -> str:
    """'D:/dan-workspace' のように / 区切りの文字列にする（今までの書き方と同じ形）。"""
    return path.as_posix()


def localize(text: str) -> str:
    """指示文に書かれた Windows の場所を、今動いている機械の場所に置き換える（Windows ではそのまま）。"""
    if _WINDOWS or not text:
        return text
    for win, here in (
        ("D:/dan-workspace", DAN_WORKSPACE.as_posix()),
        (r"D:\dan-workspace", DAN_WORKSPACE.as_posix()),
        ("D:/done-artifacts", DONE_ARTIFACTS.as_posix()),
        ("D:/dan-archive", DAN_ARCHIVE_ROOT.as_posix()),
        ("D:/done", DONE_ROOT.as_posix()),
        (r"D:\done", DONE_ROOT.as_posix()),
    ):
        text = text.replace(win, here)
    return text
