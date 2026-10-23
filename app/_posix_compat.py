"""
Mac / Linux でダンを動かすための読み替え

ダンは Windows で育ったので、子プロセスを窓なしで起こす指定（subprocess の
CREATE_NO_WINDOW など）と、msvcrt のファイル錠が多くのファイルにある。Mac には
どちらも無く、使った所で落ちる。app を読み込んだ最初に、同じ意味の物を
ここ1か所で用意する。Windows では何もしない。

- 窓の指定は Mac では意味が無いので 0（指定なし）にする。Popen は 0 なら受け付ける。
- msvcrt.locking（今の位置から nbytes を錠）は fcntl.lockf で同じ範囲を錠する。
  取れない時は Windows と同じく OSError を出す。
"""
from __future__ import annotations

import sys

if sys.platform != "win32":
    import fcntl
    import os
    import subprocess
    import types

    for _name in (
        "CREATE_NO_WINDOW",
        "CREATE_NEW_CONSOLE",
        "DETACHED_PROCESS",
        "CREATE_NEW_PROCESS_GROUP",
        "CREATE_BREAKAWAY_FROM_JOB",
        "CREATE_UNICODE_ENVIRONMENT",
        "IDLE_PRIORITY_CLASS",
        "BELOW_NORMAL_PRIORITY_CLASS",
        "NORMAL_PRIORITY_CLASS",
        "ABOVE_NORMAL_PRIORITY_CLASS",
        "HIGH_PRIORITY_CLASS",
    ):
        if not hasattr(subprocess, _name):
            setattr(subprocess, _name, 0)

    if "msvcrt" not in sys.modules:
        _msvcrt = types.ModuleType("msvcrt")
        _msvcrt.LK_UNLCK, _msvcrt.LK_LOCK, _msvcrt.LK_NBLCK, _msvcrt.LK_RLCK, _msvcrt.LK_NBRLCK = 0, 1, 2, 3, 4

        def _locking(fd: int, mode: int, nbytes: int) -> None:
            if mode == _msvcrt.LK_UNLCK:
                fcntl.lockf(fd, fcntl.LOCK_UN, nbytes, 0, os.SEEK_CUR)
                return
            shared = mode in (_msvcrt.LK_RLCK, _msvcrt.LK_NBRLCK)
            cmd = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
            if mode in (_msvcrt.LK_NBLCK, _msvcrt.LK_NBRLCK):
                cmd |= fcntl.LOCK_NB
            fcntl.lockf(fd, cmd, nbytes, 0, os.SEEK_CUR)

        _msvcrt.locking = _locking
        sys.modules["msvcrt"] = _msvcrt
