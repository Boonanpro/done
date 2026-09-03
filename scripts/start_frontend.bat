@echo off
REM Dan Frontend auto-start wrapper (2-server layout, 2026-09-03).
REM   3000: dashboard as a PRODUCTION build  (scripts/frontend_prod.py start; builds first if none)
REM   3001: artifact preview as a DEV server  (scripts/start_preview_dev.bat, HMR)
REM Both start hidden (no console window). Logs: frontend-prod-3000.log / frontend-dev-3001.log
setlocal
set "REPO_ROOT=%~dp0.."
call "%REPO_ROOT%\scripts\start_preview_dev.bat"
"C:\Program Files\Python310\pythonw.exe" "%REPO_ROOT%\scripts\frontend_prod.py" start >> "%REPO_ROOT%\.tmp\frontend_prod_start.log" 2>&1
if errorlevel 1 (
  "C:\Program Files\Python310\pythonw.exe" "%REPO_ROOT%\scripts\frontend_prod.py" restart >> "%REPO_ROOT%\.tmp\frontend_prod_start.log" 2>&1
)
endlocal
