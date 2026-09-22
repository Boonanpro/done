# Voice conversation repair — 2026-09-17

## Acceptance status

**Not complete.** Real synthetic Japanese speech was sent through Live 1 WebRTC, with real Jev routing, real search and separate real worker file tasks. Received audio, transcripts and tool timing were recorded. This verifies more than tool receipt, but does not establish handset/headset acoustics or human-rated naturalness.

Targets: ordinary reply onset median <=1 s and p95 <=2 s; correct factual answers; no unintended execution on questions/negations; final results spoken back; context retained across follow-up questions. Reply onset and useful result arrival are separate measurements. The latency targets remain unmet.

## Repairs

- Distinguish conversation, information requests, reservation cancellation and cancellation of an existing job. Questions/small talk must not rewrite the current job.
- Require final user speech and a proposal-bound semantic approval for irreversible confirmation. Preserve the existing proposal revision and ownership checks. A short-lived signed internal proof avoids racing the asynchronous transcript save; non-voice callers retain the existing checks.
- Resolve final-transcript/deferred-approval races in the shared voice client.
- Remove backend transport instructions and the lengthy worker approval policy from the speaking model's context. Keep a concise approval requirement and the full policy on the worker.
- Return current results/status, without replaying old work instructions as fresh speech.
- Search now requests query-relevant advanced snippets, rather than truncating basic snippets to 400 characters. Jev selects a supporting source; uncertain or unsupported results go to the worker. Selected evidence alone is returned to speech.

## Actual audio evidence

Files are in `.tmp/voice-conversation-trial/`; each named trial has `.json` events and `.wav` received audio. These files are local test artifacts, not committed recordings of the user's calls.

| Trial | Observed outcome |
|---|---|
| `intake-audio-before-20260917` | Reproduced generic repeated clarification, approval becoming a new job, and ordinary questions altering the proposal. |
| `intake-audio-final-20260917` | Seven spoken turns: reservation cancellation, retracted approval, status, explicit approval, result and small talk. No confirmation on retraction; one later confirmation and spoken completion. Median onset 2.213 s, p95 3.691 s. Financial executor was a fixture; no real reservation was cancelled. |
| `natural-current-20260917` | Sixteen spoken turns, all answered. Retained corrections and remembered the gift recipient after a topic change. Median onset 1.831 s, p95 2.143 s. This is not proof of overall human-rated conversational quality. |
| `real-work-audio-final-20260917` | Real public-information search and real Astra worker file creation/readback in an isolated test directory. Results returned in speech. File task took roughly 26 s; not a speed pass. |
| `real-work-audio-v2-20260917` | Failed factual answer from irrelevant search snippets. Kept as failure evidence; not counted as a passing test. |
| `production-spoken-20260917` | Real deployed session/backend, search, follow-up and recall. Correct answer, but useful search answer took roughly 27 s because evidence checking triggered another worker investigation. |
| `search-source-spoken-20260917` | Revised source selection used actual search without worker delegation; correct answer and follow-up. Locally loaded intake with deployed search, not a fully deployed-session proof. |
| `production-source-final-20260917` | Deployed revised source selection. ASR produced katakana ヨナゴ; search lacked the specific route's booking rule, so it correctly fell back to the worker. Correct useful answer took roughly 26 s. The speed improvement is not reliable across ASR variants. |

## Other verification

- Sixteen search evidence fixtures exercised the actual source-selection intake with real Jev: seven supported and nine unsupported correctly separated. Small sample, not a general accuracy guarantee.
- Twelve semantic approval holdouts exercised real Jev, including questions, negations and changed reservation targets. No affirmative confirmation for the negative cases.
- Python regression tests cover intake, Live session instructions and confirmation binding. Shared-client tests cover both final-transcript/deferred-result arrival orders.
- Frontend production build and mobile TypeScript check passed.

## Delivery

- Sandbox reloaded after checking idle work and closed voice sessions. Core was not restarted.
- Frontend production build `.next-prod-1789655867` started on port 3000.
- Android preview OTA published for runtime `1.0.25`: group `fd00c946-185d-4cf2-95a5-74b823d514ac`, update `01a0afd3-1dc3-722e-81c5-013b19718140`.
- Phone was disconnected. OTA publication is verified; download/application on the handset is **not** verified. No native firmware or APK installation was performed.

## Remaining work

1. Improve search robustness to speech-derived place names without hardcoding this route or trusting generic results. Current worker fallback preserves accuracy at a large latency cost.
2. Reduce ordinary turn latency; current measurements exceed the target. Do not equate acknowledgement latency with answer latency.
3. Real browser worker execution still takes tens of seconds. This work does not establish fast purchase/refund flows.
4. Recheck handset/headset behavior after the OTA is applied. Atom handoff, simultaneous video audio, and physical microphone behavior were not tested here.

No success claim should collapse these remaining limitations into “voice performance fixed.”
