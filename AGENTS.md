# Dan development

Dan is a personal assistant. Each room runs on Claude or GPT, and the owner uses both. Dan must behave the same on both; write prompts and skills so that either model can follow them.

Complete the user's requested outcome, including relevant verification and delivery. Carry forward prior authorization and corrections. Choose routine implementation details yourself. Ask only for information or authorization that is actually missing; finish independent preparation first. Do not infer permission to contact people, spend money, or expand the task.

Use only the documents and skills needed for the current operation. A skill supplies domain knowledge and operational constraints, not an obligatory itinerary. User requirements take precedence over skill preferences. When a rule prevents progress, identify its source and the exact conflict.

## Workspace

- `app/core/` and `app/agent/`: Dan Core, normally port 9000, carries live conversations.
- `app/api/` and `app/services/`: check route ownership before deciding which process needs a restart. Sandbox normally uses port 8000.
- `frontend/`: dashboard production server on 3000; artifact preview development server on 3001. Production changes require a build; editing a file does not prove deployment.
- `~/.dan/workspace/`: user preferences, operational rules and memory. Read topic details when needed; do not load all memories.
- User websites belong under `frontend/src/app/artifacts/<slug>/`, their server code included (`<slug>/_server/` for Python routes); Dan keeps only generic code. The folder is recorded in done-artifacts on publish and hourly; preserve an existing project's source of truth. Read `.claude/skills/build/SKILL.md` when creating or changing an editable website. Other deliverables do not require this skill.

## Changes and verification

Preserve existing work, including uncommitted changes. Review and stage only the current task's changes. Never use a whole-workspace restore, stash or clean to undo a task.

Verify the behavior affected by the change. For user interfaces, inspect the actual result; for instruction loaders, check the assembled context and session update behavior. Repeat or broaden checks only for a new failure, change or unresolved concern. Do not turn a local wording edit into a full deployment or account test.

Do not stop a live conversation to reload code. Establish the process owner and active sessions before a necessary restart. Terminate only a verified PID belonging to the intended process; never kill all Python or Node processes. On Windows launch background helpers hidden.

Work happens in a worktree of its own, never in the running folder (`/Users/mikihonda/done` on the Mac mini, `D:\done` on the Windows standby). The running folder is what runs; only `scripts/follow_github.py` changes the files git tracks there. `scripts/hook_live_tree_guard.py` refuses other writes from Claude and Codex before a tool runs, and after it ran moves any tracked file that changed anyway (a script, a program) onto the session's branch `wip/<date>-<session>` and puts the committed version back. What git does not track stays writable there: user artifacts (`frontend/src/app/artifacts/<slug>/`, `frontend/public/artifacts/<slug>/`) and runtime data. One road for each piece of work: `python ~/done/scripts/work.py new <name>` makes `~/dan-workspace/<name>` on branch `dan/<name>` from `origin/main` (`--from <branch>` continues a branch), with its own `frontend/node_modules` (a copy-on-write clone) and, after `work.py venv`, its own Python in `.venv`; installing there never reaches the running Dan. `work.py save` often, since committed work cannot be overwritten or lost (it commits tracked changes and new files in the repository's folders, not a new top folder of notes; `--only <path>` names files). `work.py test -- <command>` runs the tests and remembers the command; `work.py try` runs that worktree (API 8001, screens 3002; `try stop`). `work.py ship "<title>"` takes in main and stops on a clash so you settle it on your own branch, runs the remembered tests again when main brought anything, then pushes, merges the PR and brings the running folder up to main; it fails (exit 1) when the running folder could not follow, saying so. Making a finished change run is part of the work, and the owner agreed (2026-10-13) that it needs no question when nothing in use is interrupted. Core and sandbox: `python D:/done/scripts/restart_dan_core.py` stops them and refuses while a call, a turn or parallel work is running. A turn inside Dan runs in Core, so it cannot stop Core and go on: `--when-idle --then "<what to check afterwards>"` hands the restart to a process outside Core, which waits until the asking turn and all other work have ended, checks that the code loads, restarts, runs `scripts/verify_dan.py` and wakes the asking room with the outcome; check the change there and report. From outside Dan, start afterwards with `scripts\dan_core_autostart.bat` (hidden) and run `scripts/verify_dan.py`. Dashboard: `python scripts/frontend_prod.py restart` builds beside the running server and swaps it in within seconds; turns continue. Anything left uncommitted in the running folder is named by follow_github; `python scripts/rescue_wip.py` groups it by the session that wrote it and `--apply` saves all of it onto `wip/...` branches before putting anything back, losing nothing (copies of what it put back stay in `.git/dan/rescued/`).

## Delivery and publishing

Commit scopes separate Dan infrastructure from each artifact. `scripts/scope_diff.py` explains the classification. For authorized pushes, inspect the actual `origin`; since 2026-09-20 it is GitHub again (`gitlab` remains as a mirror remote, kept in step when convenient). Approval already given for the same action persists. Do not commit unrelated changes.

The GitHub account was suspended for seven weeks in 2026 because of machine-like traffic: an unattended retry loop that sent failing authenticated requests for weeks, an automated password login, and hundreds of self-merged pull requests a month. Keep GitHub use human-paced. Collect related work into few pushes or pull requests a day rather than one per small change. If a GitHub request fails with an authentication or permission error, stop after that one attempt and report it; never retry in a loop or on a timer. Never automate signing in to github.com (the `gh` credential helper is the only authentication path). `work.py ship` asks GitHub each thing once and stops at the first refusal.

Artifact publication uses the current registration/publish service, not an arbitrary deployment of a shared worktree. Read the implementation for source ownership, native slug handling and returned URLs before publishing. Verify the registered URL before claiming it is live; do not promise success based on an estimated wait.

Keep credentials in the credential service, never in skill text, logs or source files. Reuse authenticated browser sessions. Change account security settings only when that change is within the user's request.

## References by task

- Runtime prompts: `app/agent/bootstrap_context.py`, `app/agent/cli_runner.py`, `app/agent/codex_runner.py`.
- Browser sessions: `docs/current/browser-lifecycle.md` and `docs/current/browser-speed-and-verification.md`.
- Editable artifact integration: `docs/editable-artifact-build-integration.md`.
- Current project documentation: `docs/current/README.md`; read only the topic relevant to the task.

Report the result, verification and any actual remaining limitation concisely in the user's language. Supply the requested artifact or link. Distinguish tested, saved and published states.
