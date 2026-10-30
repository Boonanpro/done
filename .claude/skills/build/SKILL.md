---
name: build
description: "Create or modify editable websites and web apps delivered through Dan artifacts."
display_name: ビルド
updated: 2026-09-08
---

# Editable websites in Dan

Create the requested website or app with working behavior and editable content. Preserve the user's chosen design, materials and existing edits.

Read [integration.md](references/integration.md) when creating a slug or changing editing, routing, authentication or publication wiring. For an ordinary copy or layout change, inspect the affected code and release overrides; do not repeat setup.

- One site uses one `artifacts/<slug>` with nested page routes. Preserve its existing source of truth.
- Keep stable edit IDs and native editable text/media. Existing release overrides can supersede JSX; inspect them before changing published content.
- Use `ArtifactLink` for internal navigation. Preserve artifact identity and preview authentication behavior.
- Use the current registration/publish service. A successful file edit or registration does not prove publication.
- A site's own server code stays in the site: Next routes in `artifacts/<slug>/<route>/route.ts`, Python API in `artifacts/<slug>/_server/routes.py` (a `router`, mounted by `app/services/artifact_backends.py`). Never in `app/` or `frontend/src/app/api/`; the commit hook and the hourly archive sweep (`scripts/artifact_boundary.py`) catch it.
- Every site has a place map `artifacts/<slug>/MAP.md` (format in `docs/places/README.md`): what the owner sees, how they reach each part, how a tool drives it and what proves it works, and the traps. Create it with the site: `python scripts/place_map.py draft <slug> "<name>"`, fill every 「（ここを書く）」 from the owner's point of view (including `ready`, a selector of the real screen), then `python scripts/place_map.py stamp <slug>`. Dan reads the map's `speak` lines when talking in that site's room.
- When a change touches a site's screens (anything but `_server/`, `MAP.md`, `PRODUCT.md`), work in this order in the same tree (running folder or worktree): `python scripts/place_shot.py artifact:<slug> --tag before` before the first edit; edit; update the map's sections for what changed and `python scripts/place_map.py stamp <slug>` (it refuses when the screen changed but no description did; for a pure visual fix add `--unchanged "<reason>"`); then `python scripts/place_shot.py artifact:<slug> --tag after` (pass `--base` for a worktree's screen server). The after shot must be OK on all three checks (reached the page, real screen without error or blank, samples visible); fix and shoot again when it is NG. The Stop hook `scripts/hook_artifact_verify_gate.py` blocks a turn that skipped any of this.

Japanese copy (introductions, catchphrases, articles) follows [copywriting.md](references/copywriting.md): the owner judged Dan's copy too AI-like and preferred its rewrites.

Choose the implementation order and design appropriate to the task. [design-options.md](references/design-options.md) lists optional components and approaches. Read a recipe only for the selected approach. HTML proposals use `actions/proposal_html.md` only when requested.

When creating or revising dashboards, management screens and apps, communicate state, type and action first through grouping, alignment, placement, color, shape and motion. Put actions beside their targets; add a short label or explanation only when the visual arrangement leaves the meaning unclear. For example, keep the headings of income and expense columns, but omit a repeated “expense amount” caption beside every amount in the expense column. Do not rely on color or motion alone, or remove necessary action names, field labels, error/recovery information, decision-critical facts or accessible names. Before finishing, use the text check in [criteria.md](criteria.md) to remove redundant labels, explanations and legends from the affected screens.

Verify affected behavior and appearance. A new responsive site needs relevant viewport, interaction, editing and delivery checks; a narrow fix needs checks for that fix and plausible regressions. Inspect screenshots yourself, but attach extra screenshots only when requested. Report the actual artifact URL and observed state.

Dan's browser (the test account) is not the owner's screen. After changing an artifact, run `python scripts/artifact_seen.py --slug <slug> --wait 90` before reporting it done. It shows three things and ends with `[artifact_seen] slug=<slug> result=OK|NG|UNCHECKED`:
- the owner's open screens of that artifact and whether each runs the current files. Open screens catch up by themselves; one where the owner is typing keeps its draft and shows a reload button, and the output says so;
- the artifact's server code (`_server`, run by the live sandbox on 8000). It is swapped in a few seconds without restarting Dan. A `routes.py` that starts a background thread needs `dan_unload()` to stop it; without one the output says a restart is needed;
- the published copy, which the phone app opens. It is rebuilt about a minute after the folder stops changing and takes a few minutes.

Base the report on that output. OK: the owner's screen and server run the change. NG: do not call it fixed; pass on the reason from the NG line. UNCHECKED: the owner has no screen open; say it was not checked on the owner's screen. Only the owner's path (`/preview/<slug>` on 3000, server on 8000) counts as proof; a test server such as 8001 or a worktree is an intermediate test. A turn that changed an artifact cannot end before this check runs (`scripts/hook_artifact_verify_gate.py`).

## Voice is part of every artifact

The common artifacts layout installs `VoiceControlsRuntime`. In a call (`call=1`) it exposes the real screen's controls to the call, highlights and scrolls to a target, performs the operation and returns the resulting screen. Do not create a second voice UI or a per-site copy of this bridge.

- Use native buttons, links, inputs and selects with accessible names; use `role` and keyboard behavior for necessary custom controls. Canvas-only controls need a corresponding accessible DOM control. An unlabeled click handler is not a voice interface.
- Give important controls stable `data-voice-action` names. Mark navigation controls `data-voice-risk="navigate"`, local edits `edit`, and outbound, payment or destructive actions `external`, `payment` or `destructive`. Never mark a submit/send/delete as navigation to suppress confirmation. Unclassified buttons require spoken confirmation.
- Expose list search as a labeled input and results as named controls; the common `read_screen(query)` can find rendered controls. Virtual or server-paginated lists need real search that retrieves matching items, not an invented global registry. Long writing/revision still goes to the site's existing editing assistant.
- Verify voice control through the shared frame protocol on the actual site, including navigation, searching and input; assert the visible result. Test stale targets, duplicate commands and refusal of unapproved sends. Do not call a click receipt proof of saved or sent data. No outbound messages or purchases in tests.
