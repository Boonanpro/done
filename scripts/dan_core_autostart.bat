@echo off
REM Dan Core 自動起動ラッパー — Windows タスクスケジューラから呼ばれる
REM ログオン時にダンコア(port 9000)を起動し、サンドボックス(port 8000)を自動 spawn する
cd /d D:\done
"C:\Program Files\Python310\python.exe" scripts\start_dan_core.py >> D:\done\dan_core_autostart.log 2>&1
