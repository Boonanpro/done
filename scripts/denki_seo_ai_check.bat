@echo off
rem denkiouen.com SEO monthly job (engine 3): ask ChatGPT / Gemini / Claude 10 questions and record whether denkiouen.com is cited
cd /d D:\done
set PYTHONIOENCODING=utf-8
"C:\Program Files\Python310\python.exe" -u "D:\done\scripts\denki_seo_engines.py" ai-check >> D:\done\.tmp\denki_seo_ai_check.log 2>&1
