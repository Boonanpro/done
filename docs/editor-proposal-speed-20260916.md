# Visual proposal iteration, 2026-09-16

## Acceptance target

Natural Japanese speech through the actual LIVE1/WebRTC/editor/Codex CLI route:

- Initial pair of useful comparison samples displayed within 30 seconds of utterance end.
- Color, entrance timing, and text revisions displayed within 10 seconds each, three consecutive turns.
- Unrequested composition properties preserved exactly; prior versions remain in history.
- No explanatory paragraphs or detail disclosure in the visual cards.
- Report presentation only after the client has rendered it; distinguish media failures.

These are acceptance measurements, not universal service latency guarantees.

## Implemented

- `revise_presentation`: immutable revision by item ID and JSON Pointer replacements. Validates the complete result before saving. Available to the conversation agent and production MCP worker.
- `composition.defaults`: shared layer properties reduce repeated authoring without changing the renderer or restricting design choices.
- Short editor tool turns use the application tools directly; native shell and configured MCP servers remain available in the separate production worker. ChatGPT-authenticated Codex CLI remains the backend, with no API-key fallback.
- Browser returns presentation readiness and media load errors to the model. Embedded external playback is explicitly unverified.
- A displayed result requests speech once; subsequent backend explanations remain readable context instead of requesting another announcement.
- Actual text colors, sizes, content and canvas appearance accompany the display result. Results arriving while Dan speaks wait for the speech boundary before requesting the report; the UI updates immediately.
- Direct editor turns use medium reasoning; the separate production worker and shared `CodexTurn.prepare` default remain high. No replacement lightweight model was introduced.

## Measurements so far

All times are utterance end to client display, not just tool execution.

| Trial | First comparison | Color | Entrance timing | Text |
|---|---:|---:|---:|---:|
| Direct tools, high reasoning | 48.65 s | 5.53 s | 7.67 s | 6.77 s |
| Shared settings, medium reasoning | 22.65 s | 8.41 s | 8.19 s | 9.84 s |
| Appearance delivery check | 21.95 s | 8.07 s | 12.24 s | 8.32 s |
| Final, speech-boundary reporting | **18.46 s** | **9.56 s** | **7.74 s** | **9.11 s** |

Direct-tools trial: `D:\done\scratch\visual-voice-direct-tools\conversation.mp4`.
All three revisions passed exact preservation checks. Only the requested color, keyframe offsets, and text fields changed. Initial comparison target remained unmet in this trial.

The first two trials used a specific cream-color request. Later trials asked for a warmer but readable color; the initial comparison request remained unchanged. Timings vary: the appearance-delivery check exceeded the revision threshold once. The final run meets the acceptance target, not an all-requests latency guarantee.

Verification: 31 Python tests and 17 client tests passed. Actual browser checks confirmed removal of details/explanatory paragraphs and distinguished successful presentation from a failed image load. Final field-by-field comparison proves only colors, entrance keyframe offsets and the first text changed in the respective user turns. No main-video timeline was edited.

Final recording: `D:\done\scratch\visual-voice-report-verified\conversation.mp4`.
Machine-readable acceptance: `scratch/visual-voice-report-verified/acceptance.json`.
Deployed UI screenshot: `scratch/visual-voice-report-verified/deployed.png`.
Video/audio review confirmed natural synthetic user speech, actual animated comparisons, and matching completion reports after all three changes. It also observed an early overlapping backchannel at 0:14–0:19 and a roughly seven-second quiet wait at 0:34–0:41. Natural dialogue is not universally solved.

Regular sandbox was restarted only after recent voice sessions were closed and no production jobs were active. Port 8000 is healthy (PID 39464 at deployment). Its actual page was opened, latest saved presentation displayed, and new readiness/reporting functions verified. No Core restart, frontend build, commit or push was performed.

This acceptance covers comparison and narrowing of animated subtitle samples. Web-wide sourcing, long-form finished-video quality and external embedded-player availability were not established by this test.
