# Atom command center

The owner has one pinned project, marked `metadata.role=command_center`.
Text and voice share its chat history. Atom always connects to its configured
room, regardless of the project being inspected or delegated to.

`command_center` is shared by the text MCP and voice backend. It provides
project listing/search, history pagination and editor state, durable work
dispatch, and reporting. Identity comes from the authenticated session, never
model arguments. Source-room and target-project/room access are checked.
Read operations do not write chat history or start the target Dan.

## Command center home and answer reliability

`/command-center` is the dedicated web home (desktop and mobile browser).
The sidebar separates it from projects; old hub `/chat/<id>` links redirect
there. The existing chat component retains text, voice and tools, while the
home adds source-linked reply/decision candidates, outstanding work, reports,
and the actual Atom connection/wake-standby state. Native APK layout is not
changed by this web deployment.

Only projects marked `metadata.role=command_center` receive the hub role:
overview, priorities, errands and initial discussion. Sustained project work
should be proposed for a dedicated/existing project and handed off with
context after agreement. Ordinary project capabilities remain unchanged.

`command_center(overview)` and the home use one authenticated, user-scoped
background review. It reads the latest eight messages per project (first
5,000 characters each), and an isolated tool-free classifier proposes items.
Every accepted item must cite an existing message and an exact source quote.
The quote check establishes provenance, not semantic certainty: candidates
are not definitive obligations. Attachments, external services and older
unresolved matters are outside this snapshot; Dan can investigate with read
and its other capabilities. Partial/failed/uncertain reviews never mean zero
pending work. The interface shows coverage, uncertainty and timestamps.

Snapshots are private under `.tmp/command-center/<user>.json`. Concurrent
requests share a job; unchanged conversation fingerprints reuse both reviewed
and uncertain results. Retrieval/model failures can be retried. The home polls
lightweight cached state, not the model. A voice overview that is still running
returns progress without provisional candidates; completion is announced once
while that voice session remains connected. Text Dan can call overview again.

Voice tool calls now hold the continuation until all concurrent tools return,
including failures. Provisional delegate text remains activity only; the final
report is spoken once. Diagnostics record call IDs, action/project IDs and
result coverage/status without source text or credentials. Controlled test
utterances can temporarily mute input (maximum 180 seconds, automatic restore)
to distinguish tool scheduling from acoustic/user interruptions.

Work requests use the existing durable follow-up queue. The target room's Dan
executes the task in its own context. The poller relays its result or failure to
the originating project with a link to the work room. This does not require a
new tool in an already-running target session. A deterministic report message
ID connects the receipt to the report. While voice remains connected, Atom
checks for outstanding reports every three seconds and announces new results.
After standby/reconnection, reports remain in chat history; automatic spoken
replay of reports from the previous voice session is not implemented.

The prompt identifies the role and capabilities; it does not prescribe a
retrieval sequence. `delegate_to_dan` remains the command center's own deep
work mode, while `command_center(delegate)` runs work in a selected project.
Old mobile voice clients do not advertise these new tool capabilities. APK
text chat can use the command center; this change targets Atom/web voice.

## Provisioning and deployment

Run `setup_command_center.py --user-id UUID` from the repository root. It
reuses the owner's existing hub, pins it and writes `.tmp/atom-voice-room.json`.
The bridge and controller load that same private destination file; it is not
compiled into firmware. Restart both after changing it. No USB flash is needed.
Without the file, the legacy test room remains the fallback.

Deploy voice backend changes by restarting the sandbox. The follow-up relay
needs a core restart when no turns are running. Rebuild/start the production
frontend and reconnect the dedicated headless worker. Refresh idle text CLI
sessions when changing MCP tool formatting; their saved history is preserved.

## Verification, 2026-09-13 JST

- Atom connected to room `5e43d6b8-0f68-4113-a576-01bb39b84933` in project
  `2740d218-2d5b-4898-a950-048e8757f7a8` (Dan command center).
- Voice read the voice-device test project's actual latest conversation and
  answered in the command center. Text Dan found the same project through MCP.
- Voice dispatched a bounded arithmetic test to the test room. Its Dan
  returned 42; the relay saved the result in the command center, and Atom's
  voice session announced it. Audio output events and transcript were observed;
  physical audibility still needs the user's confirmation.
- Eight unit tests cover access boundaries, read-only behavior, receipts,
  report routing, relay failure, and the actual MCP result formatter. Two
  existing headless pairing/cancellation tests pass. Production frontend build
  succeeds. Detailed local acceptance artifacts stay in `.tmp`.
- Other project rooms were not used for write tests. The user's desktop
  browser was not controlled.
