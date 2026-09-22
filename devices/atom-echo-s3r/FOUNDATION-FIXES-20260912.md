# Dan connection and loading fixes — 2026-09-12

## Follow-up: real cold-room rendering

The user subsequently confirmed successful voice pairing. A refresh credential
is now saved and real voice playback events were observed.

Authenticated cold-browser checks exposed a separate startup deadlock in
ProjectChatPanel: the project query was disabled until the bundled room request
finished, but the bundled request required the room ID from the project query.
With no cached project, neither could start. Fixed by allowing project lookup
while the cached room ID is absent.

Production build .next-prod-1789188552 was built and deployed successfully.
scripts/check_local_chat_bootstrap.py verifies actual visible message elements,
not only HTML or page-load completion. On the user's specified project:
fresh context 1875 ms, reload 953 ms. Before the fix, a fresh authenticated
context still had no message request after 10–12 seconds. This establishes the
cold-start fix, not the absence of every possible future API/DB stall.

Fixed-tunnel migration remains separately pending Cloudflare/DNS access; see
NAMED-TUNNEL-MIGRATION.md. No DNS or public client endpoint was changed.

## Evidence

- Voice pairing used localStorage on localhost:3002 while the user was logged
  in on localhost:3000. These are different storage origins.
- The saved voice access token had expired; no refresh token was saved.
- The generic API client redirected on 401 before the auth hook could refresh,
  and returned a never-settling promise during the redirect.
- Tailscale reported NeedsLogin with no Tailscale IP. The old 100.76.90.51
  address timed out. This is separate from Dan account authentication.
- Python HTTP probes: localhost:3000 took ~2.03–2.05 seconds, while 127.0.0.1
  took 0–0.015 seconds. The frontend listened on IPv4 only. After dual-stack
  binding, localhost, IPv4 and IPv6 loopback returned in 0–0.016 seconds.
- Headless Chromium after the listener fix: login TTFB ~10 ms, DOM ~90 ms,
  load ~380 ms. These are anonymous login measurements, not authenticated
  large-room render timings.
- Shared tsconfig accumulated historical production and development output
  directories. An obsolete generated route validator broke a subsequent build.

## Implemented and locally deployed

- One UI origin: http://localhost:3000/atom-voice. The voice worker now uses the
  production frontend. The dedicated development server on 3002 was stopped
  and removed from voice startup.
- Pair through a same-origin server route below the refresh-cookie path.
  Forward the existing HttpOnly refresh cookie to Dan core, validate access
  through the controller, and store both tokens. Device key stays server-side.
  Pair/stop reject other origins and unauthenticated requests.
- Voice controller refreshes paired credentials periodically and before
  connection, saves replacements atomically under a lock, and removes stale
  worker cookies. Credential renewal does not operate the user's browser.
- General API requests share a refresh attempt and retry once; network/503
  failures preserve login. Invalid refresh sessions still require login.
- Cookie-only sessions can initialize browser auth without localStorage.
- Production listener supports IPv4 and IPv6. Local/IP hosts skip custom
  domain lookups; literal IPv6 host parsing is corrected.
- Production builds use their own TypeScript configuration and cache instead
  of accumulating historical generated types in the development config.

## Verification

- Later production build .next-prod-1789188552 also fixes cold project loading:
  project lookup no longer waits for the room request that itself needs that
  project's room ID. Fresh headless context with real authorized credentials
  confirms messages visible (not just the shell).
- After named-tunnel preparation, the same local room check measured cold
  1547 ms and reload 922 ms. Evidence:
  .tmp/dan-local-room-bootstrap-after-tunnel.json.
- Windows PowerShell ParseFile detected a syntax error caused by decoding
  the UTF-8 watchdog script without a BOM. Saved it as UTF-8 with BOM;
  parsing and execution now pass, and scheduled task reports exit code 0.
- Legacy quick-tunnel recovery is scoped to the owned 9000/8000 connectors;
  two regression tests verify named/unrelated processes survive recovery.
  Fixed connector gets independent idempotent startup in the watchdog.

- Successful full production build and deployment: .next-prod-1789186908.
- Python: test_voice_credentials.py (4 tests), test_headless_voice.py (2 tests).
- Node: test_session_refresh.cjs, test_api_session.cjs,
  test_atom_pair_route.cjs passed.
- Live same-origin unauthenticated pairing returns 401; unrelated origin 403.
- Voice page returns 200 on localhost and both loopback address families.

## Pending user / longer-running checks

- User to pair once from their existing authenticated browser on port 3000.
  No claim of successful real-account pairing until controller confirms it.
- Tailscale account reauthentication requires the user's SSO interaction;
  the CLI authentication link was supplied. Verify assigned address afterward.
- Historical room-message API spikes (roughly 4–11 seconds) remain in server
  logs. Existing DB timeout/offloading changes were preserved. Anonymous page
  timings do not establish that all authenticated room-load stalls are fixed.
- Long-duration renewal and sleep/restart recovery need observation. Unit
  tests verify renewal behavior without claiming a multi-day hardware soak.
- Sound firmware from the prior task is installed; the user approved both
  ready and standby cue audibility and volume.
