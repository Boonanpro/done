@echo off
rem denkiouen.com SEO daily job (engines 1-3): evaluate 7-day experiments -> add 1 new guide page -> polish 1 near-top query -> IndexNow + sitemap
cd /d D:\done
set PYTHONIOENCODING=utf-8
"C:\Program Files\Python310\python.exe" -u "D:\done\scripts\denki_seo_engines.py" daily >> D:\done\.tmp\denki_seo_daily.log 2>&1
