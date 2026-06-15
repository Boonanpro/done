@echo off
rem 電管ナレッジ 朝1回の自動更新（新着だけ取り込み→更新があれば本番反映）
cd /d D:\done
"C:\Program Files\Python310\python.exe" "D:\done\scripts\refresh_denki_knowledge.py" --deploy >> D:\done\.tmp\denki_refresh.log 2>&1
