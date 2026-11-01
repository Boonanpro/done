# Google Docs comment events

Owner-authorized document comments run silently in a fork of the registered
room's conversation. New owner comments/replies trigger answers in the same
Google thread; editing instructions require the browser's suggesting mode.
Google Docs API cannot create suggestions. Other authors' text is context,
not an authorized task. Replies begin with `ダン：` and do not trigger jobs.

`files.watch` posts to `https://dan.paina.info/api/v1/gdoc-events/push`.
Receiver verifies the hashed channel token, resource, and expiration, commits
a dirty sequence, then acknowledges. The persistent worker is woken by OS file
events. It fetches comments only for dirty documents (paginated, timestamp
overlap), deduplicates content revisions and queues a durable batch. Text-only
edits and duplicate callbacks do not wake an AI. Channel registration is renewed
one hour before expiry; this timer never reads comments. Google push is best
effort: a lost Google notification cannot be discovered without a later event.

The worker uses `~/.dan/gdoc-events/jobs`, separate from visible jobs. Existing
parallel runners supply the room's conversation, with quiet delivery. A single
document's batches are processed sequentially. Results and full thread snapshots
remain in `state.sqlite`; the shared room system prompt loads recent history for
both Claude and Codex. No chat message, unread mark, push, work card or progress
event is created. Older messages are available using the history helper.

Setup after shipping and activating the route:

```
python scripts/install_gdoc_events.py
python scripts/gdoc_comments.py register --file FILE --room ROOM --account shub6923
python scripts/gdoc_comments.py browser --file FILE --room EXISTING_AUTHENTICATED_BROWSER_ROOM
python scripts/gdoc_comments.py status
```

OAuth credentials use the encrypted `~/.dan/gdrive_<account>_token.enc` created
by the authorized login. Client identity uses existing app settings. No secrets
in command arguments, logs, or SQLite. Only token hashes are stored for channels.

Assign an already authenticated Dan browser for suggestion edits; its profile is
reserved from the ordinary idle-job pool. Batches sharing a browser run serially.
Questions answerable from the room/thread use the reply helper without browser
login. Do not repeat Google login attempts when Google has refused them. Observed
push delivery can be delayed by tens of seconds; this is event-driven, not a
guarantee of instantaneous Google delivery.

Administration: `pause --file FILE` stops new work and renewals; `resume --file
FILE` retries pending work. A failed operation gets at most three bounded attempts
and then pauses with a recorded error. Already-started jobs are never replayed
after a crash. Reply intent is stored before the POST: an uncertain outcome is
reconciled against thread history, never blindly resent. Use `reply --batch ID
--comment ID --text-file PATH` for an authorized answer; it refuses stale,
deleted, resolved or unrelated comments. Inspect a failed batch before resuming.

`history --room ROOM` gives recent context. Full snapshots and results remain
in SQLite for longer history. `install_gdoc_events.py` refuses to interrupt an
existing worker. To update that process, wait for its private jobs to finish,
then restart only `com.dan.gdoc-events`; Core/browser/chat continue running.

References: https://developers.google.com/workspace/drive/api/guides/push
and https://developers.google.com/workspace/drive/api/reference/rest/v3/comments/list

## Opt-in script learning

`python scripts/script_learning.py enable --file FILE` captures an initial baseline
and enables collection on the existing registered document. Source documents are
never mutated by the collector. The event worker also reconciles enabled targets
every five minutes, even with no comments. Collection failures pause after three
bounded attempts; `status` exposes errors and `resume --file` is explicit recovery.
This is NOT a complete keystroke history or proof of edit authorship.

Current transport is Drive DOCX export, preserving tracked insertions/deletions,
author labels and comments, plus full Drive comment threads. The installed Google
project has Docs API disabled; we do not silently change its configuration. Each
export is bracketed with Drive version reads; concurrent-version exports retry
later instead of mixing evidence. Raw ZIPs and structured evidence are kept under
`~/.dan/gdoc-events/`, with an independent `learning.sqlite`. Identical editorial
content is deduplicated. Direct edits have unknown per-span authorship; the last
modifier does not identify every edit. Export IDs are not stable across snapshots.

`before` / `after --file FILE` brackets Dan's own edits. Failures leave the interval
open, so concurrent or abandoned edits are not silently attributed to the owner.
The existing comment-job prompt and talk-script skill use these boundaries.

After edits settle for 60 seconds (maximum batching window ten minutes), one quiet
learning job across all documents reads the evidence and the skill-creator /
talk-script learning instructions. Collection continues while the AI is busy.
The worker requires a structured `complete` report; a runner's fluent final answer
alone yields `needs_attention`. Crashed runs are reconciled, never replayed blindly.
A needs-attention job blocks new skill writers, but not collection or comments.
A deferred report preserves the candidate and the missing decision in room context.

Promotion requires all assigned changes accounted for, evidence-linked lessons,
real old/new output artifacts including a held-out example, and the committed skill
files delivered to the live folder. Artifact checks establish provenance, not an
objective guarantee of writing quality. The agent supplies the substantive review;
ambiguous cases remain deferred. See `.claude/skills/talk-script/learning.md`.

The worker can be restarted independently when no private runner is alive. No Core
restart is needed for collection/learning. Existing processes' cached room-context
code receives the new summary on their next ordinary generation/reload.
