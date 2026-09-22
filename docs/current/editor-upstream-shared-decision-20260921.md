# Upstream voice reference loop

Changes: editor-live.js now anchors reference decisions at the latest user message. Assistant acknowledgement tokens no longer create a different request/cache key. Earlier assistant context remains available for interpreting subsequent user answers. Reference facts arriving during Dan's speech update its context silently instead of triggering a second report after it finishes.

Verification: 47 Node behavior tests and 24 Python discovery/retrieval tests passed. Actual production-served JavaScript tested with WebRTC and natural synthetic user audio; no server restart. Screenshots inspected. These are synthetic tests, not user approval of reference quality.

Three-turn run: scratch/upstream-shared-decision/conversation.mp4. Initial film references appeared 3677 ms after audio end; refinement appeared 3950 ms after audio end. The ordinary-home constraint persisted after a Top Gun comparison. The assistant asked about duration/materials and did not initiate production when asked to keep discussing. Zero Astra dispatches; no browser errors. This run exposed a duplicate spoken presentation report, subsequently corrected.

Final report-fix run: scratch/upstream-report-once/conversation.mp4. Two visible film references; one spoken comparison question, no delayed duplicate report. Busy=false and no residual toast; browser errors empty. Card insertion took 6759 ms. Therefore the 5-second target is not consistently achieved.

Remaining delay: at +543 ms a search began on a transcript ending in an unfinished word; the final syllables invalidated it. That request finished +3736 ms, then the complete-text request started +4145 ms and finished +6467 ms. The current single speculative request waits for stale work to finish before handling the newest utterance. A bounded supersession mechanism can shorten this without reusing a result that ignores a correction. Do not treat all trailing words as insignificant or claim these two films fully resolve the user's desired direction.

All test calls ended normally. The changes are served on editor reload; an already open page retains its previous script.
