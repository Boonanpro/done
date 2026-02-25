# Dan Core Inventory (Chat First)

Last updated: 2026-02-24

## 1) What is already unified

- Chat requests run on one execution path (CLI) for both:
  - normal chat
  - project chat
- Automatic pre-triage routing from chat is disabled.
- Automatic project creation from chat tools is disabled.

## 2) Actual request flow (today)

1. User sends message to Dan chat stream endpoint.
2. Server checks whether the room is a project room.
3. Both branches call the same CLI runner (`process_message_cli`).
4. CLI runner launches Claude CLI with:
   - appended system prompt
   - MCP server config file
5. CLI emits events (`reasoning`, `tool_use`, `text`, `result`, `error`) and server streams them.
6. Final AI message is stored in DB and returned to UI.

## 3) System prompt inputs used by CLI (today)

CLI prompt builder:
- `app/agent/cli_runner.py` `_build_system_prompt(...)`
- `app/agent/core_runtime_contract.md` (single runtime contract source)

Current behavior:
- Planning status:
  - uses team leader resident prompt
  - appends shared bootstrap context
  - appends runtime contract (tools/skills/policy)
- Non-planning status:
  - uses Dan core base sentence
  - appends shared bootstrap context
  - appends runtime contract (tools/skills/policy)
  - appends project context template only when metadata exists

Shared bootstrap context is loaded via:
- `app/agent/v2/runner.py` `load_all_bootstrap_files()`

Loaded files:
- `USER.md`
- `MEMORY.md`
- recent daily memory files
- `SOUL.md`
- `RULES.md` (last in order)

## 4) Workspace files currently available

Workspace root:
- `~/.dan/workspace`

Observed files:
- `USER.md`
- `SOUL.md`
- `RULES.md`
- `MEMORY.md`
- `HEARTBEAT.md`
- `HEARTBEAT_PROMPT.md`
- `memory/YYYY-MM-DD.md` (daily files)

## 5) Tool surface currently available to chat CLI

A. Claude CLI built-in tools (not exposed via MCP):
- `read_file`
- `write_file`
- `edit_file`
- `bash`

B. MCP tools exposed by Dan server (`get_all_skill_tools`):
- browser tools (`open/screenshot/click/type/scroll/back/select`)
- `read_url`
- `deep_research`
- `skill_generate`
- credentials tools (`save_credentials`, `get_credentials`)
- `check_skill`
- workspace tools (`read_workspace`, `update_workspace`, `search_memory`)

Explicitly not exposed now:
- `create_project`

## 6) Skill loading model (today)

Skill directories:
- `.claude/skills/*/SKILL.md`
- (plus local internal path if present)

Observed project skills:
- `amazon`
- `rakuten`
- `find-skills`
- `note`
- `project-triage`
- `project-capability-scan`
- `ui-ux-pro-max`
- `vercel-react-best-practices`

How skills are used now:
- `check_skill` returns manual text from `SKILL.md` and `actions/*.md`.
- Generated skills can execute via generated executor.
- Non-generated skills are mostly manual-driven: model reads manual and then uses browser/tools.

CLI runtime contract now injects:
- available built-in tools
- available MCP tools
- available skills
- skill usage policy

## 7) Current product-level risks

1. Project creation UX risk:
   - Chat cannot directly call `create_project` tool now.
2. Contract sprawl risk:
   - Runtime contract is file-backed and now reused by CLI + Gemini channels.
3. Channel parity risk:
   - Chat, heartbeat, Gemini, and `/ws/voice` now run on shared contract path.
   - Remaining legacy `v2/runner.py` usage is mainly in old SDK/compat paths and should be retired.

## 8) Recommended next implementation order

1. Keep one versioned core prompt contract as single source.
2. Define project creation behavior in chat.
3. Remove remaining old runner-specific prompt paths.
4. Align any future channel additions to the same runtime contract renderer.
