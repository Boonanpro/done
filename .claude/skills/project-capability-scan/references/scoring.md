# Scoring Guide

Convert evidence into consistent automation and confidence scores.

## Automation Level per Capability Unit

- `full` (score 90-100): AI can execute end-to-end with minimal supervision.
- `assisted` (score 50-89): AI can do most work but needs human checkpoints or approvals.
- `limited` (score 0-49): current AI is unreliable or incomplete for critical outcomes.

## Confidence per Capability Unit

Start from `0.50`, then adjust:

- +0.20: Primary official source confirms capability.
- +0.10: Evidence is recent (<=30 days).
- +0.10: Two or more credible sources agree.
- -0.20: Sources conflict on key behavior.
- -0.20: Evidence is stale (>90 days) or indirect only.

Clamp final confidence to `0.00-1.00`.

## Aggregate Project Scores

- `automation_percent`: weighted mean of unit automation scores.
- Suggested weights: delivery-critical 3, important 2, optional 1.
- Project `confidence`: weighted mean of unit confidence scores.

## Human Requirement Rule

Set `needs_human_now=true` only when at least one delivery-critical unit remains `limited` or requires legal/financial approval that current workflow cannot automate safely.

## Default-Invert Rule（デフォルト反転）

全タスクは **automation_level=full (score 95)** からスタートする。
下げるには以下の全てを満たすこと:
1. 具体的な現在の技術的制限を明記（出典・日付付き）
2. 既存ツールやワークアラウンドで回避できない理由を説明
3. 人間に委ねた場合のコスト・時間を併記

根拠なくスコアを下げてはならない。
