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


## Continuation 2026-10-31 12:50 JST
Implemented, still not shipped:
- start_work keeps the full task and full passed dialogue, labels it as a handoff (not a fabricated verbatim utterance); internal-only command_center voice_handoff permits 64000 characters. Oversize rejects explicitly instead of executing partial instructions. Public params cannot raise limit. Durable task persistence and late constraints tested.
- scroll_screen is a native short operation, no discovery/read roundtrip; uses current artifact page_id or exact external screen/source/phone serial. Refuses stale scene or unidentified phone. Browser ordinary scroll uses smooth behavior. Actual browser -> API -> UI test via scroll_screen helper: 12 frames, 0.88s tool completion (not speech latency).
- Android worker binds serial, owns only its adb/ffmpeg subprocesses, stops on host death/viewer lease expiry. Initial screenshot seeds static H264 decoder; actual idle device first frame0.76s. Recording restarts only at180s limit. Child cleanup confirmed after Host termination. First actual phone capture saw10 distinct frames, but screenshot was OneUI update page, so this is not proof of successful Settings scrolling.
- Phone read(query=...) returns only matching lines without renumbering refs, retains whole screen internally, duplicate matches visible and zero match explicit. Browser already has bounded find/locate, internal artifacts already have inspect(query).
- tests:57 screen/work/command tests passed, plus6 phone reading/lock/paste checks. Command-center test generation source isolated from machine runtime (prior assertion depended on active generation).
- Android UI harness --phone failed once before static-frame seeding, returning still PNG. During follow-up observation phone showed pornblock app rather than expected Settings; do not assume exclusive device ownership or turn this into evidence of Settings scrolling. No settings/security changes made. No calls made.

Next: verify Android actual UI and gesture continuity while dev S24 is available, exercise phone static seeding/lifecycle failure tests, run full combined suite and TypeScript with artifact fixture, review and grouped ship + production verification. Audio-through-execution evidence remains absent; no calls may be initiated without explicit authorization. scripts/check_voice_live_screen.py now accepts --phone; test ports3017/8017. No public publication yet. Tests call real fixed scroll helper without ASR/Live.

## Continuation: Android screen proof and release checks
- Actual development S24 Settings screen verified before navigation; no other recorder process was present. Opened Settings, returned from update details without changing settings, and scrolled the Settings list.
- Actual Android -> API -> React harness passed: 32 frames during scroll, 1.09 seconds for tool completion (NOT speech latency). Screenshot phone-ui-after.png shows Settings; recording d2957f2b91bd527521183d11219eaef3.webm is uncut and has no speech.
- Worker lifecycle checks now cover parent exit, expired viewer, decoder exit, owned child cleanup, frame cleanup and no retry on encoder failure.
- Combined relevant Python suite: 48 passed. TypeScript passed with a local ignored sitemap type fixture for deployment-owned denki-knowledge; frame parser checks passed.
- Remaining: production release/runtime verification and real speech-through-execution evidence. No test call authorized or placed.
