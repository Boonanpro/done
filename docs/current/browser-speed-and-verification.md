# Browser speed and verification

## Current validation: real agent wall time

The reproducible agent benchmark runs Claude Code with the production browser
tool/observation functions, on a local eight-field form with fresh browser
contexts. It permits the model to request multiple tools in one response; it
does not manufacture eight reasoning turns or inject artificial thinking delays.

Final paired runs (three per mode, model resolved to `claude-sonnet-5`):

| Metric | Individual fields | Verified batch |
|---|---:|---:|
| Median wall time, including CLI startup/model/tools/network | 13.13 s | 9.49 s |
| Independently verified completed runs | 3/3 | 3/3 |
| Tool calls including initial open | 9 | 2 |
| Assistant message IDs per run | 3 | 3 |
| Failed tools / repeated field requests | 0 / 0 | 0 / 0 |

This is about 28% less wall time in this small fixture, not a claim of a universal
speedup. It uses a test MCP adapter and does not exercise the production Dan
chat UI, persistent CLI startup, user memory or external-site business workflows.
Message counts are not a measurement of internal reasoning. The earlier claim
that seven inference rounds necessarily disappear would be incorrect.

Read-only public smoke tests opened the same Amazon Japan product detail and
Wikipedia page in each mode: both legacy force-click and guarded click reached
the expected destinations in all four samples. This does not establish an
Amazon-wide success rate or cover purchasing/authentication/carousels in situ.
Partial and full overlays are covered by isolated real Chromium tests.

Raw summarized evidence: [browser-speed-validation-20260911.json](browser-speed-validation-20260911.json).
Reproduce with `python scripts/benchmark_browser_agent.py --rounds 3` and
`python scripts/check_browser_public_sites.py`. The agent benchmark uses existing
Claude authentication; its CLI-reported dollar cost is not a statement of actual
subscription billing. Test transcripts and synthetic inputs stay under scratch.

## Objective and implementation scope

Improve the shared Claude/Codex browser tool without reducing result verification.
Work is confined to browser execution, tool dispatch/schema, diagnostics and tests.
Existing unrelated edits in tools.py must remain intact.

The expensive unit is an agent/tool/observation round trip, not just a mouse click.
The implementation adds verified form input in one call, explicit postconditions,
and local timings, then tests these against isolated real Chromium pages. It also
fixes result attribution and replay behavior before permitting faster workflows.

## Using the fast paths

Use `browser(action="fill_form", expected_url="<last observed exact URL>",
fields=[{"ref":"@e123", "value":"Alice"}, ...])` for 1–20 already observed,
independent, ordinary text fields. Empty values are allowed. It preflights all
fields, retains DOM identity, checks for navigation and cancellation, verifies
each input and rechecks all values. It returns one complete screenshot + DOM
observation. It never submits. Credentials, selects, dependent/autocomplete
fields and actions whose intermediate result needs interpretation use individual
tools. A partial failure is not automatically rolled back or replayed.

For a known same-tab result, use `expect` on `click` or `type`:

```json
{
  "action": "click",
  "ref": "@e123",
  "expect": {"selector": "#save-result", "text": "Saved", "timeout_ms": 10000}
}
```

Selectors must come from actual inspected DOM. The preflight rejects ambiguous,
malformed or already-satisfied expectations before acting. The result condition
must identify the effect of this action, not an unrelated visible element. A
timeout returns the screen and uncertainty; it never retries the action. Use
`action="wait_for"` with the same expectation to observe delayed results without
clicking again. DOM evidence still does not prove server-side persistence unless
the site supplies that evidence.

Clicks with explicit postconditions skip the legacy 500 ms popup delay. Unknown
destinations and popup clicks retain the existing fallback. Delayed login
redirects retain the existing conservative handling; DOM quiet is not proof that
authentication succeeded. Default ref clicks now use Playwright's actionability
checks instead of forcing through overlays. Before emitting a click, a bounded
trial checks actionability. If the center is blocked, hit-testing looks for an
unobstructed point on the same retained DOM node, then validates that point with
another trial. Only one real click is attempted. Full occlusion returns blocker
metadata, an updated screen and next-action guidance; it never blindly forces or
replays the click. Cancellation after trial is checked before dispatch.
Specialized coordinate tools remain
available for interfaces that cannot be operated by DOM refs.

## Correctness changes

- Replies belong to a specific queued request. A late reply cannot satisfy a
  different command. Cancelled queued requests are skipped.
- Browser-close recovery does not replay mutating commands; their effect may
  already have happened. Read-only observation recovery remains available.
- Element refs follow DOM node identity across observations rather than being
  reassigned according to list position. Replaced nodes receive new refs. The
  compact format has a random 48-bit document namespace and base-36 sequence
  (`@aB3dE5gH:1`). Navigation changes the namespace; same-document observations
  retain node identity. Legacy numeric refs remain parseable. For 200 elements,
  ref strings shrink from 3600 to 2365 characters (34%); tokenizer savings have
  not been measured and are not inferred from character counts.
- Batch diagnostics report refs/stage, not submitted field values.

## Measurement

Timings are appended to `~/.dan/logs/browser-timing.jsonl` (bounded file size).
Override with `DAN_BROWSER_TIMING_LOG`; disable with `DAN_BROWSER_METRICS=0`.
Only phase, operation, status, duration, timestamp, PID and numeric counters are recorded. No URL,
field value, credential, screenshot or task text is recorded.

Run `python scripts/browser_timing_report.py`. The common CLI entry point now
records `agent_request` wall time for browser-using request streams, including
model and server waits, tool count and error-event count. `returned` means a
result event arrived, not independently verified business completion. Tool,
observation, execution and roundtrip spans overlap and must not be added together.
Inference alone is not separately measured. No production request samples were
available at validation time; they accumulate during normal use after reload.

Run `python scripts/benchmark_browser_actions.py` for the reproducible isolated
benchmark. It alternates individual and batch paths, warms each once and records
five measured runs. Both paths verify all values and zero submissions; both
click paths verify the result. It performs real screenshot/DOM work, but excludes
LLM/network latency and is not an end-to-end production speedup claim.

## Verification and rollout

`python -m pytest tests/test_browser_fast_actions.py tests/test_browser_recovery.py -q`

34 targeted tests pass. Coverage includes values, disabled/missing/duplicate fields, credential exclusion,
DOM replacement, navigation, cancellation, later inputs altering earlier ones,
overlays, popups, stable refs, delayed postconditions, request ownership and no
mutation replay. Use a fresh MCP process to load code and the new tool schema.
Existing processes retain old imports/schema; restart the core only when all
rooms are idle. This is a local change; no commit/push is implied.

## Local verification on 2026-09-11

- 25 targeted tests passed; a fresh stdio MCP client verified tool discovery.
- Chromium 141, five measured runs: eight-field individual input + observations
  median 403.42 ms; verified batch + final observation 218.37 ms (1.85x).
- Immediate-result click + observation: fixed-delay median 582.44 ms; explicit
  precondition/postcondition path 80.81 ms (about 7.2x).
- These are local browser-only measurements, not total task completion times.
- Checked 68 room statuses: zero active. Restarted the local core to refresh
  idle CLI/MCP processes. Restored the sandbox after the known restart race;
  both health endpoints returned HTTP 200. No commit or push was performed.
