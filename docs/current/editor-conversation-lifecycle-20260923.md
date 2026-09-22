# Editor conversation ownership — 2026-09-23

## Findings

The September 22 call restored 31 historical messages and injected a version-2
consultation memo containing `Resume this consultation...`. Its first answer
discussed old references for approximately 30 seconds. No commentary append or
queued completion delivery preceded that answer. The log does not establish the
exact provider-side trigger; it also contains an unexpected opening input
transcription despite the user's report that they had not spoken.

Library navigation retained the last content ID, including while disconnected.
Paused calls also retained ownership. Deletion was not reconciled with those
client caches. The room's contents file was empty when investigated, while the
failed session had still used the removed content ID.

## Changes

- Before starting voice and during status observation, reconcile owners against
  the authenticated room's existing contents. Remove deleted owners' local
  histories/memos, stop their transport, clear UI and reject stale native IDs.
- Explicit new-work creation resets even paused ownership. Normal navigation
  during an ongoing call retains its original work context.
- Save history before clearing the paused owner, avoiding writes to the browsed
  work's key. Only show status references belonging to the current view.
- Delete scoped backend turns/transcript rows along with the content; ignore
  late event batches for removed content IDs. Other works and source media remain.
- Ignore version-2 memos. Version-3 startup data is silent context, with no resume
  directive. Connection instructions distinguish background history from a new
  result notification.
- Late sheet updates cannot restore a deleted memo or notify another session.

## Verification

- Real editor page and actual create/delete APIs: old history/reference/memo,
  deletion while paused, new work -> 0 messages, 0 references, no memo or paused
  owner, all eight inspector fields unknown, no page errors.
- Actual Live connection handler, no microphone attached: fresh history and
  two historical turns, 15 seconds each, zero unsolicited output in both trials.
  This is not proof of every reconnect condition, nor a natural interview test.
- 53 Node behavioral checks, including ongoing reference navigation, explicit
  new work, deletion, stale native IDs, and late sheet completion.
- 38 Python checks covering deletion, Live configuration, consultation sheet,
  assistant routes and production lifecycle.

Evidence: `scratch/conversation-lifecycle-20260923/result.json` and
`new-project.png`. Reproduction: `python scripts/check_editor_conversation_lifecycle.py --live`.
The application sandbox was restarted only after no active calls/jobs were found.
Static editor code is served without a frontend production build; an already
open embedded page needs reopening. Proactive interview execution remains a
separate unresolved behavior from this ownership/reconnection fix.
