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


def local_file(value: str | None) -> str | None:
    """Windows の頃に記録したファイルの場所（D:\\done\\uploads\\…）を、今の機械の場所にする。

    2026-11-12: Mac に移った後、制作ライブラリの画像とAIで作った素材が全部エラーになっていた。
    素材の台帳が「D:\\done\\uploads\\production-assets\\…」のまま残っていて、ファイル自体は
    Mac の同じ場所にあるのに見つけられなかった。読み替えられない場所（C:/Users/… など）はそのまま返す。
    """
    if not value or len(value) < 3:
        return value
    if not _WINDOWS and value[1] == ":" and value[2] in "\\/":
        value = localize(value.replace("\\", "/"))
    return shared_file(value)


# 世代ごとのコードの写し（dan-workspace/releases/<世代>/）では、uploads・.data・.tmp は動いているダン
# （LIVE_ROOT）の同じフォルダへのつなぎ（symlink）になっている（scripts/core_release.py link_shared）。
LIVE_ROOT = _place("DAN_LIVE_ROOT", "D:/done", "done")
_SHARED_TOPS = ("uploads", ".data", ".tmp")


def shared_file(value: str | None) -> str | None:
    """写しの中の住所（…/releases/<世代>/uploads/…）を、動いているダンの本物の住所にする。

    2026-11-17: エディターの冒頭の演出・LINE特典の映像が再生で出なかった。画面用の写しの住所が
    「dan-workspace/releases/db23980566c8-c975ac/uploads/…」のまま台帳に書かれていて、その世代の写しが
    掃除で消えると、ファイルは done/uploads に残っているのに見つけられなかった。"""
    if not value or "/releases/" not in value:
        return value
    head, _, tail = value.replace("\\", "/").partition("/releases/")
    parts = tail.split("/", 2)
    if head != DAN_WORKSPACE.as_posix() or len(parts) < 3 or parts[1] not in _SHARED_TOPS:
        return value
    return str(LIVE_ROOT / parts[1] / parts[2])


def real_dir(path: Path) -> Path:
    """つなぎ（symlink）を解いた本物のフォルダ。ここから作った住所は世代の写しが消えても残る。"""
    try:
        return path.resolve()
    except OSError:
        return path
