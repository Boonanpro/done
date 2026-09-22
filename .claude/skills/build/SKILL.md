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

Choose the implementation order and design appropriate to the task. [design-options.md](references/design-options.md) lists optional components and approaches. Read a recipe only for the selected approach. HTML proposals use `actions/proposal_html.md` only when requested.

Verify affected behavior and appearance. A new responsive site needs relevant viewport, interaction, editing and delivery checks; a narrow fix needs checks for that fix and plausible regressions. Inspect screenshots yourself, but attach extra screenshots only when requested. Report the actual artifact URL and observed state.
