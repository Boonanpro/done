@echo off
REM Dan Frontend (Next.js) auto-start wrapper.
REM Launches `npm run dev` fully hidden (no console window) on 0.0.0.0:3000.
REM Output is redirected to log files, so there is nothing to watch in a
REM terminal and no stray "Dan Frontend" window piles up when the watchdog
REM relaunches the frontend. Bind to 0.0.0.0 so the app is reachable via Tailscale.
REM Inspect logs at D:\done\frontend-dev-3000.log / .err.log if the UI misbehaves.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath 'C:\Program Files\nodejs\npm.cmd' -ArgumentList 'run','dev','--','--hostname','0.0.0.0','--port','3000' -WorkingDirectory 'D:\done\frontend' -RedirectStandardOutput 'D:\done\frontend-dev-3000.log' -RedirectStandardError 'D:\done\frontend-dev-3000.err.log' -WindowStyle Hidden"
