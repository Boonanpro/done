# Architecture Decision Records (ADR)

このディレクトリには、プロジェクトの重要な設計判断を記録したドキュメントが含まれています。

## ADRとは

ADR（Architecture Decision Record）は「なぜそう決めたか」を記録するドキュメントです。
コミット履歴は「何をしたか」を示しますが、「なぜ」「他に何を検討したか」は分かりません。
ADRはその背景と理由を将来の開発者（または自分）のために記録します。

## 相互参照

```
コミット ←→ ADR ←→ CHANGELOG
```

- **コミット**: `163bb92` のようなハッシュ
- **ADR**: このディレクトリのファイル
- **CHANGELOG**: [CHANGELOG.md](../../CHANGELOG.md)

## ADR一覧

| # | タイトル | ステータス | 日付 | 関連コミット |
|---|---------|----------|------|-------------|
| [001](001_task_persistence.md) | タスクをSupabase DBに永続化 | 採用 | 2024-12-27 | `163bb92` |
| [002](002_smart_fallback.md) | LLMを使ったスマートフォールバック | 採用 | 2024-12-27 | `69c5b9d` |
| [003](003_e2e_test_separation.md) | E2Eテストの分離とテスト用DB | 採用 | 2024-12-27 | `f0df21c` |

## 新しいADRの作成

重要な設計判断をした場合は、以下のテンプレートでADRを作成してください：

```markdown
# ADR-XXX: タイトル

## ステータス
提案 / 採用 / 廃止 / 置換

## 関連
- **Commits**: `xxxxxxx`
- **CHANGELOG**: [vX.X.X](../../CHANGELOG.md#xxx---yyyy-mm-dd)

## 背景・問題
（なぜこの決定が必要だったか）

## 決定
（何を決定したか）

## 検討した代替案
（他に何を検討したか、なぜ不採用か）

## 結果
（この決定の結果・効果）
```

## コミットメッセージにADRを参照

今後のコミットでは、関連するADRがあれば参照してください：

```
feat: Add new feature X

ADR: docs/adr/004_feature_x.md
```

