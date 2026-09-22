# Jev editor integration — 2026-09-16

## Saved implementation

- `editor_jev.py`: paid TypeSafe `jev-latest` structured decision API. Reads the authenticated user's `typesafe_jev` API credential (`password` field) from the encrypted credential service. No client-side key or source-file secret. Thirty-second per-user key cache; maximum 2.2-second decision wait, then existing Astra flow.
- `POST /editor-assistant/presentation-action`: authenticated decision-only endpoint; cannot mutate timelines. Reads original dialogue and the currently loaded visual feed. One batched request decides a simple view action and its target. Only reveal/play/pause with both confidence values >= .9 qualify. This threshold is provisional, not calibrated evidence of accuracy.
- Live delegation attempts that path before starting Codex, unless a Codex turn is already running (existing steering preserved). Changed speech/project/session invalidates late UI decisions. Unsupported players fall back. Complex/mixed requests and uncertainty retain the original conversation for Astra.
- Proposal players expose real play/pause controls for direct media and local animated compositions. YouTube/Vimeo iframe playback is not in this fast path. No comparison-layout action implemented yet.
- Both reference searches optionally return advisory Jev rankings. They preserve every candidate and source; ranking does not claim to have watched footage or replace Astra's final choice.
- Decision duration, model, token usage and actual UI application are logged separately.

## Verification and current limit

14 JavaScript context tests, 26 Python Jev/Live/reasoning/Codex tests, and 18 route tests passed before final documentation. Actual headless Edge composition playback advances and pause holds position; screenshot inspected, recording saved under `scratch/jev-ui-check`. This browser test does NOT test Jev's decisions or spoken interaction.

TypeSafe account opened in Core-owned held browser room `jev-editor-setup`. No saved TypeSafe credential found. Google login requires completion. No purchase or real Jev call performed yet; no claimed improvement in Japanese judgment accuracy or production latency. Sandbox has not been restarted for the new Python endpoint. Existing JS files are served dynamically, so new page loads may receive the client path and safely fall back if the endpoint is not yet available.

After login: inspect account access/billing, purchase needed access within user's authorization, create API key directly into credential service, run `python scratch/benchmark_jev_editor.py`, investigate misclassifications before enabling real use, check active sessions before sandbox restart, verify deployed endpoint and real recorded voice/UI test with natural synthetic user speech. Preserve Gemini work and active sessions.
