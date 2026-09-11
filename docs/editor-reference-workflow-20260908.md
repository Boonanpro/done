# Reference-led general video production — 2026-09-08

## Target

The three supplied examples are acceptance subjects, not supported genre limits.
Dan discovers references from the user's intent, shows real media, discusses the
direction, makes an appropriate playable draft, refines it, and finishes it.
The user need not explain why each example is impressive or write prompts.

## Research and remaining uncertainty

- Product motion: the first supplied video combines typography, product UI,
  camera movement and music. Editable code/graphics are a suitable implementation
  direction, not a verified identification of its author's source project.
- Presenter tutorial: the second supplied video describes a presenter + graphics
  workflow and mentions source footage and editing projects. The official related
  workflow is https://higgsfield.ai/blog/talking-ai-avatar-inside-claude . This
  establishes a supported general method, not that the exact posted video used
  every step of that article. Face/voice fidelity remains an empirical acceptance
  test with the user's own authorized material.
- Spatial shot: the third post claims Astra + Seedance 2.5. The public guide is
  https://higgsfield.ai/blog/seedance-2-5-prompting-guide . The exact handoff from
  the demonstrated 3D viewport to the generation service is still unverified.
  Do not assume depth/pose conditioning just from the split-screen demo.
- Analysis uses the Gemini Interactions API, Agentic for video. Source:
  https://ai.google.dev/gemini-api/docs/video-understanding . Model output remains
  fallible: the earlier reports incorrectly speculated that Astra was unreleased.
  Such guesses must not become executable recipes or reported facts.

## Implemented

- Shared `resolve_reference`, `read_references`, production `analyze_reference`.
  X public video/image resolution, public YouTube/direct media, room asset IDs,
  and public page OpenGraph media discovery. Page introduction images are explicitly
  labeled as images, never represented as inspected video.
- Per-room reference records linked to a content; original post text/source URL
  retained. No timeline mutation. Analysis is separate from first presentation.
  Results for identical questions and unexpired uploaded media are reused.
- `search_web_references` uses Gemini Google Search grounding directly. Only
  citation-backed URLs become candidates; Google's redirects are expanded to
  source URLs. This complements the existing YouTube search. Search is not viewing.
- Attachment picker, file drop, pasted files in the voice/editor page. Files use
  the existing authenticated upload endpoint and are linked as references without
  creating a generation job or toggling the microphone.
- A method catalog read on demand, with explicit readiness, inputs, draft approach,
  sources and validation. It is extensible and can combine methods. It does not
  imply all listed external generation routes have passed live quality tests.
- Agreed brief changes keep other fields, record revisions, and are submitted to
  an active production worker. Selected-reference changes are also delivered.
  Submission is not reported as worker application.
- External video playback fixed by a no-referrer page policy; YouTube/Vimeo
  iframes already specify their own strict-origin-when-cross-origin policy.

## Evidence

- Reference intake: 1.08s / 0.44s / 0.30s for the supplied three public X posts.
- Common Agentic path: 27.69s for a concise analysis of the 36-second video;
  processing_call steps confirmed; repeated identical query served from disk.
- Cross-source search for an unseen category (paper/stop-motion product ads):
  17.838s before redirect expansion was added. YouTube, Motionographer and
  Cartoon Brew sources returned. Motionographer article retrieval subsequently
  returned 429: source access is not universally guaranteed.
- Actual authenticated HTTP reference registration: 200. Real Chrome playback
  verified for all three videos (35.67s, 666.28s, 29.97s), including advancing
  currentTime. Playwright's bundled Chromium lacks the required H264 codec;
  Chrome was used to test the actual format. A separate referrer-related 403
  was reproduced and fixed, not dismissed as a codec issue.
- Real Realtime conversation, text input through the editor: reference URL request
  -> resolution -> actual video presentation in 9.4s, no production job.
  Room reference-conversation-9b7eb46e / dc889c54-d73e-42f4-bd2b-b28c3f9a1b35.
- 30 related Python tests passed, then the added upload reuse test passed with
  the five reference tests. Browser attachment test passed with mocked upload
  boundaries; it does not prove native file-drop integration or actual voice UX.
- Main port 8000 restarted with no active jobs and no active voice session;
  API + Realtime presentation test used the restarted main service.

## Not complete

### Subsequent live draft and partial edit acceptance

- Real editor conversation created an original 12-second bookstore draft from the
  motion reference, with editable text, book shapes, movement and original temporary
  music/effects. No paid generation. Job 35881dcc-cf7f-4a3a-9896-71a522f297d3
  committed 48 clips after validation and watch_render. Runtime 489.679 seconds:
  this is still too slow for the desired draft discussion loop.
- Contact sheet: uploads/reference-analysis-20260908/bookstore/contact.jpg.
  The content conveys a small bookstore after work; this is a draft, not a
  quality match to the supplied motion reference.
- The worker spent time reading editor internals to discover animation support.
  Added on-demand motion/property documentation and atomic apply_edits (up to
  100 native editing operations, rollback on failure). These changes happened
  after that worker started; no measured new-draft speedup is claimed.
- Text-only request without a selection identified the center book but requested
  confirmation. Repeating with that book selected applied its color change in
  13.56 seconds, including conversation. JSON comparison showed exactly one
  clip changed, and only effect_color changed; all motion keys, other clips and
  audio retained. Revision diff and composited frame are in the bookstore folder.
- Latest targeted suite: 24 passed, including atomic success/rollback,
  upload/analysis cache, search citations and direction delivery. This is not an
  actual microphone/native-window acceptance test.

- No full reference -> revised draft -> final quality acceptance yet for all
  three forms or for an unseen form. This release is not ideal-editor completion.
- Complex HTML/3D motion needs an editable project integration with the native
  editor; catalog entries alone do not implement this.
- Avatar service quality/identity preservation and viewport-to-video handoff need
  real validation. Paid video generation remains outside the current test budget.
- Native attachment/drop tests, reference playback after URL expiration and broader
  source access failures need additional work.
- Conversation ownership, natural mid-production revisions and end-to-end timing
  need realistic multi-turn acceptance beyond this one successful reference request.

Artifacts: uploads/reference-analysis-20260908 and the isolated reference acceptance
rooms. User production timelines were not changed by these tests.
