# Real audio acceptance — 2026-09-16

Actual deployed editor / LIVE1 WebRTC / ChatGPT-authenticated Astra CLI.
Local Microsoft Haruka speech entered the outgoing WebRTC audio track; replies
were received as audio, not simulated model responses. The browser was isolated
and the user's projects were not edited. No Qwen process was used.

## Valid run

- Room: voice-handoff-5b00147a
- Content: beaecbf4-ed4d-4032-a5a4-4728d2e9acb0
- Provider-confirmed connection duration: 249 seconds; close_requested received.
- Evidence: scratch/live-audio-20260916-continuous/
- Conversation, events and UI errors: final.json (no page errors).
- Mixed input/output recording: conversation.webm and conversation.mp3.
- Actual UI: screen.png, inspected; YouTube candidate card was visible.
- Separate Gemini 3.8 Flash audio review: conversation.review.txt.

The spoken sequence covered two alternative visual approaches, a reference
request, a status question while searching, a follow-up about the other approach,
and an interruption. Live distinguished moving 3D reconstruction from still-image
storytelling, answered the status question without screen inspection, explained
the displayed reference, and changed response after the interruption.

Reference presentation at 1789524697789ms was forwarded at 1789524697790ms.
Its spoken transcript began 0.774 seconds after presentation. Search/presentation
still took 41.885 seconds after the reference-request audio ended (53.759 seconds
from playback start). Only one backend turn was started; no superseded restart.
The recording review identified a roughly 14-second quiet period during search.
Reference explanation was lengthy (roughly 45 seconds). No claim that every
conversation or human speaking style is validated. Full reference footage and
representative segment were not validated by the test, only card rendering.

## Invalid preliminary run

scratch/live-audio-20260916/ used a synthetic source that did not maintain the
audio clock during silence (about 123 wall seconds versus 59 model seconds).
It produced truncated replies. Its timing/naturalness results are excluded from
product acceptance. The corrected harness maintains a continuous low-level input
and pronounces 3D as スリーディー rather than SAPI's サンディー.

## Reproduction

`python scratch/live_audio_acceptance.py` runs the deployed editor in a fresh
test room and records the exchange. It uses paid Live API time and real CLI
reasoning. It does not generate paid image/video assets. Close occurs in finally.
`scratch/review_live_audio.py <mp3>` is a supplementary model-based audio review,
not a substitute for human preferences or full product acceptance.
