@echo off
rem denkiouen.com SEO weekly job: ensure AI answers on all questions -> resubmit sitemap -> Search Console report
cd /d D:\done
"C:\Program Files\Python310\python.exe" -u "D:\done\scripts\denki_seo.py" weekly --days 28 --inspect-limit 12 >> D:\done\.tmp\denki_seo_weekly.log 2>&1
