# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **PLANのナレーション改善** - 自問形式で「なぜそのツールを選んだか」の根拠を表示
  - プロンプトに良い例・悪い例を追加
  - 関連ファイル: `app/agent/prompts.py`
- **実行履歴の構造化と記憶保持** - 実行結果を構造化して保持し、次の推論に渡す
  - `execution_history` - 成功/失敗両方を記録するリスト
  - `add_execution_record()` - 実行結果を記録するメソッド
  - `get_failed_tools()` / `get_execution_summary()` - 失敗情報を取得
  - PLANに戻る時に失敗したツール情報を渡し、同じ失敗を繰り返さないようにする
  - 関連ファイル: `app/agent/states.py`, `app/agent/state_machine.py`, `app/agent/prompts.py`
- **PLANプロンプトにweb_searchを追加** - LLMがTavily + Jina AI Readerを選択できるように
- **Critic再検索機能** - Criticが「根拠不足」を指摘した場合に自動でWeb再検索を実行
  - `_needs_additional_research()` - 再検索が必要かどうかをキーワードで判定
  - `_research_for_fix()` - Jina AI Reader + Tavilyで正確な情報を取得
  - `suggest_fix()` を拡張 - 必要に応じて再検索結果を根拠に提案を修正
  - 関連ファイル: `app/agent/critic.py`, `app/agent/state_machine.py`
- **Step 6: agent.pyへのStateMachine統合** - 新しい状態機械アーキテクチャをエージェントに統合
  - `process_with_state_machine()` - 状態機械ベースのメッセージ処理
  - `confirm_state_machine()` - 提案の承認
  - `revise_state_machine()` - 提案の修正
  - `get_state_machine_state()` - 状態取得
  - 新規APIエンドポイント:
    - `POST /api/v1/sm/message` - StateMachineでメッセージを処理
    - `POST /api/v1/sm/{session_id}/confirm` - 提案を承認
    - `POST /api/v1/sm/{session_id}/revise` - 提案を修正
    - `GET /api/v1/sm/{session_id}/state` - 状態を取得
  - 関連ファイル: `app/agent/agent.py`, `app/api/routes.py`, `tests/test_state_machine.py`
  
- **リアルタイムプロセス表示** - SSEストリーミングでAI思考プロセスを1つずつ表示
  - メッセージ送信直後は「考え中...」を表示、その後プロセスが1つずつ追加される
  - 各ステップ到着時に表示追加、完了時に✓マーク、実行中はスピナーアニメーション
  - AI返信完了後もプロセス表示は折りたたみ可能で保持
  - SSE（Server-Sent Events）でバックエンドからリアルタイムストリーミング
  - `POST /api/v1/chat/dan/messages/stream` エンドポイント追加
- **フロントエンド実装** - Done Chat UI（Next.js 16 + React 19）
  - ログイン/登録画面、チャット画面、サイドバー
  - バックエンドAPI連携（`lib/api-client.ts`）

### Fixed
- チャットメッセージの表示順を修正（古いメッセージが上、新しいメッセージが下）
- チャット画面のスクロールを修正（過去のメッセージを遡れるように）
- **APIクライアント不足メソッド追加** - 未定義だったAPIメソッドを追加
  - `api.proposals` - 提案一覧・詳細取得・応答（通知パネルで使用）
  - `api.invites` - 招待リンク作成（友達チャット画面で使用）
  - `api.rooms.getAiSettings` / `updateAiSettings` - AI設定取得・更新（友達チャット画面で使用）
  - `api.user.update` - ユーザー情報更新（設定画面で使用）
- サイドバーのハイドレーション問題を`useSyncExternalStore`で修正

### Added (チャットセッション機能)
- **バックエンドAPI** - セッション一覧・作成・切り替えAPI
  - `GET /api/v1/chat/dan/sessions` - セッション一覧取得
  - `POST /api/v1/chat/dan/sessions` - 新規セッション作成
  - `POST /api/v1/chat/dan/sessions/{id}/activate` - セッション切り替え
- **フロントエンド** - サイドバーにセッション履歴表示
  - 「新しい会話」ボタンで新規セッション作成
  - 過去のセッションをクリックで切り替え

### Performance (チャット最適化)
- **セッション切り替え高速化** - 3回のAPIコールを1回に統合
  - `POST /api/v1/chat/dan/sessions/{id}/switch` - セッション切り替え＋データ一括取得
  - N+1クエリ問題を解消（`get_dan_sessions`の最適化）
- **フロントエンドキャッシュ最適化** - invalidateQueriesからsetQueryDataへ変更

### Added (チャット履歴削除機能)
- **サイドバー** - チャット履歴の×ボタン削除機能
  - ホバー時に×ボタンを表示
  - アクティブなセッションも削除可能（1つ上/下に自動切り替え）
  - 最後のセッション削除時は新規セッションを自動作成

### Previously Added
- **ドキュメント更新ルール** - ADR/CHANGELOG更新タイミングを`.cursor/rules`に明記
  - Commits: `65a168d`, `4f441a7`
  - ADR作成トリガーの明確化（設計判断時に確認を促す）

## [1.3.0] - 2024-12-27

### Summary
本番運用に向けた基盤強化。タスクの永続化、スマートフォールバック、E2Eテスト基盤を追加。

### Added
- **タスクのDB永続化** - サーバー再起動後もタスクが保持される
  - Commits: `163bb92`
  - ADR: [ADR-001](docs/adr/001_task_persistence.md)

- **Smart Fallback** - タスク失敗時にLLMが距離・コスト考慮した代替案を提案
  - Commits: `69c5b9d`, `0ff8124`
  - ADR: [ADR-002](docs/adr/002_smart_fallback.md)

- **E2Eテスト基盤** - 実サービスを使った統合テスト環境
  - Commits: `f0df21c`
  - ADR: [ADR-003](docs/adr/003_e2e_test_separation.md)

- **revise_task再検索機能** - 訂正リクエスト時に再検索して最新結果で提案
  - Commits: `163bb92` (同コミット内)

### Changed
- バックエンドメッセージを英語に統一（国際化対応）
  - Commits: `58ed1bd`

- Playwright Windows互換性修正（専用スレッド方式）
  - Commits: `58ed1bd`

### Technical Details
- メモリキャッシュ + Supabase DBのハイブリッド方式
- `tests/`（Unit Tests）と `tests_e2e/`（E2E Tests）の分離
- `.env.test` によるテスト用DB分離

---

## [1.2.0] - 2024-12-26

### Added
- Phase 10: Voice Communication（音声通話）完了
- Phase 9: OTP Automation完了
- Phase 8: Payment Execution完了
- Phase 7: Invoice Management完了

---

## [1.1.0] - 2024-12-25

### Added
- Phase 6: Content Intelligence完了
- Phase 5: Message Detection完了
- Phase 4: Credential Management完了

---

## [1.0.0] - 2024-12-24

### Added
- Phase 1: Core Flow
- Phase 2: Done Chat
- Phase 3A: Smart Proposal
- Phase 3B: Execution Engine

---

[Unreleased]: https://github.com/your-repo/done/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/your-repo/done/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/your-repo/done/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/your-repo/done/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/your-repo/done/releases/tag/v1.0.0

