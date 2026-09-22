# Native editor: GPT-Live 1 migration

## Architecture

The native editor now defaults to GPT-Live 1 when the updated backend serves the
Live module. `?voice=realtime` retains an explicit rollback path.

Live owns listening, speaking, interruption, backchannels and conversational
judgment. It requests client delegation when research, inspection, presentation
or production needs tools. The app passes the editor's original, speaker-labelled
conversation to GPT-6 Astra. Live does not rewrite it into a task specification.
Simple edits use the existing direct editor tools; longer work keeps the existing
production worker, browser/PC tools and media services. Live receives results and
speaks naturally. No GPT-6 call is required for each conversational utterance.

Images and full tool results remain available to Astra. Live itself is the audio
front end, not the image inspector. Editor history is persisted independently of
ordinary project chat. Reconnection restores recent original messages; older
messages remain accessible through read_conversation.

## Why client delegation

Both official delegation modes were exercised against the actual API. Managed
Responses delegation successfully presented text but failed during a short
timeline creation and rendered-image check with `response_input_buffer_full`:
the session's appended application input is limited to 128 items / 32,768 bytes.
Truncating images or editor evidence to fit that budget would damage production.
Client delegation keeps the full backend capabilities outside that limit.

## Evidence

- Actual authenticated `gpt-live-1` session creation and browser WebRTC audio.
- In `live-voice-5383ef1d`, voice created a three-second black-background title,
  then changed only the title to 一息どうぞ. The saved draft's base_sequence and
  sequence are identical after normalizing that one text field.
- Creation report was actually transcribed as 「できたよ…」; revision report as
  「変えたよ。黒背景の中央に『一息どうぞ』が3秒表示になってる。」
  Incoming audio playback was measured separately from context acknowledgments.
- Revision tool committed at 02:29:19.667 UTC, following the first correction
  transcript at 02:29:13.311 UTC. This is one measured example, not a latency SLA.
- The default production page also passed the complete creation/revision test
  in `live-voice-101393c0`. Typed-only presentation passed in
  `live-text-75c7d4c0` without opening any voice connection.
- Graceful session closure produced `reason: close_requested` and final usage.
- 23 unit tests cover conversation history, production handoff, presentations
  and Live configuration. Browser tests cover uploaded image/video visibility,
  picker/drop, sender labels, retry, persistent mixed-media history and 3D.

Synthetic voice fixtures need continuous silence after the utterance. An ended
fake capture stops Live's frame clock, so context injection and speech can stop
even with an open data channel. Tests now send silence, like a live microphone.
Speech recognition can choose 一息 / ひと息 / ひといき; tests must account for
these spellings without accepting unrelated edits.

## Deployment and limits

The active user editor must not be killed. Native updates (removing the duplicate
status banner and enabling native file drop) are staged in the existing pending
installer. The guarded backend restart helper waits until native editors exit.
The core service on port 9000 is not restarted. Until that backend restart, an
already-open voice session continues with its previous implementation.

These checks establish voice-to-tools and feedback, not full creative quality
parity or superiority over the previous model. Natural human conversation,
reference discovery, sophisticated production and recovery during long work
still need continuous real-use evaluation.

## Official specifications consulted

- https://developers.openai.com/api/docs/models/gpt-live-1
- https://developers.openai.com/api/docs/guides/live
- https://developers.openai.com/api/docs/guides/live-delegation
- https://developers.openai.com/api/docs/guides/live-conversations
- https://developers.openai.com/api/docs/guides/live-migration
- https://developers.openai.com/api/docs/guides/live-prompting
- https://developers.openai.com/api/docs/guides/voice-webrtc?api=live
- https://developers.openai.com/api/docs/guides/voice-server-controls?api=live

## Post-deployment connection failure

Provider returned HTTP 500 with plain text `Internal Server Error`, including for a minimal model + client-delegation configuration without history or editor instructions. The original route attempted JSON parsing and raised a second 500; the browser then attempted to parse that plain-text failure as JSON. Both response parsers are now guarded; malformed successful responses and transport failures also return readable errors. Six Live unit tests pass. Updated backend PID 73384 was deployed by guarded restart, and the real production page now reports the provider 500 correctly. Voice connection remains blocked while the provider rejects session creation; no silent model fallback was enabled.

## Further diagnosis: prepaid credit exhausted

At 2026-09-11 03:08 UTC, the same API key returned `credit_balance_exhausted` / `insufficient_quota` on both Realtime 2.1 WebSocket and GPT-6 Astra Responses (HTTP 429). Evidence is in scratch/live-quota-diagnosis.json. Model metadata access still returned 200. Live WebRTC returned plain HTTP 500 and Live WebSocket returned output_creation_failed, with both client/Responses delegation and quartz/marin voices. Thus a prepaid balance blocker is confirmed; Live masking the same condition is the leading explanation, to be confirmed by retesting after funding. Official status had no listed active incident; targeted X searches found no matching current report. No new credit purchase was made.
