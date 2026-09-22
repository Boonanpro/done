# Production library: evidence and quality

## Separate records

- Work reference: original URL and provider metadata; observed facets require video evidence.
- Scene/technique: parent reference + valid time range + observable appearance/movement/audio.
- Editable component: source files, runtime/dependencies, license, preview and adaptation tests.
- Production asset: model/material/lighting environment with provider metadata and compatible renderer.
- Implementation proposal: a possible way to recreate an effect, never evidence of the original workflow.

## Quality is not playback

`inspection` in the older 71-component catalog records decoding and playback.
It is NOT aesthetic approval. These components remain unapproved until reviewed.
Neither download counts, price, provider reputation nor a model's praise grants approval.

New items start `unreviewed`. A video model may produce `candidate`, `reject`, or
`uncertain`; all are `model_review_only`, not production-approved components.

To approve an editable component, record:

1. Exact source revision/hash and a concrete reference-quality benchmark.
2. Inspection of the running preview: composition, typography, motion timing,
   transitions, image quality, and audio where applicable. Sparse screenshots
   do not establish smooth motion.
3. Actual adaptation: Japanese/Latin text, a long and a short string for text
   components; substituted assets and supported aspect ratios where relevant.
4. Known runtime, external dependencies, source license and media dependencies.
5. Specific strengths, limitations and intended uses; no claim of universal quality.

Reject placeholders, broken dependencies, unreadable text, obvious clipping,
uncontrolled motion, and substitutions that degrade the benchmark. Simplicity
alone is not a defect. Reference footage is not an editable source component.

## Offline collection and runtime

Analyze once outside the conversation. Preserve raw output, model/mode, usage,
source and timestamps. Validate evidence links and scene ranges before merging.
Cache successful analyses; do not retry unsuccessful paid calls indefinitely.
Whole-work and scene search consume observed facets. Reproduction guesses are
excluded from observed-feature search text. Renderer assets stay out of the
whole-film reference list.

## Current expansion commands

`python scripts/enrich_production_library.py --limit 66 --run --publish`

Each explicit run chooses unprocessed records across genres and favors publisher
diversity. Maximum four concurrent cloud analysis requests. No local GPU.

`python scripts/import_production_assets.py --samples 2`

Imports Poly Haven publisher metadata and six representative previews/file
manifests. Does not purchase assets, install plugins, or claim Dan 3D compatibility.
