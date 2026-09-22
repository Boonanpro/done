# Proactive visual discovery — 2026-09-18

## Requested experience and acceptance

The user supplies purpose but cannot name a style. Dan should proactively show references, ask a concrete comparison question, retain partial likes/dislikes, and propose a useful next production experiment once direction is shared. No fixed questionnaire or mandatory full storyboard. Do not generate merely because a style was liked.

Targets: a comparison without the user asking to see references; a useful follow-up after vague feedback; a concrete next-step proposal; ordinary ranking/card insertion around 3 seconds, no unnecessary Astra dispatch for catalog comparison. Playback/network readiness is a separate measurement.

## Actual diagnosis

The user trial ending 05:12 JST showed purpose recall, references only after the user prompted, a Gemini-heavy replacement set, and a broad “what did you like?” question. Existing instructions already mentioned proactive discovery, but also exempted preference discussion from delegation.

Audio testing exposed two additional application defects:

- Speculative work fanned out across 1,178 references repeatedly for partial transcripts. The first purpose answer launched 29 decision requests.
- Only one reclassification was allowed after transcript revision. A second trailing correction discarded the comparison and fell through to Astra, which returned a preference summary rather than visuals.

## Changes

- Live instructions establish active discovery, concrete comparisons, partial preferences and moving toward a small production experiment. Phrasing and choice of experiment remain model decisions.
- Jev distinguishes endorsing a displayed option from asking to change it and treats a purpose answer in creative discovery as an opportunity to compare.
- Full-work retrieval receives the displayed references as well as original conversation, so relative references and rejected properties have context.
- Speculative retrieval waits for a short quiet boundary and permits one speculative request in flight. Changed text is re-evaluated; repeated corrections do not themselves launch Astra.
- Selection results convey the chosen title and a concise next-step hint. Facts remain valid JSON within the Live append byte budget.
- URL candidate facts explicitly mark publisher metadata, not watched footage. This final evidence-label addition was structurally tested after the recorded conversational run; improved factual speech from it is not yet audio-verified.

The official Live prompting guide was reviewed: https://developers.openai.com/api/docs/guides/live-prompting . Detailed retrieval/execution remains outside the live prompt.

## Verification

Three real LIVE1 WebRTC sessions, natural synthetic user voice (gpt-4o-mini-tts/marin), isolated test rooms, actual editor display path. First run was interactively steered; repeat runs used the same recorded four utterances. No forced dialogue responses. No user project edited.

Final run `visual-voice-cc82129e`:

1. Bare request → purpose/audience question, no arbitrary references.
2. Purpose + uncertainty, without “show me” → three references and comparison question.
3. “Quiet, but less polished, ordinary tired daily life” → updated two-reference comparison and follow-up question.
4. Direction accepted, advice requested without production → suggestion to compare a short daily sequence; no generation.

Measured audio-end-to-card insertion: initial 4,787 ms, refinement 2,685 ms. Retrieval itself: 1,464/1,699 ms. Baseline 8,795/9,525 ms. Purpose/refinement decision requests reduced from 29/20 to 3/4. Final four-turn run: zero Astra dispatches, no page errors. The initial ~3s end-to-end target was not met in the final run; do not call every turn instant. YouTube readiness is not included.

Python affected tests: 21 pass. JS editor context/lifecycle tests: 42 pass, including speech coalescing, new-utterance preservation and multiple trailing corrections. Final small evidence-label/prompt wording adjustment was not a fourth audio run.

Artifacts:

- `D:\done\scratch\proactive-discovery-verified\conversation.mp4`
- `D:\done\scratch\proactive-discovery-verified\final.json`
- `D:\done\scratch\proactive-discovery-verified\evaluation.json`
- Reporter: `scripts/report_proactive_discovery.py`

## Limits

This tests discovery behavior in one Vlog conversation, not all genres, finished-video quality, or a calibrated optimal narrowing algorithm. Most URL references still have metadata labels only. Live occasionally describes details not established by metadata; evidence delivery was improved, but full factual reliability is not proven. TTS transcription had minor word errors. User preference quality still requires real use. No data expansion was done in this change.
