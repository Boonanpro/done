---
name: self-dev
description: "Modify Dan runtime or infrastructure with process ownership and deployment awareness."
---

# Developing Dan

Use `D:/done/AGENTS.md` for scope, process ownership and delivery rules. Inspect the affected runtime or service before editing; preserve unrelated work.

Dan Core normally runs on 9000 and carries active chats; the sandbox normally runs on 8000. A file's directory alone does not prove which process imports it. Determine whether the change reloads dynamically or needs a restart.

Each room runs on one of several model backends (Claude CLI, Codex CLI; the list is `CLI_MODEL_OPTIONS` in `app/agent/cli_runner.py`), and the owner uses them side by side. Anything Dan does must behave the same on every backend. Put a rule where every backend's path passes through it, not inside one backend's path, and check the change on each backend before reporting it done. A check made on one backend is reported as checked on that backend only.

Run the checks relevant to the change. For instruction changes, check loading, assembled prompts and resumption. For a UI change, inspect the affected flow. Do not restart a server merely to validate Markdown. The dashboard (3000) is a production build; artifact tabs (`/preview/<slug>`) come from the development server (3001). When the change reaches artifact pages, Dan's browser check does not show the owner's screen: confirm with `python scripts/artifact_seen.py` that the owner's open screens, the artifact's server code and its published copy (what the phone app opens) run the current files before reporting; a test server such as 8001 or a worktree is only an intermediate test. An artifact's `_server` is swapped by the live sandbox within seconds (`app/services/artifact_backends.py`), so it needs no restart; a `routes.py` that starts a background thread defines `dan_unload()` to stop it, otherwise the swap is refused and a restart is reported. A turn that changed an artifact cannot end before that check (`scripts/hook_artifact_verify_gate.py`, Stop hook on both backends).

If a restart is needed, inspect current sessions and the actual restart mechanism. A task running inside Core cannot stop Core and go on; it hands the restart over with `scripts/restart_dan_core.py --when-idle` (see AGENTS.md) and is woken with the outcome. An external developer CLI can coordinate a restart without killing other work. Tell saved, tested and running apart yourself before calling it done; the owner is told only whether it works now, how use changes and what they must do — not how it was checked or which state the machinery is in.

Commit and publish within existing authorization; use the actual origin and separate scopes. Do not treat old action documents as a mandatory deployment sequence.
