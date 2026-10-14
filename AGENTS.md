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

What runs is the code on disk in `D:\done`; a commit or merge elsewhere does not change it. The folder follows GitHub main through `python D:/done/scripts/follow_github.py`: run it after every push, and the restart script runs it before stopping. It brings in what was pushed from elsewhere, leaves uncommitted work alone, and stops without changing anything when one file has both uncommitted work and a change from GitHub it lacks; settle that file and run it again. Do not bring the folder up to date any other way (`git pull`, checkout, reset and stash stay off-limits here), and do not copy pushed files into it by hand. `git status` in `D:\done` then lists exactly the uncommitted work. Making a finished change run is part of the work, and the owner agreed (2026-10-13) that it needs no question when nothing in use is interrupted. Core and sandbox: `python D:/done/scripts/restart_dan_core.py` stops them and refuses while a call, a turn or parallel work is running. A turn inside Dan runs in Core, so it cannot stop Core and go on: `--when-idle --then "<what to check afterwards>"` hands the restart to a process outside Core, which waits until the asking turn and all other work have ended, checks that the code loads, restarts, runs `scripts/verify_dan.py` and wakes the asking room with the outcome; check the change there and report. From outside Dan, start afterwards with `scripts\dan_core_autostart.bat` (hidden) and run `scripts/verify_dan.py`. Dashboard: `python scripts/frontend_prod.py restart` builds beside the running server and swaps it in within seconds; turns continue. That build ships everything in `frontend/`, other sessions' unfinished edits included.

## Delivery and publishing

Commit scopes separate Dan infrastructure from each artifact. `scripts/scope_diff.py` explains the classification. For authorized pushes, inspect the actual `origin`; since 2026-09-20 it is GitHub again (`gitlab` remains as a mirror remote, kept in step when convenient). Approval already given for the same action persists. Do not commit unrelated changes.

The GitHub account was suspended for seven weeks in 2026 because of machine-like traffic: an unattended retry loop that sent failing authenticated requests for weeks, an automated password login, and hundreds of self-merged pull requests a month. Keep GitHub use human-paced. Collect related work into few pushes or pull requests a day rather than one per small change. If a GitHub request fails with an authentication or permission error, stop after that one attempt and report it; never retry in a loop or on a timer. Never automate signing in to github.com (the `gh` credential helper is the only authentication path). `D:\done` is the live runtime tree with many sessions' uncommitted work: commit from a separate `git worktree` based on `origin/main`, not by pulling, checking out or stashing there.

Artifact publication uses the current registration/publish service, not an arbitrary deployment of a shared worktree. Read the implementation for source ownership, native slug handling and returned URLs before publishing. Verify the registered URL before claiming it is live; do not promise success based on an estimated wait.

Keep credentials in the credential service, never in skill text, logs or source files. Reuse authenticated browser sessions. Change account security settings only when that change is within the user's request.

## References by task

- Runtime prompts: `app/agent/bootstrap_context.py`, `app/agent/cli_runner.py`, `app/agent/codex_runner.py`.
- Browser sessions: `docs/current/browser-lifecycle.md` and `docs/current/browser-speed-and-verification.md`.
- Editable artifact integration: `docs/editable-artifact-build-integration.md`.
- Current project documentation: `docs/current/README.md`; read only the topic relevant to the task.

Report the result, verification and any actual remaining limitation concisely in the user's language. Supply the requested artifact or link. Distinguish tested, saved and published states.
