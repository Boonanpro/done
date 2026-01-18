# プロジェクト固有ルール

## バックエンド再起動ルール

コードを修正した後にバックエンドを再起動する際は、**必ず**以下のコマンドを実行すること：

```bash
# 自動クリーンアップスクリプト（推奨）
python scripts/cleanup_port_8000.py && cd "D:/done" && python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

### 手動で行う場合

1. **ポート確認**: `netstat -ano | findstr :8000 | findstr LISTENING`
2. **重複プロセス終了**: `taskkill //F //PID <PID>` で全て終了
3. **起動**: `cd "D:/done" && python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload`

**理由**: 複数のバックエンドプロセスが同時に動くと、古いコードが実行され続けてデバッグが困難になる。

### Hook設定（自動化）

`.claude/settings.local.json` に PreToolUse hook を設定済み。uvicornコマンド実行前に自動でポート8000をクリーンアップする。（Claude Code再起動後に有効になる場合がある）

## 開発環境

- バックエンド: FastAPI (port 8000)
- フロントエンド: Next.js (port 3000)
- データベース: Supabase

## 現在の実装計画

**docs/current/README.md** を参照。

v2アーキテクチャに基づいて開発中。旧計画書（phase*.md）は docs/archive/ に移動済み。

## Agent v2 アーキテクチャ

詳細: `docs/current/architecture_v2.md`

- ツール呼び出し: B方式（キーワード検出 `[TOOL: skill-name action]`）
- スキル定義: `.claude/skills/*/SKILL.md`
- 状態遷移: LLMが `[STATE: xxx]` で宣言
- メインロジック: `app/agent/v2/`
