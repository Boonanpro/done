# Reference library integration — 2026-09-17

## Implemented

- `docs/reference-library.json` describes 11 inspected public reference images. Cached JPEGs live in `uploads/reference-library/`; this directory must be provisioned on another installation. This is a small initial corpus, not a comprehensive video/style library.
- Jev scores the request with original conversation and recent presentations. Confident existing-reference requests go directly to presentation, without starting the full production agent. Ambiguous requests use subscription Astra CLI; normal production model settings remain unchanged.
- The editor loads curated images locally, decodes them and checks display readiness. Selection and display latency are recorded separately. No automatic Web-search/generation fallback was added. Explicit requests to search still use existing capabilities.
- Presentation tools cannot modify the timeline. Known public IDs only are served; arbitrary filesystem paths are rejected.

## Verification

`scripts/test_reference_library_display.py` uses real Jev, Astra CLI, API routes and the actual editor page with Playwright. It replays transcribed Japanese conversation in an isolated test room, without microphone or TTS. It asserts displayed images are ready and the timeline is unchanged.

Latest run:

| Request | Route | Submission to display/answer | Image decode/display |
|---|---|---:|---:|
| Compare two different reconstruction illustration moods | Astra CLI | 8.303 s | 47 ms |
| Prefer hand-drawn, worried/troubled scene | Jev | 1.366 s | 35 ms |
| Different drawing style rather than just another person | Astra CLI | 8.033 s | 33 ms |
| Live-action video unavailable in corpus; no search/generation | Astra CLI | 8.595 s to answer; no image displayed | — |

The alternative comic includes a nervous catcher and smiling batter. It offers a distinct drawing style, but is not a strong match for the earlier serious/non-smiling preference. Do not describe all four turns as a quality pass. Broader appropriate references and better handling of partial matches remain necessary.

58 focused unit/API tests passed; JavaScript syntax checks passed. Screenshot and measurements: `scratch/reference-library-display-20260917/`.

## Limits

- The 5-second target is met by the direct-selection example, not ambiguous cases. End-of-speech latency and natural audio conversation were **not tested**. Latest user voice log reports exhausted LIVE 1 API credit.
- The latency test invokes the same decision/presentation endpoints and actual renderer; it does not exercise an entire LIVE 1 delegation, reconnection or spoken reporting session.
- No claim of comprehensive style coverage, final production quality, or subjective preference accuracy follows from these results.
- No additional payment or Web searches/generation were performed by this integration test. Jev calls use the existing account; Astra uses CLI subscription.
