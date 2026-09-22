# Proactive consultation follow-through — 2026-09-23

Prior ownership fix published first: `1dcf9c3` on GitHub main.

## Change

The Live delegation policy previously excluded short confirmations/ordinary
conversation, while a trailing paragraph asked it to delegate new consultation
information. A simple duration answer could therefore be acknowledged without
ever calling the sheet writer.

There is now one delegation policy. New creative facts, answers, corrections and
reference decisions trigger the backend, including short answers. Greetings,
small talk and explanation of existing results do not require it. Live asks the
next concrete question or makes a proposal using the resulting sheet, rather
than asking the user which field to fill in.

Backend instructions require saving the facts during that request, preserving
unrelated fields on corrections, and returning a useful next question/proposal.
An explicit absence of materials is a confirmed answer, not an undecided field.
The backend reads state on its first request; it need not reread every turn.

This follows the separation of conversational delegation conditions and backend
tool procedures in the [official Live prompting guide](https://developers.openai.com/api/docs/guides/live-prompting).

## Real audio evidence

`python -m scripts.check_editor_consultation_audio` sends synthesized Japanese
speech through the actual deployed Live WebRTC handler. It does not inject a
backend request, call the sheet tool directly, or ask the voice to record a memo.
The room is isolated. Four normal utterances cover the initial request, multiple
answers, a duration correction, and agreement to the proposed direction.

Observed save delays from the end of input audio: 6730, 4656, 3092, 4766 ms.
All four saved without prompting. The duration changed from 15 to 10 minutes;
other fields were unchanged. The final sheet had all eight fields resolved or
explicitly deferred, and direction agreement, before a production handoff.

Spoken continuation included a comparison question about the desired treatment,
then offers to make a composition plan. This verifies proactive conversational
continuation for this test, not every genre or long interview.

Two harness problems were found and corrected, not hidden:
- A WebAudio constant-zero source is necessary to continuously send silence
  between clips, matching microphone behavior. The earlier recording without it
  is retained separately and is not the conversation-quality evidence.
- The initial oracle forbade every production handoff. The final user agreement
  followed a specific offer to make the plan, so handoff was appropriate. The
  corrected evaluation verifies agreement/readiness precede it and blocks real
  media production at the test boundary. A final spoken error in the recording
  is caused by that original test stub rejecting the handoff, not a real failed
  production task. Production execution is outside this test's claims.

Files: `scratch/consultation-audio-20260923/result.json`, `conversation.webm`,
`turn-0.png` through `turn-3.png`. `--evaluate` reevaluates captured evidence
without spending on another call. Also verified: 12 existing Python Live/sheet
tests. The application sandbox was restarted after checking no active calls or
production jobs. Existing embedded pages need reopening to use a fresh session.
