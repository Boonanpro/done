# Core releases without a global idle barrier

The stable entrance listens on 9100 (Core) and 8100 (Sandbox). Once
`~/.dan/generations/enabled` exists, local Next builds use those ports. Explicit
backend environment variables and Vercel remain unchanged. The original
9000/8000 processes retain browser ownership, room event feeds, shared pollers,
and artifact endpoints. Do not terminate these service processes as part of a
worker release. Updating those shared services is a separate maintenance scope;
this change does not make their in-memory work transferable.

`python scripts/core_release.py prepare` creates a detached immutable release
worktree and starts a Core/Sandbox pair on free 92xx/82xx ports. It starts no
shared pollers and checks both health responses before becoming eligible for
activation. `activate ID` atomically changes the pointer for new requests.
Failures leave the active pointer intact. `restart_dan_core.py` uses this path
once enabled; it does not schedule another AI turn to check for idle time.

During installation, activate first, then run `install_gateway.py` on the Mac,
then rebuild the frontend with `frontend_prod.py restart`. The existing Core,
calls and jobs are retained. Existing active chat runs are recorded as legacy
owners and stay on 9000 until their authoritative state finishes. Never change
routing by killing a listener. First installation requires no global restart.

Each ongoing chat room and voice session records its owning generation and
process identity. Message reservations cover the gap before a run is created.
The gateway keeps each HTTP stream/WebSocket on its selected process. Finished
old generations are retired only after all live ownership records and gateway
connections are gone. No timeout force-kills active work. Release source trees
are retained because detached jobs can still import from them.

User artifact code remains in its existing live service. A release's documented
Sandbox routes go to its worker; unknown paths go to 8000. This avoids mounting
live artifact workers twice and preserves newly-added artifact endpoints.

New jobs use `queue_owner=process`, a separate runner process and OS locks for
job ownership and four concurrent slots. Core can lose its connection without
closing the runner's pipes. File events wake the durable dispatcher. A runner
that died after starting is failed for reconciliation, never automatically
replayed. Existing legacy jobs retain their original owner; no migration kills
or restarts them. Approval and control records are unchanged.

Voice settings in `~/.dan/voice-settings.json` are read as one snapshot at new
call creation. Write them atomically with `voice_settings.save`. A current call
keeps its existing snapshot. Invalid settings reject the new call rather than
silently switching to an unintended model.

Validation includes process-group termination with a continuing detached job,
duplicate dispatch, stale PID reuse, preservation of calls/turns during pointer
switch, reservation races, streamed responses/cookies, no retry of failed writes,
and retirement only after calls and streams finish. No real phone call or
financial action is used by these tests.
