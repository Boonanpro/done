# Phase 3+4: ステップごとの段階的実行 + 完了検証

## 現状の問題

```
今の実行フロー:

[全ステップを1つのプロンプトに詰める]
     ↓
[CLI Runnerに1回送る（max-turns 200）]
     ↓
[CLIが全部やる（途中で止められない）]
     ↓
[終わった後にRegexで完了判定]
     ↓
[DB更新]
```

問題点:
- 途中で止められない（Red操作があっても突っ走る）
- 完了判定がRegex（AIの自己申告を信用）
- ステップの進捗がリアルタイムで見えない
- 1ステップ失敗しても残り全部やろうとする

## 目指す姿

```
新しい実行フロー:

[ステップ1のプロンプトを送る]
     ↓
[CLI Runnerが実行]
     ↓
[完了検証（LLM判定）] → 失敗 → リトライ or 停止
     ↓ 成功
[DB更新: ステップ1 = completed]
     ↓
[次のステップがRedか？] → Yes → ユーザー確認を待つ
     ↓ No
[ステップ2のプロンプトを送る]
     ↓
  ... 繰り返し ...
     ↓
[全ステップ完了 → 完了報告]
```

## 変更対象ファイル

| ファイル | 変更内容 |
|---------|---------|
| `app/services/project_execution.py` | メイン: ステップループ実行 + 検証ロジック |
| `app/api/project_routes.py` | Red確認のAPI追加、実行再開のエンドポイント |
| `app/services/project_service.py` | ステップ状態管理の拡張 |
| `app/models/project_schemas.py` | スキーマ追加（確認待ち状態等） |

## 実装ステップ

### Step 1: ステップループ実行（project_execution.py の書き換え）

今の `_start_project_execution` は全ステップを1プロンプトで送る。
これを「1ステップずつ送るループ」に変える。

```python
# 概念コード（実際の実装はこれをベースに調整）

async def run_project_execution(...):
    """ステップごとに実行するメインループ"""

    for i, step in enumerate(steps):
        # 1. ステップ開始をDB記録
        await update_step_status(proposal_id, step["step_number"], "in_progress")

        # 2. このステップ専用のプロンプトを組み立て
        prompt = build_step_prompt(
            step=step,
            previous_results=results_so_far,
            project_context=project_context,
        )

        # 3. CLI Runnerで実行
        response = await execute_step_via_cli(prompt, room_id, user_id)

        # 4. 完了検証（LLM判定）
        verification = await verify_step_completion(step, response)

        # 5. 結果に応じて分岐
        if verification.status == "completed":
            await update_step_status(proposal_id, step["step_number"], "completed")
            results_so_far.append(verification.summary)
        elif verification.status == "failed":
            await update_step_status(proposal_id, step["step_number"], "failed")
            # 後続ステップへの影響を判断
            if verification.should_abort:
                break

        # 6. 次のステップがRed操作か確認
        next_step = steps[i + 1] if i + 1 < len(steps) else None
        if next_step and is_red_zone(next_step):
            await pause_for_confirmation(project_id, next_step)
            return  # ユーザー確認後に再開される
```

### Step 2: ステップ単位のプロンプト設計

全ステップを一気に送るのではなく、1ステップずつ送る。
ただし前のステップの結果は文脈として渡す。

```python
def build_step_prompt(step, previous_results, project_context):
    """1ステップ分の実行プロンプト"""
    return f"""
## 現在のタスク
ステップ {step['step_number']}: {step['description']}

## これまでの実行結果
{format_previous_results(previous_results)}

## プロジェクト情報
{project_context}

## 実行ルール
- このステップだけを実行してください
- 完了したら結果を報告してください
- 失敗した場合は理由と影響範囲を報告してください
"""
```

### Step 3: 完了検証（LLM判定）

Regexの代わりにLLM（Haiku）で検証する。

```python
async def verify_step_completion(step, cli_response):
    """ステップが本当に完了したかLLMで検証"""

    prompt = f"""以下のステップの実行結果を評価してください。

## ステップ
{step['description']}

## 実行ログ（CLIの出力）
{cli_response.text[:3000]}

## 使用されたツール
{format_tools_used(cli_response.tool_events)}

## 判定基準
以下のJSONで回答してください:
{{
  "status": "completed" | "failed" | "partial",
  "confidence": 0.0-1.0,
  "summary": "何が達成されたかの1行要約",
  "evidence": "成功/失敗の根拠",
  "should_abort": true/false  // 後続ステップを中止すべきか
}}
"""
    # Haiku で判定（安い・速い）
    result = await call_llm(model="claude-haiku-4-5-20251001", prompt=prompt)
    return parse_verification(result)
```

### Step 4: Red操作の確認待ち

ステップに「【要操作】」タグがある or 内容がRed判定の場合、
実行を一時停止してユーザー確認を待つ。

```python
def is_red_zone(step):
    """ステップがRed操作（ユーザー確認必須）かを判定"""
    desc = step.get("description", "")
    red_keywords = ["購入", "確定", "送金", "振込", "削除", "解約", "個人情報", "【要操作】"]
    return any(kw in desc for kw in red_keywords)

async def pause_for_confirmation(project_id, next_step):
    """プロジェクトを確認待ち状態にする"""
    await project_service.update_project(
        project_id, user_id,
        status="awaiting_confirmation",
        metadata={
            "pending_step": next_step["step_number"],
            "confirmation_message": f"次のステップは確認が必要です:\n{next_step['description']}\n\n実行してよろしいですか？",
        }
    )
    # チャットにも確認メッセージを送信
    await chat_service.send_dan_ai_message(...)
```

### Step 5: 確認後の実行再開API

```python
# project_routes.py に追加

@router.post("/{project_id}/resume")
async def resume_execution(project_id, current_user):
    """確認待ちのプロジェクトの実行を再開"""
    project = await service.get_project(project_id, current_user.user_id)
    if project["status"] != "awaiting_confirmation":
        raise HTTPException(400, "Not in confirmation state")

    # 中断地点から実行を再開
    pending_step = project["metadata"]["pending_step"]
    # ... 残りのステップを実行
```

## プロジェクト/提案のステータス拡張

```
現在:
  project.status: planning → proposed → approved → in_progress → completed/paused

追加:
  project.status: ... → in_progress → awaiting_confirmation → in_progress → completed

  step.status: pending → in_progress → completed/failed
```

## CLIセッション管理の考慮事項

現在の設計では1プロジェクト = 1 CLIセッション（`--resume`で会話を継続）。
ステップごとに実行する場合、2つの選択肢がある:

- **A: 同じセッションを継続** — 前のステップの文脈がCLI内に残る（自然）
- **B: ステップごとに新規セッション** — 文脈は自前のプロンプトで渡す（制御しやすい）

→ **A方式を採用**。`--resume`でセッションを継続し、各ステップのプロンプトを追加メッセージとして送る。これによりCLI内のブラウザセッションやファイル操作の文脈が保持される。

## 実装順序

| # | 内容 | 依存 |
|---|------|------|
| 1 | `project_execution.py` をステップループに書き換え | なし |
| 2 | ステップ単位プロンプト（`build_step_prompt`） | #1 |
| 3 | LLM完了検証（`verify_step_completion`） | #1 |
| 4 | Red判定 + 確認待ちステータス | #1 |
| 5 | 実行再開API（`/resume`） | #4 |
| 6 | フロントエンド対応（ステップ進捗表示、確認UI） | #5 |

## リスクと対策

| リスク | 対策 |
|--------|------|
| ステップごとにCLI起動するとコスト増 | `--resume`でセッション継続、promptは最小限に |
| Haiku検証が間違う | confidence閾値を設定、低い場合は人間に聞く |
| 確認待ちで放置される | タイムアウト設定（24h）、リマインド通知 |
| ステップ間の文脈が切れる | previous_resultsで要約を渡す + CLIセッション継続 |
