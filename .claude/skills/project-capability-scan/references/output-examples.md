# Output Examples

## Example 1 (High Automation)

Request: "Build a landing page + payment flow + automated email onboarding."

Summary:
- Implementation, QA, payment integration, and deployment are all AI-driven.
- Payment provider dashboard setup (Stripe account, API keys) is AI-executable with user approval【要承認】.
- No tasks require human execution.

```text
[CAPABILITY_SCAN]
scan_date_utc: 2026-02-24
automation_percent: 95
confidence: 0.79
needs_human_now: false
human_required_areas: none
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
- AI can build the bot, but legal validity of AI-negotiated contracts varies by jurisdiction.
- Human required【要人間】: final contract signing (legal signature requirement in many jurisdictions).

```text
[CAPABILITY_SCAN]
scan_date_utc: 2026-02-24
automation_percent: 44
confidence: 0.42
needs_human_now: true
human_required_areas: legal contract signing (jurisdictional signature requirements)
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
- Stripe本番審査申請、DNS設定、特定商取引法ページ作成は全てブラウザ操作で実行可能【要承認】。
- 人間が必要なタスク【要人間】はなし（全てAIがブラウザ・コード・APIで実行可能）。
- AI自律タスク: 要件定義、DB設計、フロント/バックエンド実装、メールテンプレート作成、Stripe連携・審査申請、DNS設定、テスト、デプロイ、LP作成。

```text
[CAPABILITY_SCAN]
scan_date_utc: 2026-02-26
automation_percent: 97
confidence: 0.75
needs_human_now: false
human_required_areas: none
p50_duration_days: 14
p90_duration_days: 30
p50_cost_usd: 500
p90_cost_usd: 2000
estimate_currency: USD
next_action: execute_ai_first
[/CAPABILITY_SCAN]
```
