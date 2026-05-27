# Salonboard StyleUp Stable Worker

Goal: run the current one-client Salonboard StyleUp flow without depending on the owner's daily PC.

## Target Shape

```text
Vercel frontend: https://salonboard-styleup-done.vercel.app
  -> BACKEND_URL
Windows VM or dedicated always-on Windows mini PC
  -> FastAPI sandbox backend on port 8000
  -> Playwright + regular Chrome profile
  -> SALONBOARD
Supabase
  -> salonboard_credentials
  -> salonboard_post_jobs
```

The frontend stays on Vercel. The browser automation moves from the owner's PC to one always-on worker machine.

## Worker Machine Requirements

- Windows 10/11 Pro or Windows Server.
- Google Chrome installed.
- Python 3.10 initially, matching the current working environment.
- Repository checked out at `D:\done` unless the startup script arguments are changed.
- `.env` copied from the current working backend with at least:
  - `SUPABASE_URL`
  - `SUPABASE_KEY`
  - `SUPABASE_SERVICE_ROLE_KEY`
  - `GOOGLE_GEMINI_API_KEY`
  - `SALONBOARD_ENCRYPTION_KEY`
  - `ALLOWED_ORIGINS=https://salonboard-styleup-done.vercel.app`
  - `FRONTEND_URL=https://salonboard-styleup-done.vercel.app`
- Chrome profile directory is isolated to the worker user:
  - `%USERPROFILE%\.ai_secretary\salonboard_normal_chrome_data`

## Backend Startup

From PowerShell on the worker:

```powershell
powershell -ExecutionPolicy Bypass -File D:\done\scripts\start_salonboard_styleup_backend.ps1 -HostName 0.0.0.0 -Port 8000
```

Health check:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing
```

For production, run the same script via Task Scheduler on login/startup, or wrap it in a Windows service after the first stable week.

## Public URL

Use one fixed HTTPS URL in front of the worker backend. Acceptable first-week options:

- Cloudflare Tunnel installed on the worker with a named tunnel and stable hostname.
- A small reverse proxy in front of the Windows VM.
- A VM public IP plus HTTPS reverse proxy.

Then set the Vercel environment variable:

```text
BACKEND_URL=https://<stable-worker-backend-host>
```

Redeploy the Vercel project after changing `BACKEND_URL`.

## Durable State

Post status is now persisted in Supabase table `salonboard_post_jobs`.

This means:

- `/api/v1/salonboard-styleup/post-status/{job_id}` survives FastAPI restarts.
- The UI can keep polling the same job after a backend restart.
- Operations can inspect recent jobs from Supabase if a client reports trouble.

The actual browser execution still runs in the backend process for phase 1. Moving execution into a separate polling worker is the next step after the one-client worker VM is stable.

## First Migration Checklist

1. Provision worker machine.
2. Install Chrome.
3. Clone/copy repo to `D:\done`.
4. Install Python dependencies.
5. Copy `.env`.
6. Run backend startup script.
7. Open the SALONBOARD login once on the worker if human verification is needed.
8. Configure stable HTTPS URL to the worker.
9. Set Vercel `BACKEND_URL` to the worker URL.
10. Run one real post with the current client.
11. Confirm `salonboard_post_jobs` has the job with `status=done`, `published=true`, and `style_id`.

## Cutover Rule

Do not onboard a second salon until the current client has at least one week of successful posts from the worker machine without using the owner's PC.
