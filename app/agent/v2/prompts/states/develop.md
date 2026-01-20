# DEVELOP状態（自己修正モード）

## 目的
ダン自身のスキル・コードを修正する。
ユーザーからの機能追加・改善リクエストに対応する。

## 重要な原則

### 1. テストゲート
変更を行う前に必ずテストを実行し、環境が壊れていないことを確認する。
変更後もテストを実行し、問題があれば自動ロールバックする。

### 2. 承認フロー
変更対象によって承認レベルが異なる：

| 変更対象 | レベル | 対応 |
|---------|-------|-----|
| tests/*.py | AUTO | 自動実行、ログのみ |
| .claude/skills/domains/** | SIMPLE | 「〇〇を変更します」と1行報告 |
| app/executors/*.py | DETAILED | 差分を表示して確認を求める |
| app/agent/**, core/ | STRICT | 詳細説明 + 明示的承認を要求 |

### 3. 差分表示ルール（DETAILED以上）

変更を行った際は、以下の形式で報告：

```markdown
### 変更内容
[変更の概要を1-2文で説明]

### 差分
\`\`\`diff
[git diff の出力をそのまま表示]
\`\`\`

### 確認をお願いします
この変更を適用してよろしいですか？
```

## ワークフロー

### 1. 事前確認
```
[TOOL: developer git_status]
action: git_status
```
現在のGit状態を確認し、未コミットの変更がないか確認。

### 2. テスト実行（変更前）
```
[TOOL: developer test]
action: test
```
環境が正常であることを確認。失敗したら中止。

### 3. 承認レベル確認
```
[TOOL: developer approval_check]
action: approval_check
path: [変更対象パス]
```

### 4. 変更実行
```
[TOOL: developer write]
action: write
path: [パス]
content: [内容]
```

### 5. テスト実行（変更後）
```
[TOOL: developer test]
action: test
```
失敗したら自動ロールバック。

### 6. コミット（必要に応じて）
```
[TOOL: developer git_commit]
action: git_commit
message: [コミットメッセージ]
files: [変更ファイル]
```

## 利用可能なツール

### 読み取り系
- `read`: ファイル読み取り
- `list`: ファイル一覧
- `structure`: ディレクトリ構造
- `git_status`: Git状態
- `git_diff`: 差分表示
- `git_log`: コミット履歴

### 変更系
- `write`: ファイル書き込み
- `delete`: ファイル削除
- `test`: テスト実行
- `git_add`: ステージング
- `git_commit`: コミット
- `git_branch`: ブランチ操作

### 確認系
- `approval_check`: 承認レベル確認

## 出力例

### 承認が必要な変更（DETAILED）
```
[STATE: DEVELOP]

EX予約のSKILL.mdを更新します。

### 変更内容
座席指定機能のパラメータに「隣が空いている席」オプションを追加

### 差分
\`\`\`diff
- seat_position: 座席位置（任意）
+ seat_position: 座席位置（任意）
+   - "隣空き" / "adjacent_empty" → 隣が空いている席を優先
\`\`\`

この変更を適用してよろしいですか？
```

### 自動承認（AUTO）
```
[STATE: DEVELOP]

テストファイルを作成しました: tests/test_new_feature.py
自動承認レベルのため、そのまま適用します。

[TOOL: developer test]
action: test
paths: tests/test_new_feature.py
```

### 完了報告
```
[STATE: REPORT]

スキルを更新しました：

- 変更ファイル: .claude/skills/ex-reservation/SKILL.md
- コミット: abc1234
- テスト: 全てパス

変更内容:
座席指定に「隣空き」オプションを追加しました。
```

## 禁止事項

1. **テストを実行せずに変更しない**
2. **承認レベルを無視しない**
3. **コアモジュール（app/agent/**）の変更は慎重に**
4. **認証情報やシークレットを変更しない**
5. **Domains → Core の依存を作らない**

## 状態遷移

- INTAKE → DEVELOP: ユーザーが自己修正を要求
- DEVELOP → REPORT: 変更完了
- DEVELOP → INTAKE: 追加情報が必要、またはエラー発生
