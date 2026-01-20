# 現在の実装計画

## 概要

現在は **v2アーキテクチャ** に基づいて開発を進めている。

詳細: [architecture_v2.md](./architecture_v2.md)

## v2アーキテクチャの設計思想

1. **会話の継続性** - Messages配列を維持し、LLMが文脈を理解
2. **Progressive Disclosure** - 状態ごとに必要な指示だけを読み込み
3. **LLMに判断を委ねる** - 状態遷移はLLMが宣言、コードが追従

## ファイル構造

```
app/agent/v2/           # メインロジック
├── session.py          # 会話セッション管理
├── runner.py           # メインループ
├── tools.py            # ツール実行（スキルへの橋渡し）
└── prompts/
    ├── system.md       # システムプロンプト（ダンの人格）
    └── states/         # 状態ごとの指示
        ├── intake.md
        ├── plan.md
        └── ...

.claude/skills/         # スキル定義
├── ex-reservation/
│   └── SKILL.md
└── (他サービス)/
    └── SKILL.md
```

## 移行計画の進捗

| Phase | 内容 | 状態 |
|-------|------|------|
| Phase 1 | 基盤（session.py, runner.py） | ✅ 完了 |
| Phase 2 | プロンプト（system.md, states/*.md） | ✅ 完了 |
| Phase 3 | ツール連携（Executorへの橋渡し） | ✅ 完了 |
| Phase 4 | 統合（API更新、テスト） | ✅ 完了 |

## スキル定義の進捗

| スキル | SKILL.md | Executor | 状態 |
|--------|----------|----------|------|
| ex-reservation | ✅ | ✅ | 動作中 |
| **developer** | ✅ | ✅ | **実装済み（実ケース未テスト）** |
| amazon | ❌ | ✅ | SKILL.md未作成 |
| highway-bus | ❌ | ✅ | SKILL.md未作成 |
| bank-transfer | ❌ | ✅ | SKILL.md未作成 |
| rakuten | ❌ | ✅ | SKILL.md未作成 |

## Self-Healing機能の進捗

詳細: [developer_plan.md](./developer_plan.md)

| Phase | 内容 | 状態 | 備考 |
|-------|------|------|------|
| Phase 1 | 読み取り専用（read, list, git操作） | ✅ 完了 | |
| Phase 1.5 | エラーログ追跡（Supabase永続化） | ✅ 完了 | |
| Phase 2 | 変更機能（write, delete, test, commit） | ✅ 完了 | |
| Phase 3 | 状態機械統合（DEVELOP状態、承認レベル） | ✅ 完了 | |
| Phase 4 | 自己改善ループ（自律的なエラー検知→修正） | ❌ 未着手 | IssueTracker連携等 |

**注意**: Phase 1-3は実装済みだが、実際のユースケースでの動作確認は未実施。

## 次のステップ

1. **DeveloperExecutorの実ケーステスト** - 実際に使って動作確認
2. **他サービスのSKILL.md作成** - Amazon、高速バス、銀行振込など
3. **Phase 4: 自己改善ループ** - 自律的なエラー検知→Issue作成→修正→クローズ
4. **agent-browser検討** - コンテキスト削減のため

## 将来の設計方針

### スキルの自己拡張（Self-Healing）
最重要。ダン自身のコードやSKILL.mdを書き換えるスキルを持たせる。
- 最初は最小限のSKILL.md（種）だけ用意
- 実行しながらダン自身にマニュアル（SKILL.md）を完成させていく
- エラーや新しいパターンを学習してスキルを自己改善

### ツール呼び出し方式
**B方式（キーワード検出）** を採用。
- LLMが `[TOOL: skill-name action]` と宣言
- コードが検出してExecutorを呼び出し
