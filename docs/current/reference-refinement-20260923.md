# Reference refinement, 2026-09-23

The live reference tool now accepts optional `refinement` with `keep`, `change`,
and `next_axis`. The HTTP endpoint passes it as discovery context to genre
routing, Jev ranking, and independent content-fit checks. These are descriptions
of the user's remaining differences, not a confidence score or required form.

The live client suppresses already-visible library IDs / YouTube URLs from new
search results. An all-duplicate result tells the conversational model that no
new example was shown; explicit replay still uses `control_reference`.

Existing observation enrichment reads actual videos and records time ranges,
visual/motion/audio observations, evidence-linked facets, techniques, unknowns,
and a model quality review. A model review is not human approval.

Baseline: 6,753 reference URLs, 103 observed works, 65 with richer facets.
A bounded 12-work, cross-genre enrichment batch was started using the existing
resumable script. See `scratch/production-library-enrichment/report.json` for
the final accepted counts and failures.

Verification: 54 Node context tests and 13 Python consultation/observation/
enrichment tests passed. A real Jev refinement query about documentary immersion
plus scientific explanation returned no supported candidates in 8,035 ms.
This is not evidence that retrieval quality is solved. Full result is stored at
`scratch/reference-refinement-check.json`.

The active V-conte production job was left running. Backend code changes need
a safe sandbox reload after active production finishes; observation snapshots
are refreshed by file mtime without a server restart. No voice test was run.
