# Output Examples

## Example 1 (High Automation)

Request: "Build a landing page + payment flow + automated email onboarding."

Summary:
- Most implementation and QA can be AI-driven with human review gates.
- Payment compliance review remains a human checkpoint.

```text
[CAPABILITY_SCAN]
scan_date_utc: 2026-02-24
automation_percent: 82
confidence: 0.79
needs_human_now: true
human_required_areas: payment compliance approval
p50_duration_days: 4
p90_duration_days: 8
p50_cost_usd: 180
p90_cost_usd: 520
estimate_currency: USD
next_action: execute_ai_first
[/CAPABILITY_SCAN]
```

## Example 2 (Uncertain Capability)

Request: "Fully autonomous legal negotiation bot for international contracts."

Summary:
- Capability boundary is uncertain and jurisdiction-dependent.
- High risk if treated as fully autonomous without strict human governance.

```text
[CAPABILITY_SCAN]
scan_date_utc: 2026-02-24
automation_percent: 44
confidence: 0.42
needs_human_now: true
human_required_areas: legal interpretation, final contract approval
p50_duration_days: 21
p90_duration_days: 45
p50_cost_usd: 2200
p90_cost_usd: 6800
estimate_currency: USD
next_action: plan_then_execute
[/CAPABILITY_SCAN]
```
