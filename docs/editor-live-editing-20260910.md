# Incremental editor delivery — 2026-09-10

## Shipped behavior

- Timeline MCP operations publish validated checkpoints immediately. A batch is one atomic operation; a failed batch does not leak its first edits.
- The native editor accepts manual edits while production runs, preserves playback position, selection and timeline zoom/scroll when refreshing, and briefly highlights added/modified clips. The maximum insertion stagger is 160 ms.
- Native saves use the same contents lock as backend writers. At the next tool boundary the agent adopts a human save before continuing. Concurrent unpublished changes return a conflict instead of overwriting.
- Published generated assets survive draft discard because the live timeline or Undo may reference them.
- Completion notifications no longer disappear behind an old question. They receive recent raw conversation; markdown is removed from speech. New instructions release an obsolete question with the actual instruction, without inventing purchase authorization.
- Project status accepts a null pointer from the native editor. First available clips reveal the editing view before production finishes.
- The default 120-tool ceiling is removed. An explicitly configured ceiling does not block validation/reporting.
- Split accepts several cut times atomically; caption text/style can use the generic property operation; color-grade fields are explicit in its tool schema.
- Speech timestamp analysis defaults to the cloud word-timestamp API with a file-content cache. No Qwen or local GPU model is started by this path.

## Evidence

- Python: 44 tests passed across live checkpoints, reasoning, production lifecycle, scope, and workflows.
- Native Rust: 21 tests passed. Release build/deployment succeeded, tag `59aaf67+ 09/10 10:26`.
- Actual GPT6 + microphone/ASR + speech-output browser test: `reasoning-production-ccb34558`, content `367dfa26-a729-40ab-a3c2-12061bd94883`, job `e5f722f3-5233-4045-af87-8a9098d1f4e8`. Imported an existing five-second video with linked audio, received an additional caption instruction, answered a spoken question without stopping work, and delivered a spoken completion. Full harness elapsed 149.8 seconds, including voice exchanges and validation. This is not a claim of satisfactory editing latency.
- The live contents already contained the edits with job status `running`. Native window test `native-live-20260910` subsequently changed the caption through the real MCP/checkpoint path. A window capture shows `LIVE EDIT` in the preview; published native state retains playhead 4.5 seconds. No final draft commit was needed.
- Short speech fixture: first API call 3.62 seconds, cache lookup 0.032 seconds. This does not compare equal-length material with the prior ten-minute measurement.
- Installed supplementary skills: `product-design`, `ui-animation`. These complement the existing Apple guidance; installation alone does not establish visual quality. They are available to subsequent turns.

## Limits and remaining acceptance

- This verifies incremental delivery, not the creative quality of a fresh full video. The previous inquiry draft's editorial/visual shortcomings have not been declared fixed.
- The real native screenshot verifies update and playhead retention. End-to-end pointer-operated Undo and sustained playback during repeated checkpoints have not yet been established by this run; file-level manual-edit preservation and rollback are covered by automated tests.
- The five-second production test still took too long overall. It exported and checked decoding in addition to placing media; worker startup, conversation and validation latency need separate measurement before claiming an improvement.
- Arbitrary shell operations outside the editor transaction tools do not automatically inherit checkpoint semantics.

## Deployment

Native release copied to the regular editor and headless paths. Editor backend port 8000 restarted with this checkout; core port 9000 was not restarted. Disposable native/API test processes are stopped after verification. The user's production content was not replaced by these tests.
