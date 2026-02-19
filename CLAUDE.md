# プロジェクト固有ルール

## ⚠️ 最重要ルール: バックエンド起動 ⚠️

**バックエンド起動は以下のコマンドのみ使用可能:**

```bash
python scripts/start_backend.py
```

**これ以外の方法でuvicornを起動することは禁止。**

### 禁止事項

❌ `python -m uvicorn ...` （直接起動）
❌ `cd "D:/done" && python -m uvicorn ...` （直接起動）
❌ `cleanup_port_8000.py && uvicorn ...` （古い方法）
❌ uvicornを含む任意のコマンド

### なぜ start_backend.py だけを使うのか

1. wmicでuvicornプロセスを確実に検出・終了
2. ポートが空くまで待機
3. その後uvicornを起動

netstatのPIDは信頼できない（実際のPIDと一致しないことがある）。
hookは完了を待たない可能性がある。
だから起動スクリプトで全てを制御する。

### 手動で行う場合

1. **ポート確認**: `netstat -ano | findstr :8000 | findstr LISTENING`
2. **重複プロセス終了**: `taskkill //F //PID <PID>` で全て終了
3. **起動**: `cd "D:/done" && python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload`

**理由**: 複数のバックエンドプロセスが同時に動くと、古いコードが実行され続けてデバッグが困難になる。

### Hook設定（自動化）

`.claude/settings.local.json` に PreToolUse hook を設定済み。uvicornコマンド実行前に自動でポート8000をクリーンアップする。（Claude Code再起動後に有効になる場合がある）

## ⚠️ リモート開発（Claude App コードタブ）のルール ⚠️

Claude Appの「コード」タブはリモートサンドボックスで動作するため、以下の制約がある：

- **自宅PCのプロセス（uvicorn, Next.js）は操作できない**
- **サーバーの再起動は不可能**（「再起動しました」と言わないこと）
- コード変更 → git push → 自宅PCの `auto_deploy.py` が自動検知・反映する

### 必須ルール

1. **ブランチを作らず、mainに直接pushすること**
   - ❌ `git checkout -b claude/xxx` → ブランチ作成は禁止
   - ✅ `git add ... && git commit && git push origin main`
2. **「再起動しました」「反映しました」と言わないこと**
   - 自宅PCの `auto_deploy.py` が30秒以内にpullして自動反映する
   - 「mainにpushしました。約30秒で自動反映されます」と伝えること
3. **DBマイグレーションはSQLファイル作成のみ**
   - 実際の適用は自宅PCから手動で行う

## 開発環境

- バックエンド: FastAPI (port 8000)
- フロントエンド: Next.js (port 3000)
- データベース: Supabase
- 自動デプロイ: `python scripts/auto_deploy.py` （常駐スクリプト）

## 現在の実装計画

**docs/current/README.md** を参照。

v2アーキテクチャに基づいて開発中。旧計画書（phase*.md）は docs/archive/ に移動済み。

## Agent v2 アーキテクチャ

詳細: `docs/current/architecture_v2.md`

- ツール呼び出し: B方式（キーワード検出 `[TOOL: skill-name action]`）
- スキル定義: `.claude/skills/*/SKILL.md`
- 状態遷移: LLMが `[STATE: xxx]` で宣言
- メインロジック: `app/agent/v2/`

## スキル開発ルール

### 1. ブラウザ自動化にはセレクタ調査が必須

Playwright等でブラウザ操作するスキルを新規作成・修正する場合：

1. **実装前に実際のサイトでセレクタを調査する**
2. 調査スクリプトを作成して実行し、HTMLを取得
3. 取得したHTMLから正確なセレクタを特定
4. 推測やドキュメントだけに基づいてセレクタを書かない

**理由**: サイトの実際のHTML構造は推測と異なることが多く、動作しないコードを量産してしまう。

### 2. ツール作成後は必ず統合を確認

新しいツールやモジュールを作成したら、以下を確認：

| 確認項目 | 内容 |
|---------|------|
| SKILL.md | ダンが機能の存在を認識できるか |
| executor.py | パラメータが処理されるか |
| actions/*.md | 詳細ドキュメントがあるか |

**ツールを作っただけでは使えない。SKILL.mdに記載しないとダンは機能を知らない。**
