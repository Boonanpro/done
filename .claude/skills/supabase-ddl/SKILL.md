---
name: supabase-ddl
description: Supabase の DDL (CREATE TABLE / ALTER TABLE 等) を Management API 経由で自動実行する。マイグレーションファイルをユーザーにコピペさせずに適用したい時に使う。
---

# supabase-ddl スキル

Supabase Management API を使って DDL を実行する。ブラウザ操作も Playwright も不要。

## いつ使うか

- `supabase/migrations/NNN_xxx.sql` を新規作成したとき
- テーブル定義を変更するとき
- PostgREST では不可能な DDL 操作全般

## 前提

`.env` に `SUPABASE_ACCESS_TOKEN=sbp_...` が設定されていること（Personal Access Token）。未設定の場合はユーザーに `https://supabase.com/dashboard/account/tokens` で発行してもらう。

## 使い方

### A. create_feature 経由（推奨）

`create_feature` は migration ファイルを生成した直後に自動で `apply_migration` を呼ぶ。PAT が設定されていれば何もしなくていい。

### B. 既存の migration を適用する

```python
from app.tools.supabase_ddl import apply_migration

result = apply_migration("045_aix_dashboard.sql")
```

### C. 任意 SQL の実行

```python
from app.tools.supabase_ddl import apply_sql

apply_sql("ALTER TABLE inquiries ADD COLUMN priority INT DEFAULT 0;")
```

### D. CLI から

```bash
python -m app.tools.supabase_ddl 045_aix_dashboard.sql
```

## エラー時の対応

| エラー | 原因 | 対処 |
|---|---|---|
| `SUPABASE_ACCESS_TOKEN が .env に未設定` | PAT 未発行 | ユーザーに PAT 発行を依頼 |
| `HTTP 401` | PAT が無効/期限切れ | 再発行して .env 更新 |
| `HTTP 403` | プロジェクトへの権限不足 | PAT 発行時の組織を確認 |
| `HTTP 400: syntax error` | SQL エラー | マイグレーションファイル修正 |

## 落とし穴

- **トランザクション**: Management API は 1 リクエスト = 1 トランザクション。複数 DDL を原子的に走らせたければ 1 ファイルにまとめる
- **所要時間**: 大きなテーブルへの ALTER は数十秒かかることがある。`apply_sql` のタイムアウトは 120 秒
- **Idempotency**: `CREATE TABLE IF NOT EXISTS` `CREATE POLICY IF NOT EXISTS` を推奨。失敗時に再適用しやすい
