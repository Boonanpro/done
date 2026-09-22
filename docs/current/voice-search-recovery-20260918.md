# Voice search and session recovery — 2026-09-18

## Changes

- Search evidence checks no longer launch an Astra investigation automatically when no source is selected. The response reports missing evidence instead.
- Jev evaluates whether each source supports the current question independently, using the recent dialogue. Equivalent valid sources no longer have to compete for an 85% selection probability.
- The same Jev request selects a complete supporting paragraph. Only that passage and its source title are delivered for speech, capped at 450 o200k tokens. Long JSON/source fragments are not individually announced. Search failures also produce an explicit response.
- Room intake session ownership, room, pending tool call IDs and history survive a sandbox restart in a local SQLite store. Loading this state never executes a tool. Closed and expired sessions cannot be restored; foreign users cannot load them.
- A genuinely unavailable session (HTTP 409) closes the mobile media connection and presents a restart control instead of asking the voice model to explain reconnection repeatedly.
- Previously requested voice UI caption removal is included in the mobile OTA; icon selected states and accessibility labels remain.

## Verification

- Python: 27 tests passed, covering owner checks, restart after a tool was issued, result consumption without reexecution, duplicate result rejection, hangup after state restoration, expiry and close.
- Client: 40 tests passed, including lost-session media shutdown and a single coherent evidence append.
- Real Live 1 audio, real Jev and real search API were exercised with Done room context. In `done-fast-search-recovery-v7`, the museum question ended at 9.922s, search evidence returned at 12.344s, and substantive answer text began at 13.172s. This is a repeated-query test, not a general latency guarantee; search caching can affect it.
- The bus query was transcribed incorrectly in several trials. The final trial reported missing evidence instead of inventing an answer or launching another worker. Proper-name recognition remains a limitation.
- Clearing the test process's in-memory intake state during the live session still allowed the final spoken hangup to execute. This is a controlled memory-loss test, not a claim that all network disruptions have been tested.
- Initial physical-phone trial confirmed the new caption-free UI, mute state, post-unmute transcription, and spoken hangup. It also exposed a missing-result silence issue that was fixed before the final OTA.
- Final physical-phone test used the installed final OTA in Done: mute/unmute, a spoken museum-hours search, a correct single answer (Saturday 09:30–20:00, last admission 30 minutes before close), then spoken hangup returning to the home screen. The native log recorded one search call and one 102-character evidence append, with no Astra delegation. Evidence arrived about 3.85s after the test WAV finished; this is evidence-delivery latency, not a separately measured physical audio-onset time.

## Delivery

- Sandbox final update: PID 33428 when deployed.
- Frontend build: `.next-prod-1789667436`, started on port 3000.
- Android OTA: `01a0b07e-8c07-76c1-a09b-d02f42dbf0b3`, runtime 1.0.25, preview branch.
- No purchase, refund, external message, or worker mutation was performed by these search trials.
- The initial three and final four phone-test messages were deleted by exact message ID and verified absent. User conversation history was preserved. Headless trials did not write transcripts into the room.
