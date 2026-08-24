@echo off
rem 税理士メール監視 (10分間隔) — 新着があれば経費仕訳ルームでダンを起こす
cd /d D:\done
"C:\Program Files\Python310\python.exe" scripts\watch_zeirishi_mail.py >> D:\done\.tmp\zeirishi_mail_watch.log 2>&1
