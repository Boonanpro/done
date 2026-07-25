@echo off
rem Denki knowledge daily refresh (fetch new Q&A -> redeploy if updated)
cd /d D:\done
"C:\Program Files\Python310\python.exe" "D:\done\scripts\refresh_denki_knowledge.py" --deploy >> D:\done\.tmp\denki_refresh.log 2>&1
