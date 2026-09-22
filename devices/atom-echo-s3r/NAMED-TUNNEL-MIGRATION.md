# dan.paina.info migration

## Current status (2026-09-12, verified follow-up)

- https://dan.paina.info is live through the fixed named tunnel. Cloudflare
  zone is active, delegation has propagated to the home resolver, and the
  local connector readiness returns HTTP 200.
- Ordinary home Wi-Fi access now passes with normal certificate verification
  and no DNS override: login 141 ms, anonymous API denied, authenticated
  profile succeeds, SSE hello 32 ms and heartbeat 15032 ms. Windows DNS cache
  was cleared; no machine-wide DNS or router setting was changed.
- Galaxy S25 APK 1.0.5 / versionCode 3 is installed and both embedded config
  and bundle use this hostname. Login and the voice-device test room work on
  home Wi-Fi. A new test-room message appeared without refreshing the phone,
  observed after 2.23 seconds. Safeguard VPN and accessibility protection are
  active after reconnecting its stale DNS path.
- Zone: 0fa50b10b6c466fb08a06288386f5667.
- Named tunnel: dan-paina / 941103c5-38cb-405d-b76f-88b15544d727.
- All five original Name.com DNS records were copied as DNS-only and checked
  against both assigned authoritative servers. Name.com delegation uses
  kevin.ns.cloudflare.com and stevie.ns.cloudflare.com. No DS was returned
  by the DNSSEC API. Private migration backups remain in .tmp.
- Connector token stays in the owner's .cloudflared/dan-paina.token, never
  source or process arguments. The watchdog uses scripts/start_named_tunnel.ps1.
  Legacy recovery preserves this connector.
- Evidence: .tmp/dan-named-tunnel-public-check.json and
  .tmp/dan-apk-wifi-acceptance.json. See VALIDATION-20260912.md for limits.
- Legacy Vercel/quick-tunnel clients and artifact routes remain active until
  their compatibility checks are complete. Phone screen-off/network-change
  recovery and long-duration voice operation remain separate acceptance work.

## Initial discovery (historical)

Authorized: fixed tunnel on dan.paina.info; keep local performance work separate.
Before migration, DNS used Name.com nameservers. Dan's credential
vault contains working Name.com API credentials, Cloudflare login credentials,
and a valid Cloudflare Workers API token. No cloudflared account certificate
was found locally. Never copy credential values into this document.

## External prerequisites (historical, resolved)

Name.com API access to paina.info is verified. Domain details, all five DNS
records (no next page), and the DNSSEC API response are backed up privately in
.tmp/paina-dns-before-migration.json. Inspect DNSSEC contents before delegation.
The Cloudflare token can list the account but returns no paina.info zone;
zone creation was rejected with HTTP 403 for missing account.zone.create
permission. No provider settings have been changed. Both the dedicated new
headless profile and the older Cloudflare profile stop at human verification.
The existing token needs zone creation/DNS and Cloudflare Tunnel management
permissions before API setup can continue; preserve its existing permissions.
The verified active token ID is 5b6011f55e7aeeb4cb7bc7e1d2727dec (an identifier,
not the bearer secret). Its dashboard display name is "Edit Cloudflare Workers",
verified by matching actor.token.id/name in the account audit log. Dan found
this path and Codex independently confirmed the ID/name match via API.
At the user's request, Dan was asked in the voice test room to identify its
display name and use existing management access to add permissions if possible,
without operating the user's browser or changing DNS/delegation/services.
Dan confirmed that the saved token cannot manage API-token permissions and no
usable alternate management credential was found. Dashboard editing is still
required; no permissions or DNS settings have been changed.
For the standard free full-zone setup, add paina.info to Cloudflare and copy
the existing records. Verify DNSSEC/DS consistency before changing delegation.
Preserve the existing website and mail destinations. Nameserver values must
come from the user's actual Cloudflare zone, not a template.

## Target and transition

- Named Cloudflare Tunnel -> local production frontend on port 3000.
- Host dan.paina.info maps to that tunnel. The frontend already routes API
  paths to core 9000 / sandbox 8000. Keep local origin destinations local so
  the public endpoint cannot proxy recursively back into itself.
- The example ingress sends a localhost Host header to avoid artifact-domain
  routing. Verify HTTPS redirects, cookies, origin checks and WebSockets using
  the real public hostname before switching clients.
- Start alongside the working quick tunnels for validation. Do not run the
  existing start_tunnel.py migration blindly: it kills all cloudflared processes.
- Update supervision to recognize the named connector. The current watchdog
  assumes two cloudflared processes and restarts quick tunnels when count < 2;
  this must change before retiring the quick tunnels.
- Once validated, change APK API base and the public frontend's backend routing
  to the stable origin. Existing APK builds and published artifact sites need a
  transition path; do not break their current endpoints prematurely.
- Stop URL-change-driven Vercel redeploys for the named path.

## Acceptance checks

1. Valid TLS and authenticated login/refresh; anonymous protected API denied.
2. SSE first event arrives before stream closure; later events arrive
   individually rather than as a batch. Check the actual APK path too.
3. WebSocket and attachment upload/download behavior.
4. Connector restart retains URL, reconnects automatically, triggers no deploy.
5. Galaxy on mobile data with Tailscale off: login, room load, continuous updates,
   screen-off and network-change recovery.
6. Existing paina.info site, mail and subdomains remain functional.

Local page speed is not claimed fixed by this migration. Track it separately in
FOUNDATION-FIXES-20260912.md and .tmp/dan-local-room-latency.json.
