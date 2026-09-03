@echo off
rem Denki knowledge daily refresh (fetch new Q&A -> redeploy if updated)
cd /d D:\done
"C:\Program Files\Python310\python.exe" "D:\done\scripts\refresh_denki_knowledge.py" --deploy >> D:\done\.tmp\denki_refresh.log 2>&1
rem AI一次回答の知識基盤も追いかける（新着記事の本文全文とYouTube字幕を取り込み、検索用にベクトル化）
"C:\Program Files\Python310\python.exe" "D:\done\scripts\build_denki_kb.py" --fetch --subs --embed >> D:\done\.tmp\denki_kb_daily.log 2>&1
