# LIVE1: speech context and reference browsing

Implemented in the native editor conversation panel:

- Keep a three-minute, bounded, session-relative history of editor views.
- Associate input transcript intervals with those views, including scene seeks,
  different timelines and the library (editor_visible=false).
- Persist associations with the original transcript and deliver them to Astra.
- Keep the editing project separate from the currently viewed reference.
- Do not cancel reasoning, drop queued delegation, clear pending questions, or
  discard completion notices just because another timeline was opened.
- Permit read-only timeline_frame inspection of another timeline in the same room.
- Provide set_edit_target for an explicit change of editing project; it updates
  the saved turn, scope and sequence hash, rather than redirecting by navigation.
- Send actual reasoning/job lifecycle state to LIVE1 and show tool activity in
  the existing single-line orb status. Poll production on the editing project.
- Publish editing highlights against the editing project, not the reference.

Validation:

- node --test tests/editor_live_context.test.cjs: 3 passing cases, delayed
  transcript after navigation, multi-view utterance/library, backend failure.
- python scripts/test_editor_live_screen_context.py: actual HTML/JS in headless
  Chromium, mocked backend. A speech -> B navigation -> A tool context -> idle
  status and voice state. No paid model requests or user project changes.
- pytest editor assistant routes/reasoning/dialogue/live: 32 passed.

Limits still requiring validation/work:

- Live model audio interpretation and natural responses have not been retested.
- The time origin currently uses receipt of session.started. Real transport
  clock skew, reconnects and fast continuous video require measured validation.
- This is editor state/frame access, not desktop/browser screen sharing.
- Timeline frames are rendered on request; historical pixels/revisions are not
  archived by this change.
- Astra Responses API dispatch remains unchanged; migration to Codex billing is
  a separate change, not implicitly included here.
