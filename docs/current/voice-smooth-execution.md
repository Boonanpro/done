# Voice screen and execution work — 2026-10-31

Room 393bf4c2-0d5c-4157-89dc-9b89592517ba. Owner approved continuous screens, quick short commands, and accurate partial UI reading. No phone calls (including test calls) authorized.

## Implemented, not shipped
Browser: existing tool-host Playwright page, CDP screencast, latest JPEG only, room-authenticated MJPEG endpoint, fetch stream parser and predecoded image replacement. Viewer lease stops idle capture after 30 seconds. Dead producers stop rendering as live. No new authenticated browser profile.

29 relevant Python checks pass, including real CDP smooth scrolling and room ownership/anonymous denial. Node parser checks fragmented frames and size bounds. Isolated actual tools -> actual API -> current React UI recording succeeded: 15 frame replacements during smooth scroll; tool completion 0.8 seconds (NOT speech latency). Evidence .data/voice-smooth/result.json, after.png, recordings/02580dd7c0bf178333b5f6a25cbf340a.webm. Delivered file /api/v1/files/voice-smooth-browser-proof-20261031.mp4, 8.8 seconds, no speech, no cuts, HTTP206 video/mp4. Stage state is isolated, no real call made.

## Continue here
- Android continuous screen is not implemented; bind to the exact phone serial, stop child recorders on session close, verify on development S24 only. Do not mistake owner S25 for test phone.
- Fast short commands and partial reading not yet changed. Do not claim all applications are fast/accurate.
- Current effective voice settings are gpt-live-1, backend gpt-6.1-terra medium, voice shida. Shared instructions already match chat; long jobs use gpt-6-astra. Investigate task handoff: start_work truncates task to 2000 and drops all recent dialogue if combined length exceeds 2600; command_center accepts 2800 except parallel12000. Preserve full source via a bounded reference/structured context, not silent clipping or inferred new approval.
- Need integrated speech test without placing a call; if real call essential, phone prohibition requires explicit owner approval. Current proof is ONLY screen continuity.
- Finish review, tests, map documentation, ship once grouped; verify live endpoints/frontend. Production unchanged.

## Test setup
Run Next from frontend cwd (not root) on an available port. 3002 belongs to another task (collab-comfort), never stop it. Generate ignored artifact-sources.css with frontend/scripts/wire-artifact-tailwind.mjs first. For this harness use BACKEND_URL=http://127.0.0.1:8017 and Next port3017. scripts/check_voice_live_screen.py runs isolated API8017 and uses existing Dan host browser. It does not use real speech. Whole-project TypeScript has missing untracked denki-knowledge/sitemap in a new worktree; resolve test fixture without committing generated unrelated files.
