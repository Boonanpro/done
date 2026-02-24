---
name: project-triage
description: Classify incoming requests into lane A0 (secretary direct), A1 (business direct), B (light planning), or C (deep capability scan). Use when deciding whether to execute immediately or route to business planning, especially for feature requests, integrations, scope changes, or ambiguous multi-step tasks.
---

# Project Triage

Classify a request into execution lane A0/A1/B/C with an AI-first mindset and minimal process overhead.

Keep narrative output flexible, but always append a short machine-readable triage block.

## Workflow

1. Parse the request and constraints.
2. Split the work into concrete tasks.
3. Judge uncertainty and execution complexity per task.
4. Select one lane for the whole request:
- `A0` secretary direct implementation
- `A1` business direct implementation
- `B` light planning
- `C` deep capability scan
5. Provide a short rationale.
6. Append the required triage block.

## Lane Definitions

### Lane A0: Secretary Direct
- Use for simple direct execution in secretary scope (Q&A, memory operations, straightforward non-code handling).
- Keep turnaround minimal.

### Lane A1: Business Direct
- Use for implementation tasks where quality should be prioritized by business workers (Opus path), even if complexity is moderate.
- Avoid heavy market research; focus on execution.

### Lane B: Light Planning
- Use when work has multiple steps or dependencies, but technology fit is still mostly known.
- Produce a compact plan before execution.
- Perform only focused checks for missing facts.

### Lane C: Deep Capability Scan
- Use when high-impact decisions depend on current AI capability limits, market/tool changes, or uncertain feasibility.
- Trigger `Project Capability Scan` before committing schedule/cost/team estimates.
- Prefer evidence-backed judgement with dated sources.

Read `references/lane-criteria.md` when lane selection is unclear.

## Required Output Block

After normal explanation, append this exact block:

```text
[TRIAGE]
lane: A0|A1|B|C
needs_capability_scan: true|false
confidence: 0.00-1.00
next_action: handle_locally|delegate_business_execute|delegate_business_plan|run_capability_scan
[/TRIAGE]
```

Rules:
- Keep values single-line.
- `lane=A0` should set `next_action=handle_locally`.
- `lane=A1` should set `next_action=delegate_business_execute`.
- `lane=B` should set `next_action=delegate_business_plan`.
- `lane=C` must set `needs_capability_scan=true` and `next_action=run_capability_scan`.
- Narrative text stays free-form; only this block is fixed.

## Defaults

- Bias to `A0` for simple secretary-scope work.
- Bias to `A1` for implementation requests where quality-first execution is preferred.
- Move to `B` when sequencing/coordination is needed.
- Use `C` only when uncertainty is material to feasibility or estimates.

Execution profile:
- `quality_first`: when lane is ambiguous between `A0` and `A1`, prefer `A1`.
- `speed_first`: when lane is ambiguous between `A0` and `A1`, prefer `A0`.

## Examples

- "Dan自身のUIの見た目をリッチに改善して": usually A1
- "Gmailと連携して、返信や支払いが必要なメールを通知コンポーネントに表示して": usually A1 or B
- "返信必須メールの自動リマインド事業を作りたい。プロジェクト化して計画化して": usually C

Read references/examples.md for full examples.
