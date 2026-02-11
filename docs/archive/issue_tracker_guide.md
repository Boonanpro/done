# Issue Tracker Guide

## 概要

Done AIシステムで実装すべき機能を自動検知し、優先度を追跡するシステムです。

ユーザーが実行できなかったリクエストを自動的にイシューとして記録し、発生回数に基づいて優先度を決定します。

## 仕組み

### 1. 自動イシュー検知

AISecretaryAgentが以下の場合にイシューを自動記録：

1. **Executor Missing** - 対応するExecutorが存在しない
   - 例: 「JALで飛行機予約」→ JAL Executorが未実装

2. **Search Failed** - 検索が失敗した
   - 例: セレクタが古い、サイト構造が変わった

3. **Execution Failed** - 実行に失敗した（将来実装）
   - 例: ログインエラー、予約失敗

### 2. 優先度の自動計算

同じイシューが複数回発生すると、優先度（priority）が自動的に上がります。

- 初回発生: priority = 1
- 2回目発生: priority = 2
- 10回発生: priority = 10

優先度が高いイシューから実装すべきです。

### 3. 解決策の自動提案

各イシューに対して、AIが解決策を自動生成：

- 新規Executor実装の手順
- セレクタ更新の手順
- 推定作業量

## 使い方

### イシュー一覧を確認

```bash
# 全イシューを表示（優先度順）
python scripts/list_issues.py

# Executor不足のイシューのみ表示
python scripts/list_issues.py --type executor_missing

# Airline関連のイシューのみ表示
python scripts/list_issues.py --service-type airline

# 上位10件のみ表示
python scripts/list_issues.py --limit 10
```

**出力例:**
```
================================================================================
Open Issues（優先度順）
================================================================================

1. [Priority: 12] JAL
   Type: executor_missing
   Service: jal (airline)
   Error: Executor not found for jal
   Created: 2026-01-13T10:23:15.123456+00:00
   Last occurred: 2026-01-15T14:05:32.654321+00:00
   ID: uuid-xxx-xxx

   💡 Suggested Solution:
      - jalのExecutorを新規実装する必要があります
      - Effort: medium

2. [Priority: 7] Rakuten
   Type: selector_outdated
   Service: rakuten (product)
   Error: Search failed: セレクタが見つかりません
   ...
```

### イシュー詳細を確認

```bash
python scripts/show_issue.py <issue_id>
```

**出力例:**
```
================================================================================
Issue Details: uuid-xxx-xxx
================================================================================

Type: executor_missing
Status: open
Priority: 12 (発生回数)

Service Type: airline
Service Name: jal

Error Message: Executor not found for jal

Created:  2026-01-13T10:23:15.123456+00:00
Updated:  2026-01-15T14:05:32.654321+00:00
Last Occurred:  2026-01-15T14:05:32.654321+00:00

--------------------------------------------------------------------------------
Research Result (AI推論結果):
--------------------------------------------------------------------------------
  Task Type: travel
  Service Display Name: JAL（日本航空）
  Params: {
    "departure": "羽田",
    "arrival": "福岡",
    "date": "2026-01-20",
    "transport_type": "flight"
  }

--------------------------------------------------------------------------------
Suggested Solutions:
--------------------------------------------------------------------------------
1. create_executor
   Description: jalのExecutorを新規実装する必要があります
   Estimated Effort: medium
   Suggested File: app/executors/jal_executor.py
   Steps:
      - jalの公式サイトを分析
      - 予約フローを調査
      - 必要なセレクタを特定
      - search()メソッドを実装
      - execute()メソッドを実装
      - ExecutorRegistryに登録
      - テストスクリプトを作成

--------------------------------------------------------------------------------
Occurrences (最新10件):
--------------------------------------------------------------------------------
1. 2026-01-15T14:05:32.654321+00:00
   Wish: 羽田から福岡まで飛行機で行きたい
   Error: Executor not found for jal

2. 2026-01-14T09:12:45.123456+00:00
   Wish: 羽田から札幌までJALで予約して
   Error: Executor not found for jal
...
```

### イシューを解決済みにする

```bash
# 解決済みにする
python scripts/resolve_issue.py <issue_id>

# 作業中にする
python scripts/resolve_issue.py <issue_id> --status in_progress

# 対応しない（wont_fix）にする
python scripts/resolve_issue.py <issue_id> --status wont_fix
```

## Claude Codeからの利用

Claude Codeと会話しながらイシューを確認できます。

**例1: イシュー一覧を確認**
```
本田: 今、実装すべきイシューは何がある？

Claude Code:
（Bash toolで python scripts/list_issues.py を実行）

現在のオープンイシューは3件あります：

1. [Priority: 12] JAL Executor Missing
   - 12回発生
   - JAL予約システムのExecutor実装が必要

2. [Priority: 7] Rakuten Selector Outdated
   - 7回発生
   - セレクタ更新が必要

3. [Priority: 2] Hotel.com Executor Missing
   - 2回発生
   - Hotel.com予約システムのExecutor実装が必要

最も優先度が高いのはJAL Executorの実装です（12回発生）。
```

**例2: イシュー詳細を確認**
```
本田: issue 1の詳細を教えて

Claude Code:
（Bash toolで python scripts/show_issue.py <uuid> を実行）

JAL Executor Missing イシューの詳細：

発生したリクエスト例:
- "羽田から福岡まで飛行機で行きたい"
- "羽田から札幌までJALで予約して"
- "成田からソウルまでJALで"

提案される解決策:
1. app/executors/jal_executor.py を作成
2. JAL公式サイトの予約フローを分析
3. search()とexecute()メソッドを実装
4. ExecutorRegistryに登録

推定作業量: Medium (2-3時間)
```

**例3: 実装後、イシューをクローズ**
```
本田: JAL Executorの実装が完了した。このイシューをクローズして

Claude Code:
（Bash toolで python scripts/resolve_issue.py <uuid> を実行）

Issue <uuid> を resolved にしました。
現在のオープンイシューは2件です。
```

## データベース構造

### `issues` テーブル

| カラム | 説明 |
|--------|------|
| id | UUID（主キー） |
| user_id | 発生したユーザー |
| issue_type | イシュータイプ (executor_missing等) |
| status | ステータス (open, in_progress, resolved, wont_fix) |
| priority | 優先度（発生回数） |
| service_type | サービスタイプ (airline, train等) |
| service_name | サービス名 (jal, ex_reservation等) |
| original_wish | 元のユーザーリクエスト |
| research_result | AI推論結果（JSON） |
| error_message | エラーメッセージ |
| error_details | エラー詳細（JSON） |
| suggested_solutions | 解決策（JSON） |
| created_at | 作成日時 |
| updated_at | 更新日時 |
| last_occurred_at | 最後に発生した日時 |
| resolved_at | 解決日時 |

### `issue_occurrences` テーブル

各イシューの発生履歴を記録。

| カラム | 説明 |
|--------|------|
| id | UUID（主キー） |
| issue_id | 関連するissue |
| user_id | 発生したユーザー |
| original_wish | ユーザーリクエスト |
| research_result | AI推論結果（JSON） |
| error_message | エラーメッセージ |
| occurred_at | 発生日時 |

## 将来の拡張

### 自動コーディングエージェント

将来的には、イシューを常時監視し、自動的にコード実装を行うエージェントを作成予定。

**想定フロー:**
1. イシュー監視エージェントが定期的にDBをチェック
2. 優先度が閾値を超えたイシューを検出
3. 自動的に実装プランを作成
4. コードを生成・テスト
5. プルリクエストを作成
6. レビュー後、イシューをクローズ

## まとめ

- ✅ ユーザーリクエストから自動的にイシューを検知
- ✅ 発生回数で優先度を自動計算
- ✅ 解決策を自動提案
- ✅ Claude Codeから簡単にアクセス可能
- ✅ 将来の自動コーディングエージェントに対応

実際のユーザーニーズに基づいて、効率的に開発の優先順位を決定できます。
