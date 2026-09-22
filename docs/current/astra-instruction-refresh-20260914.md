# Dan instruction refresh — 2026-09-14

Target: GPT-6 Astra. The user explicitly chose optimization for this agent without preserving Claude-oriented prompt compatibility.

## Active changes

- `AGENTS.md` is the repository entry point. `CLAUDE.md` points to it; Codex no longer uses CLAUDE.md as a fallback. Existing hooks and tool execution contracts remain intact.
- `~/.dan/workspace/RULES.md` decreased from 11,587 to 1,412 characters. Task-specific operational knowledge lives in `references/task-preferences.md`; USER.md and memory files were not rewritten. SOUL.md now permits useful progress updates and domain-appropriate explanations.
- Removed unconditional full-skill workflows, repeated approval before implementation, forced dashboards for explanations, and contradictory historical deployment promises from active general instructions.
- Codex receives the current room prompt once per turn instead of freezing a duplicate at thread creation. The stable instruction fingerprint includes runtime policies and rotates on policy changes, not room-state changes.
- All 32 repository skill descriptions were narrowed (36 files including the four `.agents` copies). Detailed capability scripts and tool action schemas were preserved.
- Rebuilt build, self-dev, media-gen and skill-creator entry points. Website integration and optional design choices are separate references. Generation routing honors the user's selected model instead of a historical universal provider/model default.
- Browser handoff mechanics remain in the small runtime contract. Authentication details are in `dan-browser-auth.md`; logging in no longer implies changing account security settings.

## Verification

26 distinct tests passed across `test_astra_instructions`, `test_editor_prompt_transport`, `test_editor_codex`, and `test_session_model_switch`. These cover skill discovery and links, instruction delivery, policy-triggered thread rotation, preserved tool/image transport, and model session transitions.

The live skill reload endpoint returned 32 skills. This verifies discovery, not creative quality or a measured improvement in model latency. No claim of empirical optimality follows from shorter instructions. Operation-specific third-party manuals were retained; this is not a line-by-line rewrite of every installed global or plugin skill.

Activation completed locally: checked that no chat sessions or production jobs were running, stopped the owned sandbox through its API, restarted the verified Core PID through the standard startup script, and reloaded skills. Core (9000) and sandbox (8000) both returned HTTP 200 after restart. These changes have not been committed or pushed.

## Recovery and scope

Pre-edit copies of mutable workspace rules, repository CLAUDE.md, the already-modified cli_runner.py, and edited skill files are in `D:/done/scratch/dan-instructions-before-20260914/`. Restore only a reviewed affected file or hunk; do not reset the working tree, which contains other active work.

Model IDs, authentication configuration, billing, tools, user memory and third-party global skill installations were not migrated. Local instruction refresh does not authorize external messages or spending; the user's explicit telephone restriction remains active.

Source: [OpenAI: Rethinking skills and prompts for GPT-6 Astra](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra).
