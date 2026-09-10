# Reference-led editable motion acceptance — 2026-09-08

## Delivered behavior

- Text clips accept transform_keys, preserving editable text/style. Native GPU
  preview/export and the browser caption overlay evaluate the same full-canvas
  translation/scale at clip-relative time. Selection geometry follows motion.
- animate_clip accepts a small set of poses and produces linear, cubic-out or
  cubic-in-out motion for text, media and regions. apply_edits can batch it.
- Caption placement accepts an explicit visual lane. A lane equal to track count
  creates a new frontmost visual lane. Existing locked/hidden lanes reject placement.
- Region motion supports off-screen entry/exit and expansion beyond the canvas.
- Agent inspection now prepares the native caption cache and draws all captions
  with the native compositor. It no longer adds a second caption plane after the
  dump, which could disagree with lane order and the new motion.

## Concrete sample

- exports/yohaku-motion-8s.mp4 — original eight-second bookstore motion sample.
- Isolated room: reference-motion-50fc6377
- Content: 858a5710-1dd8-4ec4-9e4b-f6570909f0cf
- Reproducible authoring script: scripts/build_reference_motion_sample.py.
- Borrowed from reference 1: word additions/re-layout, eased arrivals, selection
  emphasis and a zoom hand-off. It is not a faithful reproduction or a benchmark
  proving the quality of the supplied reference has been matched.
- 17 editable text clips; graphics are region clips, audio is an original
  deterministic temporary score. No paid image/video generation.
- Composition was authored by Codex, not generated from an unassisted microphone
  interview. Do not claim the end-to-end ideal production experience is complete.

## Verification

- Python targeted suite: 27 passed. Rust release tests: 21 passed.
- Frontend typecheck and isolated production build passed.
- Real Chrome/native bbox comparison at t=0,1,2,1: within 1 pixel in this fixture.
  Backwards seek reproduced identical geometry. Not a claim of pixel-identical
  font rasterization across browser and GPU.
- Real Astra production worker changed only the final brand clip's motion from
  0.55 seconds to 1.00 second. Other 25 clips, text/style, audio and duration
  unchanged. Worker time 145.2 seconds, so conversation/worker latency is not solved.
- That worker initially inspected with the old deployed executable and correctly
  reported a visual-verification limitation. Rebuilt/deployed headless binary and
  frontend production were subsequently tested; final export uses the new binary.
- Initial final-sample export including missing caption cache: 8.48 seconds.
  Revised export with cache: 3.31 seconds. Neither includes creative authoring time.
- Initial multimodal quality review identified overly brief copy and an abrupt
  hand-off. Removed the short copy and expanded the center cover into the final
  background. Final observation is in exports/yohaku-motion-8s-review.txt.
- The subsequent review found the enlarged opening words crossing the small
  eyebrow. The eyebrow now ends before the crossing (1.5s). Checked the 1.8s
  composited frame and re-exported; final cached export took 2.70 seconds.
- Native WebView selection measurement was updated for the motion wrapper and
  multiple simultaneous captions; it measures each text box rather than the canvas.

## Deployment

- Headless executable updated immediately after test workers completed.
- Frontend production built into .next-prod-1788852561 and activated on 3000.
- Native editor update is staged as native_ui_editor.exe.pending.exe; the existing
  window was not closed. Installer replaces the editor after it exits.
- Restarted idle 8000 service after checking there were no queued/running jobs.
- Existing user project timelines were not modified. The sample has its own room.
- exports/open-yohaku-editor.cmd opens that isolated editable sample with the new
  built executable, without requiring the existing editor window to be replaced.

## Remaining

This adds general motion primitives, not a complete After Effects replacement.
Rotation, rich typography effects and a full HTML/3D editable integration are not
implemented here. Reference 2/3 production routes and actual microphone acceptance
remain separate work. The current running old editor must be closed/reopened to
use the new native drawing behavior.
