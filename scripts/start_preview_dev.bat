@echo off
REM Dan artifact preview server (Next.js dev, HMR) on 0.0.0.0:3001.
REM The dashboard itself runs as a production build on 3000 (scripts/frontend_prod.py).
REM Artifact/scratch/preview pages need hot reload for Inspector / voice edits, so they
REM are served by this dev server; the dashboard points its preview iframe here
REM (NEXT_PUBLIC_PREVIEW_PORT=3001 in frontend/.env.local).
REM Logs: <repo>\frontend-dev-3001.log / .err.log
setlocal
set "REPO_ROOT=%~dp0.."
set "NEXT_DIST_DIR=.next-preview"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath 'C:\Program Files\nodejs\npm.cmd' -ArgumentList 'run','dev','--','--hostname','0.0.0.0','--port','3001' -WorkingDirectory '%REPO_ROOT%\frontend' -RedirectStandardOutput '%REPO_ROOT%\frontend-dev-3001.log' -RedirectStandardError '%REPO_ROOT%\frontend-dev-3001.err.log' -WindowStyle Hidden"
endlocal
