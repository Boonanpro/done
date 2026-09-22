# Jev failure recovery — 2026-09-21

Changed the browser delegation path in editor-live.js: an unavailable classifier or failed HTTP request completes the handoff with a factual failure report and clears busy state. It no longer silently starts Astra. The existing service already retries transient HTTP failures once within its timeout; no extra browser retry loop was added. Explicit production decisions still enter the existing CLI path.

Verification: 46 Node behavior tests pass, including HTTP 503, network failure, and existing execution/navigation tests. The shared test fixture now explicitly supplies a successful execution decision for execution tests instead of accidentally relying on an absent API mock throwing.

Production-served JavaScript was tested through real WebRTC with synthetic user speech. No server restart was needed (the script route reads the file with no-store). Room: visual-voice-08ee91fa. Actual Jev HTTP 503 reproduced. Two decisions took 1193 and 1012 ms. The failure handoff completed 1998 ms after the recorded user audio ended; Astra dispatches: zero. LIVE audibly explained references could not be retrieved and continued with a question. Final busy=false, toast empty, browser errors empty. Screenshot inspected. This verifies failure handling, not successful reference selection.

Recording: D:\done\scratch\jev-failure-recovery\conversation.mp4
Evidence: scratch/jev-failure-recovery/final.json and evaluation.json.

Normal-path latency analysis of the prior overall-discovery-voice-final recording: first decision started +816 ms and returned talk at +1220 ms. LIVE then spoke before delegating at +7061 ms. Second decision took 2671 ms and cards appeared +10143 ms. Thus the major extra wait was a missed proactive comparison and subsequent delegation, not rendering. Correcting this decision behavior remains outstanding; successful provider-backed verification was unavailable during this run because Jev returned 503.
