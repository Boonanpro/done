# Triage Action

Classify an incoming request into lane A0/A1/B/C and append the required triage block.

## Parameters

| Parameter | Required | Type | Description |
| --- | --- | --- | --- |
| `user_request` | yes | string | Original user request text |
| `context` | no | string | Extra background (current state, prior decisions) |
| `constraints` | no | string | Constraints such as budget, deadline, compliance requirements |

## Procedure

1. Read the request and constraints.
2. Break work into concrete tasks.
3. Select lane A0/A1/B/C based on scope, quality preference, uncertainty, and coordination needs.
4. Output concise rationale.
5. Append the required `[TRIAGE]` block.

## Output Rule

Always include:

```text
[TRIAGE]
lane: A0|A1|B|C
needs_capability_scan: true|false
confidence: 0.00-1.00
next_action: handle_locally|delegate_business_execute|delegate_business_plan|run_capability_scan
[/TRIAGE]
```
