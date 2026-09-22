# Reference discovery, direction changes — 2026-09-18

## What changed

- Jev reads the original conversation to estimate current preferences, exclusions and a useful unresolved comparison. Each call recomputes this state; no accumulated score makes an old direction impossible to leave. Partial changes preserve unaffected intentions. Hypothetical questions are not decisions.
- A comparison is useful only if the available evidence supports different sides of an unresolved property. Changing video IDs alone is not recorded as progress. Reused reference IDs are sent to Live explicitly.
- The comparison axes are retrieval aids, not a whitelist of production capabilities or a mandatory questionnaire. The original user words remain authoritative.
- A failed URL lookup no longer silently launches Astra. A correction that Live splits into a new transcript ID also cannot turn a stale reference decision into an Astra request.
- Reference counts and descriptions are sent when cards appear, even while Dan is speaking. Only the invitation to speak waits for a suitable pause. Previously, one path delayed the facts until after speech, leaving Live without the visible result.
- If no supported reference is found, the lookup reports that outcome instead of leaving "searching" as the last spoken message.

## Reference evidence

The existing 1,178 URLs remain searchable. Most have title/publisher/description metadata, not inspected visual attributes. `docs/reference-index/visual-observations.json` adds model video observations for three actual candidates (Claude Cowork, Infinity product demo, Blender SINGULARITY). Video files are not stored there. Analysis runs outside the interactive loop; later searches reuse its results.

The observations are model observations, not human-verified production methods. Search and presentation distinguish them from publisher metadata. With the observations, the actual retrieval test found a supported contrast between a UI-only demonstration and a demonstration that includes a live-action person. Before the observations, the same comparison had insufficient visual evidence.

## Verification and limits

`scripts/verify_discovery_pivots.py` calls real Jev with user-like Japanese: partial refinement, a complete style pivot, a hypothetical, returning to an earlier direction, and changing the purpose to a wedding video. Expected answers are not included in requests. All five passed in the final semantic run.

Real Live WebRTC tests and mixed audio/screen recordings are under `scratch/discovery-pivots-*`. The initial runs deliberately remain as failure evidence. They exposed both the stale transcript fallback and delayed visual facts. Do not cite those recordings as fully successful narrowing.

Automated regression checks cover supported versus invented visual differences, settled versus unresolved properties, retrieval failure, presentation facts arriving during speech, transcript-ID changes and presentation validation. See the final delivery evaluation for end-to-end timing.

This does not prove arbitrary creative direction can now be narrowed to satisfaction. Sparse visual evidence remains a limitation, and a correct style change does not establish that the proposed videos are the user's desired quality. Jev scores are model estimates, not calibrated probabilities of the user's taste.

## Final recorded run and deployment

`scratch/discovery-pivots-delivery/conversation.mp4` is the final 189.84-second recording (video and mixed audio). Four spoken inputs, real Live and Jev, no Astra dispatches. Initial two cards appeared 5,030 ms after synthetic input audio ended; the 3D pivot card appeared after 2,956 ms. Retrieval/selection took 2,167 / 2,209 ms respectively. These are two measured presentations, not a latency percentile or a playback-start measurement.

The first comparison correctly described the two inspected videos and their count/order. The ordinary-room live-action request had no supported new candidate; Dan said so and proposed a more concrete scene question. The next input changed to space/3D, retained the Dan introduction purpose, and displayed one SINGULARITY reference. Asking whether live action could be restored did not trigger that change or production. Browser errors: zero. It still sometimes follows a description with a redundant "on screen now" line, and the quality/coverage of further narrowing is not established.

Regression tests: 50 Python tests and 45 JavaScript tests passed. Production sandbox restarted through the guarded Core endpoint, PID 14220, healthy. Its served live script matched the saved file; authenticated production `/visual-decision` returned `talk`, change `none`, preferred medium `live` for the hypothetical test. An editor reopen loads the new client script.
