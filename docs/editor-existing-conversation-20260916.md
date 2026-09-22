# Existing-conversation visual acceptance — 2026-09-16

## Goal

Test the user's actual long conversation and existing project, not only a fresh subtitle room:

- Answer a visual-style question with relevant content within 10 seconds of the end of speech.
- Show a playable 15-second sample within 90 seconds, without requiring selection of unrelated timeline clips.
- Preserve the original timeline and match spoken claims to the displayed result.

Source: room `a588ca6f-95b1-484a-a13d-cf7771ebffb8`, content `4772ab4b-47a4-4e49-a21d-011df8c40c8a`, failed turn `1a28593db87a424e96c1db6dcd6e9920`.
Tests clone content metadata and reuse media read-only in isolated observer rooms. They seed the actual conversation, including erroneous previous assistant replies. The original project hash is checked separately.

## Confirmed failures

1. A separate sample was sent through a timeline-edit selection guard and rejected. `execute_work` previously removed the legacy prepare flag but offered no explicit separate output destination.
2. Each delegation injected current production status into Live, even for a question about appearance.
3. Replaying old assistant utterances in the assistant role reproduced obsolete procedural speech. A real voice replay still said the old “制作実行中とは扱わない” wording after changing instructions alone.
4. Long backend results were divided into several commentary events. Each fragment invited speech, producing repeated explanations.
5. All historical screen observations were expanded again in every request. The reproduced production instruction reached approximately 480 KB, even though most screen traces were irrelevant to the current question.
6. Code-generated samples unnecessarily launched a separate production runtime and project/build/export workflow.

## Changes

- Restore prior conversation as speaker-attributed verbatim reference data, not assistant-role speaking examples. Keep the original messages in storage and pass original speech to Astra. Simplify Live's prompt using the official delegation policy labels.
- Keep current facts available to the backend; remove unconditional status injection into the voice model.
- Send a single commentary invitation per long result; earlier fragments are factual context.
- Only attach the latest utterance's screen observations directly. Old screen records remain available on demand. Worker handoff contains all utterances verbatim plus the source-record path.
- Add `execute_work.destination=presentation`: work can create a separate sample without selecting timeline clips. Its draft cannot commit to the original timeline. Legacy preparation remains distinct.
- Add generic `present_references.scene` for JavaScript/Three.js/DOM/Canvas previews. Local pinned Three.js r180, seekable host clock, pause/play, offscreen suspension, first-frame acknowledgement, surfaced script errors. No project installation or MP4 export before judging a code-generated sample.
- Run preview code inside an opaque-origin sandbox with restricted CSP, without parent DOM or Dan credentials. Public module routes expose only the two pinned Three.js files; license is included.
- Record loaded-client fingerprint, instruction fingerprint and history fingerprint at voice connection so test/runtime differences can be checked.

## Test iterations

- `actual-history-voice-1`: invalid harness input (PowerShell stdin encoding replaced Japanese with `?`); excluded from measurements.
- `actual-history-voice-2`: reproduced old procedural speech and repeated explanation; a 15-second 3D preview rendered, but speech incorrectly called it 12 seconds. Harness clone also used the wrong `editor_work` type; corrected to a list. Failed run, not acceptance.
- `actual-history-voice-3`: relevant visual answer started in 1.35 seconds; no obsolete status preamble. The sample still delegated to the slow full production path and exceeded 160 seconds. Failed run, not acceptance. Test-owned worker canceled.

- `actual-history-voice-4`: two previews appeared in 75.941 seconds, but speech recognition interpreted the request as two samples. Excluded from acceptance.
- `actual-history-deployed`: normal port 8000, relevant answer 1.32 seconds, correct single sample 108.38 seconds. Failed the speed target.
- `actual-history-final`: lazy keyframe inspection reduced a first-15-second inspection from roughly 31 KB to 3,771 bytes, but the sample still took 129.063 seconds. Failed the speed target; model latency/code volume varied.
- `actual-history-fast`: same GPT-6 Astra and medium reasoning, CLI Fast service tier. Relevant answer **0.880 seconds**, playable single 15-second sample **79.721 seconds**, self-revision **83.688 seconds**. Passed the stated targets on the normal server. This is an observed run, not a latency guarantee.

## Delivered and verified

- Recording: `D:\done\scratch\actual-history-fast\conversation.mp4`.
- Machine results: `scratch/actual-history-fast/acceptance.json` and `final.json`.
- Original and cloned timeline hashes unchanged; no browser JavaScript errors. Preview first frame and seeking at 0, 5, 10 and 14.9 seconds verified. Human-visible stills inspected; recording analysis confirmed three scenes, moving anonymous person, subtitles, silence, and matching spoken explanation.
- Voice review also found one awkward phrase and one Japanese reading ambiguity. Conversation is improved, not uniformly equivalent to the official ChatGPT application.
- The recording exposed a long wait with a generic status. Public Astra commentary now replaces the orb's single status line. A separate browser check using the actual reasoning-stream consumer verifies that it appears and clears on completion (`scratch/check_reasoning_status.py`, `status-line.png`). The full voice recording precedes this final UI-only change.
- Python: 55 passing relevant tests. JavaScript: 18 passing Live-context tests. Sandbox checks verify rendering failures propagate and preview code cannot access the parent DOM.
- Normal editor backend on port 8000 updated; existing open clients must reopen to load changed JavaScript. No user conversation was interrupted.
- Detailed transform keys remain available on explicit request; defaults summarize them without mutating the timeline. Skill reads now resolve installed user skills or return an explicit missing result, rather than successful empty content.
- Interactive editor CLI Fast uses the same model and reasoning effort. It consumes **2.5x subscription credits** under the published Astra Fast policy; this is not an API fallback or an automatic credit purchase. `DAN_EDITOR_SERVICE_TIER` can override the tier. Runtime reported `priority`.
- This validates consultation to a moving 3D draft sample, beyond subtitles. It does not establish finished-film quality, all possible requests, or completion of the entire editor vision.

## Follow-up: return to normal CLI tier

The user requested normal mode if Fast risks exhausting their allowance. A live `account/rateLimits/read` returned 58% of the weekly Pro allowance used, resetting 2026-09-19 22:46 JST. Local historical snapshots include 78% in the preceding week. Editor-only usage cannot be isolated from these account-wide percentages, so exhaustion is a risk, not a proven forecast. Three unused full-reset credits were also reported; none were redeemed.

Removed the default Fast tier. An actual CLI `thread/start` with `service_tier=null` returned `serviceTier=null` without making an inference request. The three editor CLI tests passed. With no running production jobs and latest voice sessions closed, the sandbox restart service deployed this change successfully (port 8000, PID 47084, healthy). The measured 80-second result above used Fast; it must not be presented as normal-tier performance.

The user subsequently explicitly requested restoring Fast after discussing the scope and available reset credits. Restored the default `service_tier=fast` for interactive editor turns only; an explicitly empty environment override still selects normal. Three CLI tests passed, no running production jobs or newer open voice session were found, and the normal sandbox was restarted successfully (PID 38164, healthy). No reset credit was redeemed.

## References

- https://developers.openai.com/api/docs/guides/live-prompting
- https://developers.openai.com/api/docs/guides/live-conversations
- https://developers.openai.com/api/docs/guides/live-delegation
- https://threejs.org/docs/
- https://learn.chatgpt.com/docs/agent-configuration/speed

These tests establish observed behavior for the tested requests, not a guarantee for every artwork, model response or external generation service.
