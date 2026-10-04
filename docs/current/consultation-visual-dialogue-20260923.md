# Visual consultation follow-through

Implemented:
- Consultation sheet instructions describe this work, not the channel roadmap.
- Native Responses can call `show_consultation_visual` directly, without a CLI
  production job. Existing editable composition / sandboxed scene presentation
  handles diagrams, layouts and character comparisons in the conversation feed.
- A visual tool result reports actual presentation readiness before Dan can
  claim it is visible. Switching projects prevents presentation into another one.
- Accepted V-conte work sends the existing native `stage_compact` command while
  preserving the voice session; the sheet remains available to reopen.
- The progress area no longer repeats the full production request as live work.
- Jev ranking includes model-reviewed suitability and limitations, explicitly
  distinguished from human quality approval.

Verification:
- 41 consultation/presentation/Live unit tests, 19 observation/index tests,
  and 54 frontend context tests passed.
- `python -m scripts.check_consultation_decisions`: actual GPT-6 Astra selected
  the visual tool for an unclear spoken-description scenario and reference search
  with keep/change/next_axis for a refinement scenario. Fixed tool state was used;
  this is not a Live voice test.
- `python scripts/check_consultation_visual.py`: rendered the model's actual
  diagram in an isolated real editor; checked compact-stage IPC.
- Screenshot and raw tool decisions: `scratch/consultation-visual/`.

Data: 33 cross-genre works selected for further evidence enrichment. Final counts
are in `scratch/production-library-enrichment/report.json`. Inaccessible media
are not promoted into observed evidence.

Not delivered: freely draggable infinite board, interactive full-length animatic,
Jev-Omni integration, or proof of natural end-to-end voice behavior. The existing
timeline production path remains separate from this fast visual consultation.
