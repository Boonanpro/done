---
name: project-capability-scan
description: Evaluate, for a concrete project request, what current AI can execute now vs where human intervention is still required, using dated evidence and AI-first assumptions. Use when feasibility, schedule, team design, or cost estimates depend on latest model/tool capabilities, or when lane C / deep capability uncertainty is detected.
---

# Project Capability Scan

Run a bounded, evidence-backed scan of current AI capability for a specific project.

Assume AI-first by default, but never hardcode "this area is always human-only".
Re-evaluate boundaries for each request with fresh sources and explicit confidence.

Read:
- `actions/scan.md` for procedure and parameters.
- `references/source-policy.md` for source priority and recency rules.
- `references/scoring.md` for automation/confidence scoring.
- `references/output-examples.md` for output style.

## Workflow

1. Parse request into deliverables, constraints, and risk tolerance.
2. Split work into capability units (research, implementation, QA, deployment, ops, marketing, etc.).
3. For each unit, collect recent evidence and judge current AI execution level.
4. Mark required human touchpoints only when evidence indicates current limits.
5. Build AI-first plan and estimate:
- `p50` and `p90` duration (days)
- `p50` and `p90` cost (USD)
6. Report assumptions that may expire quickly.
7. Append the required machine-readable block.

## Output Rules

- Keep narrative concise and decision-oriented.
- Include dated sources for non-obvious claims.
- Do not present stale assumptions as facts.
- Currency for estimates is always `USD`.

After narrative, append this exact block:

```text
[CAPABILITY_SCAN]
scan_date_utc: YYYY-MM-DD
automation_percent: 0-100
confidence: 0.00-1.00
needs_human_now: true|false
human_required_areas: comma-separated|none
p50_duration_days: number
p90_duration_days: number
p50_cost_usd: number
p90_cost_usd: number
estimate_currency: USD
next_action: execute_ai_first|plan_then_execute|request_more_constraints
[/CAPABILITY_SCAN]
```

## Defaults

- Bias to "AI can do it now" only when evidence quality is sufficient.
- If evidence is weak or conflicting, lower confidence instead of forcing a binary claim.
- If critical data is missing, use `next_action=request_more_constraints`.
