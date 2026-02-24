# Examples

## Example 1: UI Refresh Request

Request:
"Dan自身のUIの見た目をリッチに改善してください。"

Typical result:
- lane: A1
- needs_capability_scan: false
- next_action: delegate_business_execute

## Example 2: Gmail Notification Integration

Request:
"Gmailと連携して、返信や支払いが必要なメールを通知コンポーネントに表示してください。"

Typical result:
- lane: A1 or B
- needs_capability_scan: false
- next_action: delegate_business_execute or delegate_business_plan

Reason:
- Integration and notification flow design are needed.
- Usually feasible with known APIs and implementation patterns.

## Example 3: AI-First New Business Plan

Request:
"新規事業として、見積返信メールの未返信放置を防ぐため、Outlook/Gmail向けに『返信必須メールの自動リマインド』を提供するツールを作りたい。プロジェクト化し、計画を立ててください。"

Typical result:
- lane: C
- needs_capability_scan: true
- next_action: run_capability_scan

Reason:
- Estimates depend on current AI capability and tooling conditions.
