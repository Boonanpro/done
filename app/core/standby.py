"""
控えのダン（DAN_STANDBY=1）

ダンを別の機械へ移す間、移す先でもう1つのダンを動かして確かめる。2つのダンは
同じデータベースを読むので、控えが見張り・メール・公開などの共有の仕事まで回すと
部屋が二重に起こされる。さらに控えの「止まった作業の片付け」は、本番のダンが
進めている作業を止まった物と見て閉じてしまう。控えは会話と画面だけを受け持ち、
共有の仕事は本番のダンに任せる。

控えの印は環境変数 DAN_STANDBY=1 か、ファイル ~/.dan/standby。ファイルなら、起動の
仕組み（Windows の見張り役・Mac の launchd）を変えずに切り替えられる。控えの機械は
外からの入口（dan.paina.info のトンネル）も起こさない（start_named_tunnel.ps1）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


STANDBY_FILE = Path.home() / ".dan" / "standby"


def is_standby() -> bool:
    return bool(os.environ.get("DAN_GENERATION")) or os.environ.get("DAN_STANDBY", "0") == "1" or STANDBY_FILE.exists()


# 作業の記録（agent_runs.metadata.machine）に、どの機械で始めた作業かを書く。片付けの見張り（run_reconciler・
# run_recovery）は自分の機械の作業だけを見る。本番の Mac が、Windows の控えで動いている会話（Windows の道具が
# 起こすもの）を「中身が無い」と見て閉じないため。印の無い古い記録は今までどおり扱う。
MACHINE = sys.platform + ("@" + os.environ["DAN_GENERATION"] if os.environ.get("DAN_GENERATION") else "")


def run_is_mine(run: dict) -> bool:
    machine = (run.get("metadata") or {}).get("machine")
    return not machine or machine == MACHINE
