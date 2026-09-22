# URL reference pilot — 2026-09-18

URL index connected to the live editor's whole-work comparisons on 2026-09-18. Detailed segment retrieval remains an experiment.

## Saved data

- 1,178 unique YouTube video URLs from 60 queries across 20 discovery groups.
- All candidates retained, including 71 tutorials and 43 production breakdowns.
- Labels are provisional classifications of title, publisher and description, not visual quality certification. Discovery groups are provenance, not labels.
- One 162.9-second official GPT-6 launch video analyzed with Gemini agentic video processing, divided into 29 intervals. Independent audit found four corrections, incorporated into the normalized record. Sampled stills reviewed; entire soundtrack was not manually audited.
- Suggested reproduction techniques are inference, not proof of the original production pipeline.

## Measured retrieval

The initial single question containing 1,178 choices failed: the Jev API returned HTTP 400, `Too many choices. Must have at most 255 choices.`

Revised search covers all records in six concurrent groups of at most 200, keeps up to five candidates from each group, then compares finalists in a second request. No genre is excluded in advance. Any failed group makes the overall request unavailable rather than silently reporting full coverage.

Six full-work queries: 1,193–1,616 ms. Four detailed segment queries: 232–291 ms. These are backend retrieval times, excluding voice recognition, playback, thumbnails and editor display.

Automatic coarse-label/interval checks passed 10/10, but this is NOT ten quality-approved recommendations. The tutorial query requested After Effects teaching and received `How to explain something complicated`; its broad genre matches but subject specificity is insufficient. Automatic labels are not an independent quality oracle. Ranking probabilities are relative choices, not calibrated quality scores. Second-stage selection can also lose candidates in first-stage pruning.

## Review

Run `python scripts/build_reference_pilot_review.py`.

Explorer path: `D:\done\scratch\reference-url-pilot\review.html`

Headless Edge verified 36 cards per page, 71 tutorial results, 29 interval links, view switching and no JS errors. Visible thumbnails loaded successfully. Links open original YouTube videos; full embed/playback availability of all 1,178 records has not been checked.

## Remaining

- Voice end-to-end timing remains unverified. Production browser transcript-injection tests displayed launch, vlog and tutorial candidates in 1.6–2.5 seconds without Astra delegation. This measures presentation insertion, not YouTube player readiness; visible players require additional network loading.
- GPT-4 launch reference `--khbXchTeE` was observed refusing embedded playback. It remains in the index but is excluded from embedded comparisons. Other URLs may also refuse playback; unchecked does not mean playable.
- Improve metadata coverage and specificity; fine visual taste is unknown for 1,177 videos.
- Expand beyond YouTube; present collection is deliberately diverse but not comprehensive.
- Check actual selected references, availability and comparison usefulness, not just genre agreement.
- Existing live trial failure where a timeline request was classified as talk is separate and unresolved by this index.
