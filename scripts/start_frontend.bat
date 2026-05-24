@echo off
REM Dan Frontend (Next.js) auto-start wrapper
REM Called by Windows Startup; launches `npm run dev` minimized on port 3000.
REM Bind to 0.0.0.0 so the app is reachable through the Tailscale IP.
cd /d D:\done\frontend
start "Dan Frontend" /min "C:\Program Files\nodejs\npm.cmd" run dev -- --hostname 0.0.0.0 --port 3000
