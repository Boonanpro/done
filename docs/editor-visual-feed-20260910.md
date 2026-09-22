# Visual presentation feed — 2026-09-10

Replaced the single current reference chooser with an append-only mixed-media feed. Supported renderers: image, video (including existing provider embeds), audio, text, local composition, HTTPS link, GLB/glTF model. The presentation schema does not prescribe which artifact to choose or the production sequence. Removed the draft-start UI action. Source links remain links; arbitrary web pages are not embedded.

Presentation history is retained in contents.json and fetched 12 entries at a time. read_presentations is available to conversation and production tools. Pointer/focus selects an artifact, including historical artifacts, and begin supplies its data. New items preserve existing player DOM and scroll position; users can return to the newest item and reopen a hidden feed. Local compositions stop scheduling frames offscreen. Permission errors use a single dismissible notification instead of accumulated chat rows.

Vendored @google/model-viewer 4.3.1 with license. A dedicated static endpoint and wasm-specific CSP permission support the viewer. Basic embedded-buffer glTF was verified; not every compressed or externally hosted model was tested.

Validation: 28 tests passed across presentation, reasoning, dialogue, activity and motion project modules. scripts/test_editor_visual_feed.py passed in Edge against isolated port 8037 and deployed port 8000. Checks include history pagination beyond 30 presentations, mixed artifacts, actual video readiness, 3D loaded state, preserving a player while appending, scroll preservation, historical focus in the authenticated begin API, error dismissal, hide/reopen, narrow viewport, and pausing offscreen compositions. Fixture media only; no paid generation. Screenshots: scratch/visual-feed-wide.png and scratch/visual-feed-narrow.png.

Backend was safely restarted through the core endpoint without force; health passed. Core was not restarted. Existing assistant windows need reopening to load new JS. This verifies presentation infrastructure; it does not establish creative recommendation quality or full voice production latency. X search integration was not added by this change.
