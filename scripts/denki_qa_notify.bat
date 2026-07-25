@echo off
rem Denki Q&A answer-notify poller (every 15 min)
cd /d D:\done
"C:\Program Files\Python310\python.exe" scripts\notify_denki_qa.py >> D:\done\.tmp\denki_qa_notify.log 2>&1
