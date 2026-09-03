"""Higgsfield CLI 実行ファイルの解決。

タスクスケジューラ起動のコア/サンドボックスは npm グローバル bin が PATH に
乗っておらず、裸の "higgsfield" は [WinError 2] で死ぬ（2026-08-21 実発生）。
which → %APPDATA%/npm の順で実体パスに解決する。
"""
import os
import shutil
from pathlib import Path


def cli_arg_safe(text: str) -> str:
    """改行を含む引数は .cmd シム(cmd.exe)がコマンドラインをそこで切断し、
    後続引数が全て消える（2026-08-21 実測: width/height 消失）。空白系を単一スペースに潰す。"""
    return " ".join(str(text).split())


def higgsfield_cli() -> str:
    found = shutil.which("higgsfield")
    if found:
        return found
    appdata = os.environ.get("APPDATA")
    if appdata:
        for name in ("higgsfield.cmd", "higgsfield"):
            cand = Path(appdata) / "npm" / name
            if cand.exists():
                return str(cand)
    return "higgsfield"
