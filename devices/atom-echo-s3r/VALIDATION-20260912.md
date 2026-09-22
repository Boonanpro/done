# Foundation, fixed tunnel and APK checkpoint

## Delivered runtime

- Local frontend production build: `.next-prod-1789188552`.
- Local authenticated chat: messages visible in 1547 ms cold / 922 ms reload
  in a fresh headless context. The user's desktop browser was not controlled.
- Cloudflare zone active, named connector healthy. Public HTTPS checks passed
  with normal certificate verification and process-only public DNS lookup.
  Anonymous API denied; authenticated profile succeeded; SSE hello arrived
  at 32 ms and heartbeat at 15063 ms on the same open connection.
- User confirmed `https://dan.paina.info` opens on mobile data.
- Home resolver propagation completed. After clearing the Windows DNS cache,
  normal HTTPS access (no DNS override) succeeds on the home Wi-Fi. Login
  page: 141 ms; authenticated profile succeeds; anonymous API denied;
  SSE hello: 32 ms, heartbeat: 15032 ms. Evidence stays private in
  .tmp/dan-named-tunnel-public-check.json.
- Named connector restart and repeated launcher calls preserve the legacy
  connector PIDs and avoid duplicate named processes. Readiness returns 200.
- Watchdog parses and executes under Windows PowerShell after preserving a
  UTF-8 BOM; scheduled task result is 0.
- Galaxy S25: APK `app.done.dan` 1.0.5 / versionCode 3 installed with `adb
  install -r`. APK signature matches the previous install; no uninstall or
  application-data clearing. Previous APK backed up privately in `.tmp`.
- Embedded app.config and JavaScript bundle both contain `dan.paina.info`.
  App runtime version is 1.0.5 to separate it from old 1.0.4 OTA updates.
- APK login succeeded on the home Wi-Fi and the voice-device test room was
  visible, with app.done.dan confirmed as the foreground package. One test
  message posted through the local API appeared without any phone refresh
  or navigation, observed 2.23 seconds after submission. Evidence:
  .tmp/dan-apk-wifi-acceptance.json. No other room received test messages.
- Phone DNS initially failed through the existing Safeguard VPN. Reconnecting
  it restored resolution. Its stop flow also disables the accessibility guard;
  that guard was restored and verified as enabled and bound. VPN type 1 and
  dev.dan.safeguard were verified active. No protection list, private DNS,
  router settings or paid lock settings were changed. This result does not
  prove the VPN had blocked the domain; stale resolver state is consistent
  with the observed recovery.

## Automated verification

- Android release build succeeded: 767 tasks, 8m 35s, arm64-v8a.
- Mobile TypeScript check passed.
- 16 Python voice tests passed, including synthetic acoustic echo processing.
  The isolated checkout uses the existing local audio dependency directory.
- Two tunnel recovery tests passed.
- Five Node test scripts passed: shared session refresh, API retry/revocation,
  pairing boundaries, standby drain and interrupted worklet playback.
- Scoped frontend TypeScript check passed. The repository references ignored
  denki knowledge/site sources; existing local source/dependency directories
  were linked for resolution and unrelated ignored API routes excluded from
  this check. These links and temporary check config are not committed.
- Staged files checked for exact saved provider/device/session secrets: none
  found. Credentials, DNS backups, APKs and live device configuration stay local.

## Remaining acceptance

1. Switch existing Vercel clients/artifact backends and retire legacy quick
   tunnels only after compatibility checks; the installed APK uses the new
   hostname but legacy web clients still have their transition route.
2. Long-duration voice renewal, phone screen-off/network-change recovery,
   attachment transfers and voice WebSocket behavior on the new route.

The scoped checkpoint is prepared in a separate worktree/branch. Unrelated
editor, browser-management and other in-progress workspace changes are not
included. The voice device implementation from the previously pushed voice
branch is included so the new foundation files have their dependencies.
