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

## Example 3 (Large-Scale AI-First Project)

Request: "メールリマインド SaaS事業を立ち上げたい。ユーザー登録、リマインド設定、メール送信、決済、LPまで全部。"

Summary:
- フルスタックSaaS構築はAI-firstで大幅に自動化可能。
- Next.js + Supabase + Stripe + SendGrid 等の標準スタックをAIが構築・デプロイ。
- 人間が必要なのは: Stripe本番審査の申請操作、特定商取引法の最終確認、ドメイン設定のDNS操作のみ。
- AI自律タスク: 要件定義、DB設計、フロント/バックエンド実装、メールテンプレート作成、Stripe連携、テスト、デプロイ設定、LP作成。

```text
[CAPABILITY_SCAN]
scan_date_utc: 2026-02-26
automation_percent: 88
confidence: 0.75
needs_human_now: true
human_required_areas: Stripe本番審査申請, 特定商取引法の最終確認, DNS設定
p50_duration_days: 14
p90_duration_days: 30
p50_cost_usd: 500
p90_cost_usd: 2000
estimate_currency: USD
next_action: execute_ai_first
[/CAPABILITY_SCAN]
```
