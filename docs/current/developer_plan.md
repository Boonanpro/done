# Core/Developer 実装計画

## 概要

ダンに自己拡張機能（Self-Healing）を持たせる。フロントUIから「座席表から隣が空いてる席を選べるようにして」のような指示で、ダンが自分自身のスキルを作成・編集・削除できるようにする。

---

## 技術スタック

| 機能 | 技術 | 理由 |
|------|------|------|
| Git操作 | subprocess + git CLI | シンプル、Windows対応、全機能利用可 |
| ファイル操作 | pathlib + aiofiles | Python標準、async対応 |
| テスト実行 | subprocess + pytest | 既存テスト基盤と統一 |
| **エラーログ追跡** | **Supabase + インメモリバッファ** | **既存DB基盤と統一、スケーラブル** |

---

## 設計原則

### 依存関係のルール（重要）

```
┌─────────────────────────────────────┐
│        app/agent/v2/                │  ← 上層：両者を管理
│   (session.py, runner.py, tools.py) │
└─────────────┬───────────────────────┘
              │ 呼び出し
    ┌─────────┴─────────┐
    ▼                   ▼
┌────────────┐    ┌────────────┐
│   Core/    │    │  Domains/  │
│ Developer  │───▶│ EX-Reserv  │  ← Core → Domains は OK
└────────────┘    └────────────┘
                       ✗
              Domains → Core は禁止
```

**理由**: 業務スキルが開発スキルに依存すると、開発ツール更新時に全業務スキルが動かなくなる「全滅」リスクがある。

---

## ディレクトリ構造

```
.claude/skills/
├── core/
│   └── developer/
│       ├── SKILL.md                    # [新規] developerスキル定義
│       └── templates/
│           ├── skill_template.md       # [新規] 新規スキル用テンプレート
│           └── executor_template.py    # [新規] Executor用テンプレート
└── domains/
    └── ex-reservation/
        └── SKILL.md                    # [移動] 既存スキル

app/services/
└── logging/                            # [新規] エラーログ追跡（共通基盤）
    ├── __init__.py
    └── error_tracker.py                # ErrorTracker, capture_error等

app/executors/
└── developer/
    ├── __init__.py                     # [新規]
    ├── executor.py                     # [新規] DeveloperExecutor
    ├── file_tools.py                   # [新規] ファイル操作
    ├── git_tools.py                    # [新規] Git操作
    ├── test_runner.py                  # [新規] テスト実行
    └── safeguards.py                   # [新規] 承認・ロールバック・リロード

app/agent/v2/
├── session.py                          # [変更] DEVELOP状態追加
├── tools.py                            # [変更] developer対応
└── prompts/states/
    ├── intake.md                       # [変更] 自己修正判別追加
    └── develop.md                      # [新規] DEVELOP状態用

supabase/migrations/
└── 013_error_logs.sql                  # [新規] エラーログテーブル

tests/
└── test_developer_executor.py          # [新規]
```

---

## 実装フェーズ

### Phase 1: 読み取り専用基盤
**目標**: ファイル読み取り、構造理解、Git状態確認

| 作成ファイル | 内容 |
|-------------|------|
| `app/executors/developer/file_tools.py` | `read_file()`, `list_files()`, `get_structure()` |
| `app/executors/developer/git_tools.py` | `git_status()`, `git_diff()`, `git_log()` |
| `app/executors/developer/executor.py` | BaseExecutor継承、searchで構造理解 |
| `.claude/skills/core/developer/SKILL.md` | read, list, git_status, git_diffアクション |
| `tests/test_developer_executor.py` | 基本テスト |

### Phase 1.5: エラーログ追跡（実装済み）
**目標**: ダンが自身の実行エラーを追跡・診断できるようにする

| 作成ファイル | 内容 |
|-------------|------|
| `app/services/logging/__init__.py` | モジュールエクスポート |
| `app/services/logging/error_tracker.py` | `ErrorTracker`, `capture_error()`, `get_recent_errors()` |
| `supabase/migrations/013_error_logs.sql` | `error_logs` テーブル定義 |

#### アーキテクチャ

```
エラー発生（全Executor）
    ↓
capture_error() 呼び出し
    ↓
┌─────────────────────────────────────┐
│         ErrorTracker                 │
├─────────────────────────────────────┤
│  インメモリバッファ (deque, 100件)  │  ← 高速アクセス
│           ↓                          │
│  Supabase error_logs テーブル        │  ← 永続化
│           ↓                          │
│  ファイル (logs/dan_errors.log)      │  ← フォールバック
└─────────────────────────────────────┘
    ↓
ダンが DeveloperExecutor で読み取り:
  - [TOOL: developer read_logs]
  - [TOOL: developer read_logs use_db: true]  ← DB検索
```

#### 主要API

| 関数 | 用途 |
|------|------|
| `capture_error(source, message, traceback, level, session_id, user_id, context)` | エラーをキャプチャ |
| `get_recent_errors(limit, source_filter, session_id, minutes)` | インメモリから取得 |
| `get_error_tracker().query_db(...)` | DBから検索 |
| `format_errors_for_diagnosis(errors)` | LLM読みやすい形式に整形 |

#### DBスキーマ

```sql
CREATE TABLE error_logs (
    id UUID PRIMARY KEY,
    session_id TEXT,           -- エージェントセッションID
    user_id UUID,              -- ユーザーID
    source TEXT NOT NULL,      -- "ex_reservation.search"
    level TEXT DEFAULT 'ERROR',
    message TEXT NOT NULL,
    traceback TEXT,
    context JSONB,             -- パラメータ等
    created_at TIMESTAMPTZ
);
```

---

### Phase 2: 変更機能 + テストゲート
**目標**: ファイル書き込み、テスト実行、自動ロールバック

| 作成/変更ファイル | 内容 |
|------------------|------|
| `file_tools.py` 拡張 | `write_file()`, `delete_file()` |
| `git_tools.py` 拡張 | `git_branch()`, `git_commit()`, `git_revert()` |
| `app/executors/developer/test_runner.py` | `run_tests()`, `run_all_tests()` |
| `app/executors/developer/safeguards.py` | テストゲート、自動ロールバック、**モジュール再読み込み** |
| `SKILL.md` 更新 | write, delete, test, commitアクション追加 |

#### 追加機能: モジュール再読み込み（フィードバック①）

`safeguards.py` に以下を実装:
```python
async def reload_module(module_path: str) -> dict:
    """
    コード変更後にPythonモジュールを再読み込み。
    - 変更されたexecutorやtools.pyを即座に反映
    - importlib.reload()を使用
    - 失敗時はプロセス再起動を推奨するメッセージを返す
    """
```

### Phase 3: 状態機械統合 + 承認フロー
**目標**: DEVELOP状態、承認レベル判定

| 作成/変更ファイル | 内容 |
|------------------|------|
| `app/agent/v2/session.py` | `State.DEVELOP` 追加 |
| `app/agent/v2/prompts/states/develop.md` | DEVELOP状態の指示、**git diff表示ルール** |
| `app/agent/v2/prompts/states/intake.md` | 自己修正判別ロジック追加 |
| `app/agent/v2/tools.py` | developer skill対応 |
| `safeguards.py` 拡張 | 承認レベル判定(AUTO/SIMPLE/DETAILED/STRICT) |

#### 追加機能: 差分表示（フィードバック③）

`develop.md` に以下のルールを明記:
```markdown
## 承認時の報告ルール

DETAILEDレベル以上の変更を行った際は、必ず以下の形式で報告すること：

### 変更内容
[変更の概要を1-2文で説明]

### 差分
\`\`\`diff
[git diff の出力をそのまま表示]
\`\`\`

### 確認をお願いします
この変更を適用してよろしいですか？
```

### Phase 4: 自己改善ループ（未着手）

**Phase 1-3との違い**:
- Phase 1-3: ユーザーが指示 → ダンが実行（道具）
- Phase 4: ダンが自律的にエラー検知→修正→完了まで回す（自動運転）

**実装予定**:
- エラー発生時に自動でIssue作成
- ダンが自律的に原因分析・修正案作成
- テスト実行・検証
- 成功したらIssueクローズ
- Claude for Desktop実演対応

---

## 実装状況メモ

**Phase 1-3: 実装済み（実ケース未テスト）**

コードは完成しているが、以下の実ケースでの動作確認は未実施:
- 実際のエラー発生時にログが正しくキャプチャされるか
- `[TOOL: developer read_logs]` で正しく読み取れるか
- ファイル変更→テスト→コミットのフローが動くか
- 承認レベル判定が正しく機能するか

初回の実ケーステストで問題が見つかる可能性あり。

---

## 承認レベル

| 変更対象 | レベル | 承認方法 |
|---------|-------|---------|
| `tests/*.py` (新規) | AUTO | 自動、ログのみ |
| `.claude/skills/domains/**` | SIMPLE | 1行確認 |
| `app/executors/*.py` | DETAILED | **差分表示** + 確認 |
| `app/agent/**`, `core/` | STRICT | 詳細説明 + 明示的承認 |

---

## テストゲートフロー

```
変更要求
    ↓
変更前テスト実行 → 失敗 → 中止、原因報告
    ↓ 成功
ブランチ作成
    ↓
変更適用
    ↓
変更後テスト実行 → 失敗 → 自動revert、原因報告
    ↓ 成功
コミット
    ↓
モジュール再読み込み（必要な場合）
    ↓
完了報告
```

---

## テンプレート設計

### skill_template.md（フィードバック②反映）

新規スキル作成時のテンプレートに以下の原則を含める:

```markdown
## 柔軟性の原則

ツールが未実装でも、既存ツールを組み合わせて代用できないか検討すること。
例: 「予約一覧を見る」機能がなくても「キャンセル」機能の途中で一覧が見える場合、
そのフローを転用して情報を取得できる。

新しいツールを追加する前に:
1. 既存ツールで代用できないか検討
2. 既存ツールの組み合わせで実現できないか検討
3. どうしても必要な場合のみ新規追加
```

---

## 検証方法

1. **単体テスト**: `pytest tests/test_developer_executor.py -v`
2. **統合テスト**: 一時ブランチで変更→テスト→コミット→revertフロー確認
3. **E2E手動テスト**:
   - 「EX予約のSKILL.mdを読んで」→ 読み取り確認
   - 「テストファイルを追加して」→ AUTO承認確認
   - 「executorに機能追加して」→ DETAILED承認確認 + **差分表示確認**
   - 意図的に壊れる変更 → 自動ロールバック確認
   - executor変更後 → **モジュール再読み込み確認**

---

## 変更ファイル一覧

### 新規作成（11ファイル）
- `.claude/skills/core/developer/SKILL.md`
- `.claude/skills/core/developer/templates/skill_template.md`
- `.claude/skills/core/developer/templates/executor_template.py`
- `app/executors/developer/__init__.py`
- `app/executors/developer/executor.py`
- `app/executors/developer/file_tools.py`
- `app/executors/developer/git_tools.py`
- `app/executors/developer/test_runner.py`
- `app/executors/developer/safeguards.py`
- `app/agent/v2/prompts/states/develop.md`
- `tests/test_developer_executor.py`

### 変更（4ファイル）
- `app/agent/v2/session.py` - DEVELOP状態追加
- `app/agent/v2/tools.py` - developer skill対応
- `app/agent/v2/prompts/states/intake.md` - 自己修正判別追加
- `app/executors/registry.py` - DeveloperExecutor登録

---

## 実装順序（推奨）

1. Phase 1 全体 → 動作確認
2. Phase 2 全体 → テストゲート確認
3. Phase 3 全体 → E2E確認

---

## 更新履歴

- 2025-01-19: 初版作成
- 2025-01-19: フィードバック反映
  - ① モジュール再読み込み機能を safeguards.py に追加
  - ② skill_template.md に「柔軟性の原則」を追加
  - ③ develop.md に差分表示ルールを追加
  - 依存関係ルール（Domains → Core 禁止）を明記
- 2026-01-19: エラーログ追跡機能のリファクタリング
  - `app/executors/developer/log_reader.py` → `app/services/logging/error_tracker.py` に移動
  - Supabase永続化を追加（`error_logs` テーブル）
  - セッションID・コンテキスト付きでエラーを保存可能に
  - BaseExecutorからの呼び出しを正式なimportに変更（ImportError回避を廃止）
