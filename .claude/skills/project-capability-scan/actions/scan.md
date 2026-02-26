# Capability Scan Action

Assess, for a specific project request, how far current AI can execute now.

## Parameters

| Parameter | Required | Type | Description |
| --- | --- | --- | --- |
| `user_request` | yes | string | Original project request text |
| `constraints` | no | string | Budget/deadline/risk/compliance constraints |
| `execution_profile` | no | string | `quality_first` or `speed_first` |
| `prior_context` | no | string | Existing decisions or previous scan results |

## Procedure

1. Decompose the request into capability units.
2. Collect recent evidence per unit using `references/source-policy.md`.
3. Score automation and confidence using `references/scoring.md`.

### Task Granularity Rule（タスク分解の粒度ルール）

各capability unitの推定作業時間（人間換算）で自動化率の下限を設定する:
- **4分未満** → automation_level=full (100% AI)
- **4分〜1時間** → automation_level=full (80%+ AI)
- **1〜4時間** → automation_level=assisted (50-70% AI)
- **4時間超** → **分解不足。さらに細かいunitに分割せよ。**

4. Build AI-first duration and cost estimates in USD.
5. Summarize human touchpoints only where current evidence requires them.
6. Output concise rationale and append the required block.

### Self-Review（自己レビュー）

出力前に以下をチェックする:
- `full` 未満のタスクごとに「なぜAIにできないか」を1文で述べられるか確認する。述べられなければスコアを95に戻す。
- 全体期間が「タスク数 × 平均AI完了時間」の2倍を超える場合、その理由を明記する。
- `references/anti-bias.md` のチェックリストを通す。

## Required Output Block

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
