#!/usr/bin/env python3
"""
ダンコアを Windows ログオン時に自動起動するスクリプト。

タスクスケジューラだと管理者権限が必要なため、Windows スタートアップフォルダ
( shell:startup ) にショートカットを置く方式を採用。

このスクリプトを 1 度だけ実行すると、以降 Windows ログオン時に
scripts/dan_core_autostart.bat が自動実行され、ダンコア(9000) と
サンドボックス(8000) が立ち上がる。

使い方:
    python scripts/register_dan_core_autostart.py

削除:
    エクスプローラで shell:startup を開いて DanCore.lnk を削除
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

WRAPPER_BAT = r"D:\done\scripts\dan_core_autostart.bat"
SHORTCUT_NAME = "DanCore.lnk"


def get_startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA env var not set — are you on Windows?")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def main() -> None:
    if not os.path.exists(WRAPPER_BAT):
        print(f"[register] ERROR: wrapper not found: {WRAPPER_BAT}")
        sys.exit(1)

    startup_dir = get_startup_dir()
    startup_dir.mkdir(parents=True, exist_ok=True)
    shortcut_path = startup_dir / SHORTCUT_NAME

    # PowerShell でショートカット作成（COM経由）
    ps_script = (
        f'$ws = New-Object -ComObject WScript.Shell; '
        f'$sc = $ws.CreateShortcut(\'{shortcut_path}\'); '
        f'$sc.TargetPath = \'{WRAPPER_BAT}\'; '
        f'$sc.WorkingDirectory = \'D:\\done\'; '
        f'$sc.WindowStyle = 7; '  # 7 = minimized
        f'$sc.Save();'
    )

    print(f"[register] Creating shortcut: {shortcut_path}")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True, text=True, timeout=15,
        stdin=subprocess.DEVNULL,
    )
    if result.returncode == 0 and shortcut_path.exists():
        print("[register] SUCCESS!")
        print(f"  ショートカット作成: {shortcut_path}")
        print()
        print("動作確認:")
        print("  - 次回 Windows ログオン時にダンコアが自動起動します")
        print("  - 削除する場合: エクスプローラで shell:startup を開いて DanCore.lnk を削除")
    else:
        print(f"[register] FAILED (returncode={result.returncode})")
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
