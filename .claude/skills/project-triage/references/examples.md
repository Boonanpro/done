# Examples

## Example 1: UI Refresh Request

Request:
"ダン自身のUIの色をリッチに変更して。"

Typical result:
- lane: A1
- needs_capability_scan: false
- next_action: delegate_business_execute

## Example 2: Gmail Notification Integration

Request:
"Gmailと連携し、返信や支払いが必要なメールを通知コンポーネントに表示して。"

Typical result:
- lane: A1 or B
- needs_capability_scan: false
- next_action: delegate_business_execute or delegate_business_plan

Reason:
- Integration and notification flow design are needed.
- Usually feasible with known APIs and implementation patterns.

## Example 3: AI-First New Business Plan

Request:
"この事業を立ち上げる場合、今のAIでどこまでできるか調べて期間と費用を見積もって。"

Typical result:
- lane: C
- needs_capability_scan: true
- next_action: run_capability_scan

Reason:
- Estimates depend on current AI capability and tooling conditions.
