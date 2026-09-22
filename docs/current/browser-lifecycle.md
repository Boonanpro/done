# Room browser lifetime (2026-09-11)

## Failure and fix

Windows Codex CLI 0.154.0 puts stdio MCP processes and their descendants into
a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (observed flags: 8192).
`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` separates the console, not that
Job Object. A normal `codex exec` answer/exit therefore killed Chrome, even
though the model never requested a close. A `CREATE_BREAKAWAY_FROM_JOB` probe
failed with WinError 5; adding that flag alone was not a fix.

Room browser launch now belongs to Dan Core. The MCP worker requests the room's
CDP endpoint from `/internal/browser/session` and only attaches to it. A failed
Core connection is an explicit error; there is no fallback to a CLI-owned
browser. Existing standalone scripts without a room retain the legacy path.

The private API requires a local connection, no Origin header, and an opaque
token stored under the account's `.ai_secretary` directory. It accepts room IDs
and lifecycle operations, never executable paths, profile paths or shell code.
Profile/port allocation is serialized. The live browser command line must
match both the room profile and CDP port before reuse or shutdown, preventing
an old port file from targeting another room's browser.

## Holds and cleanup

`browser` exposes these actions to both Claude and Codex through the shared
tool definition and runtime rules:

| Action | Behavior |
| --- | --- |
| `hold`, with `reason` | Preserve an existing live page while waiting for the user. Does not invent a future task. |
| `release` | Clear holds and restart the idle grace period. Does not close the page. |
| `session_status` | Report liveness/holds without creating or navigating a browser. |
| `close` | Explicitly close this room's browser and confirm it stopped. |

Observing a login URL or password input automatically records an authentication
hold. Waiting/authentication holds are written atomically into the profile's
`dan_browser_state.json` and survive MCP/CLI and Core process restarts. Release
the hold when the handoff/authentication is finished. A manual user hold and an
authentication hold are separate entries; releasing only the authentication
entry does not remove a manual user hold.

The Core reaper skips held rooms and rooms with active browser-holding watches.
It skips cleanup if watch state cannot be read, or a hold file is damaged.
Otherwise the existing 30-minute idle policy applies. Browser shutdown sends
CDP `Browser.close` (closing tabs alone can leave background/headless Chrome
alive), waits for the port to stop listening, and limits fallback termination
to verified profile processes. Holds/launch and cleanup use the same room lock.

Holding a page does not keep the model thinking after its answer. Autonomous
later checks and reports still use the existing `watch` mechanism. User input
in the same chat starts a new turn which reconnects to the retained page.

## Validation

- `python -m pytest tests/test_browser_lifecycle.py tests/test_browser_recovery.py tests/test_browser_fast_actions.py -q --disable-warnings`: **51 passed**.
- `python scripts/check_browser_lifecycle.py`: real GPT-6 Astra / Codex CLI,
  two independent CLI runs against an isolated Core API and real Chrome.
  The same live document survived both answers. Input entered between turns
  was read by the next turn. Aged held state survived cleanup; releasing it
  allowed cleanup while another held room remained alive.
- Final isolated evidence: `scratch/browser-lifecycle-proof-1789133836/result.json`.
- Production Core and sandbox were restarted after confirming 68 chat rooms
  had no active execution and there were no active production jobs. Both
  health endpoints and the live browser-manager endpoint were verified.
- Production smoke evidence: `scratch/browser-lifetime-investigation/live-result.json`
  (separate empty test profile, no user website or credentials).

An additional broad `test_salonboard_browser_policy.py` run found an existing
policy violation in `scripts/open_salonboard_login_prefilled.py` (direct login
URL / persistent-context launch); that file was not changed by this fix.
Workspace-wide scope checking also reports unrelated pre-existing unclassified
paths. All files changed for this fix classify as `infra`; no commit or push
was performed.

Implementation: `app/services/browser_lifecycle.py`,
`app/core/api/browser_routes.py`, `app/tools/browser.py`, and the shared
`app/agent/v2/tools.py` / `app/agent/cli_runner.py` contracts.
