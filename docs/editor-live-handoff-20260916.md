# Editor Live handoff repair — 2026-09-16

## Observed failure

The 09:35–09:44 JST editor session showed presentations at 09:42:57 and
09:43:11, but the combined backend commentary reached Live at 09:44:22.
`queueSpeech` intentionally did nothing for Live, while `runReasoning`
accumulated all text and appended it only after the whole tool loop.
Production polling also injected imperative prose about not treating an edit
as running. This vocabulary reappeared in speech.

## Changed

- Codex emits `message_complete` with the public message ID, phase and text.
  The browser delivers that message without waiting for the tool loop to end.
  Commentary is quiet context; answers are commentary appends. Private model
  reasoning is not forwarded. The final accumulated-text replay is removed.
- Successful presentation rendering immediately delivers compact item facts,
  including title, note (rationale/uncertainty), source and segment bounds.
  Duplicate presentation IDs are ignored. The duplicate render call is removed.
- Routine conversation work status remains local telemetry. Production polling
  updates a factual snapshot without sending periodic speech/context appends.
- On delegation the current room's work, active tools and most recent
  presentation are available to Live as quiet context and to Astra through
  the reasoning request's runtime context. Existing project_status and
  read_presentations tools remain available for fuller/history reads.
- Backend instructions request meaningful presentation notes and avoid
  re-summarizing already-delivered explanations. Live decides conversational
  timing rather than reciting internal status instructions.

## Verification

- 12 Node tests cover context targeting, preserving active work on additional
  speech, silent state updates, immediate deduplicated presentation delivery,
  delivery before a held-open reasoning stream finishes, no end-of-turn replay,
  microphone pause and report lifecycle.
- 15 Python tests cover the CLI adapter, Live configuration and reasoning input.
- Real ChatGPT-authenticated Astra CLI probes: two separate visual approaches
  were preserved; a follow-up explanation used no screen tools. Complete public
  messages arrived in 6.687 and 6.907 seconds. These are short text probes, not
  full voice-session latency or quality measurements.
- Probe script/results: scratch/check_editor_handoff_20260916.py and
  scratch/editor-handoff-20260916-results.json.

## Limits

No claim of verified natural voice behavior yet. Presentation tool success plus
local render invocation is not proof that an external video player loaded or
that the user watched the material. The meaning of alternatives still depends
on model interpretation; the probes do not establish reliability for all cases.
Gemini comparison work is separate and was not modified.

Reference: https://developers.openai.com/api/docs/guides/live-delegation
