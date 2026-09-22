---
name: self-dev
description: "Modify Dan runtime or infrastructure with process ownership and deployment awareness."
---

# Developing Dan

Use `D:/done/AGENTS.md` for scope, process ownership and delivery rules. Inspect the affected runtime or service before editing; preserve unrelated work.

Dan Core normally runs on 9000 and carries active chats; the sandbox normally runs on 8000. A file's directory alone does not prove which process imports it. Determine whether the change reloads dynamically or needs a restart.

Run the checks relevant to the change. For instruction changes, check loading, assembled prompts and resumption. For a UI change, inspect the affected flow. Do not restart a server merely to validate Markdown.

If a restart is needed, inspect current sessions and the actual restart mechanism. A task running inside Core must preserve its communication path. An external developer CLI can coordinate a restart without killing other work. Report saved, tested and running states separately.

Commit and publish within existing authorization; use the actual origin and separate scopes. Do not treat old action documents as a mandatory deployment sequence.
