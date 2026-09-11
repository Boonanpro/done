# Editor workflow and skill audit, 2026-09-10

The ordinary edit job template explicitly recommended production/studio/post-production and requested a rendered video even for `dan_revise`. These instructions were broader than the user's timeline placement request. The runtime, editor help, and skills also disagreed about when edits appeared and what constituted delivery.

Changed the job template to make timeline editing the deliverable for `dan_revise`, preserving explicit export jobs. Runtime and saving help now share one execution contract. Specialist skills remain available on demand. Verification follows the affected behavior; full new works still require whole-work review.

Revised local `studio`, `video-draft`, `creative-studio`, `video-direction`, and `post-production` guidance. Removed universal one-image-per-cut/full-subtitle recipes, mandatory direction restarts, fixed caption/PiP/filler rules, intermediate subtitle baking and silent full-frame blur fallback. Missed tracking remains unresolved until corrected and checked; no privacy claim follows from simply removing a fallback. This audit does not prove the earlier Hino failure was caused by this skill.

Actual testing exposed a missing capability interface: the native audio decoder's existing diagnostic was only available through a command line. Added `probe_audio` and returned stream metadata from `import_media`. The probe samples at most 0.5 seconds at the start of each overlapping audio clip; it is not a quality, synchronization, full-range or perceptual verdict. Actual native invocation completed in about 0.094 seconds.

## Same end-to-end test, three observed runs

Existing five-second B video, linked original audio, additional last-second caption, spoken question during production, spoken completion. Disposable rooms; no user work replaced.

| Version | Room suffix | Total seconds | Tool calls | Bash calls | Full exports |
| --- | --- | ---: | ---: | ---: | ---: |
| Before audit | ccb34558 | 149.80 | 18 | 5 | 1 |
| Instruction/skill revision | e1465b1e | 191.55 | 25 | 10 | 0 |
| Plus direct audio probe and stream metadata | f3fa524e | 139.78 | 14 | 1 | 0 |

The intermediate run got slower while searching for playback verification. The final run used probe_audio, composited frames, and a video-content check instead of researching commands or exporting. It still read the installed HyperFrames entry point and retried one batch after choosing an audio lane for the caption. Do not describe this as solved latency or a statistically established 7% improvement: one run per configuration, total time includes voice playback and test waits, and model behavior varies.

All three conversation/production harnesses completed. Latest regression suite: 29 passed; five edited skill frontmatters parse. Direct native audio probe exercised successfully. No claims about a newly produced full video's creative quality follow from this placement test.

Further latency work should measure model turns versus tool durations and improve operation schemas for automatic linked-audio lane placement. The editor's own live preview/selection/Undo acceptance still matters separately from browser-harness delivery. Tests with a real native window can establish actual playback without searching an unrelated browser window.
