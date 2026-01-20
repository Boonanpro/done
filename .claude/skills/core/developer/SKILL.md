# 開発機能（Developer）Skill

## サービス概要
ダン自身のスキル・コードを操作する自己拡張機能。
ファイルの読み取り、構造理解、Git状態確認ができる。

**重要**: これはCoreスキルです。Domainsスキル（ex-reservation等）から呼び出さないでください。

## ツールの使い方

スキル名: `developer`

### 利用可能なアクション（Phase 1: 読み取り専用）

| アクション | 説明 |
|-----------|------|
| `read` | ファイルを読み取る |
| `list` | ファイル一覧を取得 |
| `structure` | ディレクトリ構造を取得 |
| `git_status` | Gitの状態を確認 |
| `git_diff` | 差分を表示 |
| `git_log` | コミット履歴を表示 |

### read（ファイル読み取り）

```
[TOOL: developer read]
action: read
path: .claude/skills/ex-reservation/SKILL.md
```

パラメータ:
- `path`: ファイルパス（必須、相対パスはプロジェクトルートから）

### list（ファイル一覧）

```
[TOOL: developer list]
action: list
path: app/executors
pattern: *.py
recursive: true
```

パラメータ:
- `path`: ディレクトリパス（任意、デフォルト: "."）
- `pattern`: globパターン（任意、デフォルト: "*"）
- `recursive`: サブディレクトリも検索（任意、デフォルト: false）

### structure（ディレクトリ構造）

```
[TOOL: developer structure]
action: structure
path: app
max_depth: 2
include_files: true
```

パラメータ:
- `path`: ルートディレクトリ（任意、デフォルト: "."）
- `max_depth`: 最大深度（任意、デフォルト: 3）
- `include_files`: ファイルも含める（任意、デフォルト: true）

### git_status（Git状態）

```
[TOOL: developer git_status]
action: git_status
```

パラメータ: なし

### git_diff（差分表示）

```
[TOOL: developer git_diff]
action: git_diff
staged: false
path: app/executors/developer
```

パラメータ:
- `staged`: ステージング済みの差分を表示（任意、デフォルト: false）
- `path`: 特定のパスの差分のみ（任意）
- `stat_only`: 統計情報のみ表示（任意、デフォルト: false）

### git_log（コミット履歴）

```
[TOOL: developer git_log]
action: git_log
count: 5
path: app/executors
```

パラメータ:
- `count`: 取得件数（任意、デフォルト: 10）
- `oneline`: 1行形式（任意、デフォルト: true）
- `path`: 特定のパスの履歴のみ（任意）

### 利用可能なアクション（ログ読み取り）

| アクション | 説明 |
|-----------|------|
| `read_logs` | エラーログを読み取る（自己診断用） |
| `list_logs` | ログファイル一覧を表示 |

### read_logs（エラーログ読み取り）

```
[TOOL: developer read_logs]
action: read_logs
source: ex_reservation
minutes: 30
limit: 20
```

パラメータ:
- `source`: ソースでフィルタ（任意、部分一致）
- `minutes`: 直近N分以内のエラーのみ（任意）
- `limit`: 取得件数（任意、デフォルト: 20）

### list_logs（ログファイル一覧）

```
[TOOL: developer list_logs]
action: list_logs
```

パラメータ: なし

### 利用可能なアクション（Phase 2: 変更機能）

| アクション | 説明 | 承認レベル |
|-----------|------|----------|
| `write` | ファイルを書き込む | パスによる |
| `delete` | ファイルを削除する | パスによる |
| `test` | テストを実行する | AUTO |
| `git_add` | ファイルをステージング | AUTO |
| `git_commit` | 変更をコミット | SIMPLE |
| `git_branch` | ブランチ操作 | SIMPLE |
| `approval_check` | 承認レベルを確認 | - |

### write（ファイル書き込み）

```
[TOOL: developer write]
action: write
path: tests/test_new_feature.py
content: |
  # テストコード
  def test_example():
      assert True
```

パラメータ:
- `path`: ファイルパス（必須）
- `content`: 書き込む内容（必須）

### delete（ファイル削除）

```
[TOOL: developer delete]
action: delete
path: tests/test_obsolete.py
```

パラメータ:
- `path`: ファイルパス（必須）

### test（テスト実行）

```
[TOOL: developer test]
action: test
paths: tests/test_developer_executor.py
timeout: 120
```

パラメータ:
- `paths`: テスト対象パス（任意、カンマ区切り）
- `pattern`: テストパターン（任意、-k オプション）
- `timeout`: タイムアウト秒数（任意、デフォルト: 120）

### git_add（ステージング）

```
[TOOL: developer git_add]
action: git_add
files: app/executors/developer/executor.py,tests/test_developer.py
```

パラメータ:
- `files`: ステージングするファイル（必須、カンマ区切り）

### git_commit（コミット）

```
[TOOL: developer git_commit]
action: git_commit
message: feat: add developer executor
files: app/executors/developer/executor.py
```

パラメータ:
- `message`: コミットメッセージ（必須）
- `files`: コミットするファイル（任意、省略時はステージング済み）
- `add_all`: 全変更をステージング（任意、デフォルト: false）

### git_branch（ブランチ操作）

```
[TOOL: developer git_branch]
action: git_branch
name: feature/new-skill
checkout: true
```

パラメータ:
- `name`: ブランチ名（任意、省略時は一覧表示）
- `checkout`: 作成後にチェックアウト（任意、デフォルト: false）
- `delete`: ブランチを削除（任意、デフォルト: false）

### approval_check（承認レベル確認）

```
[TOOL: developer approval_check]
action: approval_check
path: app/agent/v2/session.py
```

パラメータ:
- `path`: 確認するパス（必須）

## 承認レベル

| 変更対象 | レベル | 承認方法 |
|---------|-------|---------|
| `tests/*.py` (新規) | AUTO | 自動、ログのみ |
| `.claude/skills/domains/**` | SIMPLE | 1行確認 |
| `app/executors/*.py` | DETAILED | 差分表示 + 確認 |
| `app/agent/**`, `core/` | STRICT | 詳細説明 + 明示的承認 |

## セキュリティ制限

### アクセス禁止ファイル
- `.env` - 環境変数
- `credentials*` - 認証情報
- `secrets*` - シークレット
- `.git/config` - Git設定
- SSH鍵ファイル

### パス制限
- プロジェクトルート外へのアクセスは禁止
- 相対パスはプロジェクトルートからの相対

## 使用例

### スキル定義を読む
```
[TOOL: developer read]
action: read
path: .claude/skills/ex-reservation/SKILL.md
```

### プロジェクト構造を確認
```
[TOOL: developer structure]
action: structure
path: .
max_depth: 2
```

### 変更状態を確認
```
[TOOL: developer git_status]
action: git_status
```

### 特定ファイルの変更を確認
```
[TOOL: developer git_diff]
action: git_diff
path: app/executors/developer/executor.py
```

## 依存関係ルール（重要）

```
┌─────────────────────────────────────┐
│        app/agent/v2/                │  ← 上層：両者を管理
│   (session.py, runner.py, tools.py) │
└─────────────┬───────────────────────┘
              │ 呼び出し
    ┌─────────┴─────────┐
    ▼                   ▼
┌────────────┐    ┌────────────┐
│   Core/    │───▶│  Domains/  │  ← Core → Domains は OK
│ Developer  │    │ EX-Reserv  │
└────────────┘    └────────────┘
                       ✗
              Domains → Core は禁止
```

## ユーザーへの応答例

### ファイル読み取り成功時
```
.claude/skills/ex-reservation/SKILL.md を読み取りました。

# EX予約（新幹線）Skill
...（内容）...
```

### ディレクトリ構造表示時
```
プロジェクト構造:
└── app
    ├── agent
    │   └── v2
    ├── executors
    │   ├── developer
    │   └── ex_reservation
    └── services
```

### Git状態表示時
```
現在の状態:
- ブランチ: main
- 変更ファイル: 3件
  - modified: app/executors/developer/executor.py
  - untracked: tests/test_developer.py
```
