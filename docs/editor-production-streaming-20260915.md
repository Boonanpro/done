# Production execution and incremental editing repair

User objective: shorten the instruction/review/revision loop and show real work
on the editor timeline while production continues. No user project was regenerated.

## Changed execution path

Production uses a ChatGPT-authenticated Codex CLI app-server turn instead of a
closed-stdin exec process. Normal Dan system instructions and configured MCP
servers (including browser/service tools) are passed through. Native shell and
web tools remain available. No API-key fallback is introduced.

The production worker checks durable instructions every 200 ms independently of
which tool is running. It sends native turn/steer and records acceptance only
after the CLI response. Failed delivery leaves the instruction pending. Existing
timeline-boundary delivery remains available. Scope expansion is tracked
separately so acknowledging text cannot lose selected clip IDs.

This does not cancel already-running external side effects. Transport acceptance
is not proof that the model has finished interpreting or executing the change.

## Editing and publication

apply_edits now executes sub-operations against one in-memory draft transaction.
Success writes once and publishes the complete batch through existing validation,
scope and compare-and-swap checks. Failure leaves disk and the live timeline
unchanged. This avoids repeatedly parsing/serializing a large draft for every
caption. No incomplete sub-operation is shown as a committed edit.

Production emits timeline_checkpoint with the actual sequence hash and clip count
when a completed timeline tool changed the live sequence. The shared execution
contract explains working incrementally using available audio/scenes instead of
waiting for all materials and final review before initial placement.

Terminal jobs now update the matching persisted editor_work status. Unrelated
jobs and timeline contents are preserved.

## Caption work

auto_captions accepts existing word timings in timeline coordinates. Supplied
timings bypass audio rendering/transcription. Japanese chunks use BudouX phrases
instead of slicing words at character limits. Coverage is checked before replacing
existing captions. BudouX 0.9.1 installed, dependency recorded in requirements.
This is not a claim that automatic linguistic boundaries are always editorially
ideal; visual and timing review is still needed.

## Verification

- Real CLI steering during a shell wait: updated requested answer returned.
- Real CLI + timeline MCP, isolated room production-stream-test-c2689c42:
  first clip visible 19.891 s; steering accepted in 7 ms; previous clip unchanged;
  two clips verified, completion 57.172 s including an intentional five-second wait.
- Normal production prompt path, isolated room production-stream-test-3e5cd30b:
  first checkpoint 24.672 s; steering accepted in 20 ms; second checkpoint
  41.375 s; final response 66.063 s. The first clip remained byte-for-byte equal
  as a dictionary. The model additionally checked frames and validation.
- Draft IO benchmark: 100 edits in a 470-clip draft, old read/save loop 1.657 s,
  transaction 0.0192 s. These are IO timings, not whole-model or video speedups.
- Regression coverage includes rollback, partial scope preservation, checkpoint
  publication, terminal state, supplied caption timings, and full caption text.

The live server was reloaded after verifying no active production jobs and that
the latest voice log was inactive. Sandbox PID 22600 reported healthy.

## Remaining limits

No repeat of the full 17-minute production was performed, so total end-to-end
speedup is unmeasured. Native steering eliminates the timeline-tool-only delivery
gate, not model thinking or external generation latency. The new session stores
its thread ID in its job directory; cross-job work reads persisted project state
and supplied conversation, and does not reuse the ordinary chat session.

Aspect-ratio reframing, avatar design, and quality of the real project's visual
direction are not changed by this execution repair.
