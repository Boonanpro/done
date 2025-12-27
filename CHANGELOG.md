# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

