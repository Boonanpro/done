# AI Secretary System / AI秘書システム

「○○したい」という願望に対して提案・実行してくれるAI秘書システムです。

## 開発状況

### ✅ 動作確認済み（2024年12月18日）

| 機能 | API | 状態 |
|-----|-----|------|
| タスク一覧を見る | `GET /api/v1/tasks` | ✅ 動作確認済み |
| お願いを送る | `POST /api/v1/wish` | ✅ 動作確認済み |
| お願いの状況を確認 | `GET /api/v1/task/{id}` | ✅ 動作確認済み |
| お願いを実行する | `POST /api/v1/task/{id}/confirm` | ✅ 動作確認済み |
| ヘルスチェック | `GET /` | ✅ 動作確認済み |
| LINE Webhook | `POST /webhook/line` | ⏸️ LINE設定後にテスト可能 |

### 🔧 現在の状態

- **承認フローの土台**: 完成 ✅
  - 「買いたい」「払いたい」などのリクエストは自動実行されず、ユーザー承認を待つ
- **実際の操作機能**: 未接続 🔧
  - Webサイト操作（Playwright）: コードはあるが未接続
  - メール送受信（Gmail API）: 設定が必要
  - LINE送信（LINE API）: 設定が必要
  - 支払い処理: 未実装

### ⚠️ 注意事項

- タスクはサーバーのメモリに保存されるため、サーバー再起動で消えます
- 本番運用にはデータベース（Supabase）への保存実装が必要です

## 主な機能（目標）

- **メール・LINE仲介**: ユーザーに代わってメッセージの送受信を行います
- **物品購入**: ECサイトでの商品購入をサポートします
- **サービス・請求書支払い**: 支払い処理を自動化します
- **情報リサーチ**: Web検索による情報収集を行います

## 技術スタック

- **バックエンド**: Python 3.11+, FastAPI
- **AIエージェント**: LangGraph, Claude API (Anthropic)
- **ブラウザ自動化**: Playwright
- **データベース**: Supabase (PostgreSQL)
- **タスクキュー**: Celery + Redis
- **メール連携**: Gmail API
- **LINE連携**: LINE Messaging API

## セットアップ

### 1. 環境構築

```bash
# Python仮想環境を作成
python -m venv venv

# 仮想環境を有効化
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 依存関係をインストール
pip install -r requirements.txt

# Playwrightブラウザをインストール
playwright install chromium
```

### 2. 環境変数の設定

`.env` ファイルをプロジェクトルートに作成し、以下の変数を設定してください：

```env
# Application
APP_ENV=development
APP_SECRET_KEY=your-secret-key-here-change-in-production

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-supabase-service-role-key

# Anthropic (Claude)
ANTHROPIC_API_KEY=your-anthropic-api-key

# Redis (for Celery)
REDIS_URL=redis://localhost:6379/0

# Gmail API
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# LINE Messaging API
LINE_CHANNEL_ACCESS_TOKEN=your-line-channel-access-token
LINE_CHANNEL_SECRET=your-line-channel-secret

# Encryption Key (32 bytes)
ENCRYPTION_KEY=your-32-byte-encryption-key-here
```

### 3. Supabaseスキーマの適用

Supabaseダッシュボードの SQL Editor で `supabase/migrations/001_initial_schema.sql` を実行してください。

### 4. Gmail API設定

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成
2. Gmail API を有効化
3. OAuth 2.0 クライアントIDを作成
4. 認証情報JSONを `~/.ai_secretary/gmail_credentials.json` に保存

### 5. LINE Messaging API設定

1. [LINE Developers Console](https://developers.line.biz/) でチャネルを作成
2. Messaging API設定からアクセストークンとチャネルシークレットを取得
3. Webhook URLを `https://your-domain.com/webhook/line` に設定

## 起動方法

### 開発環境

```bash
# Redisを起動（Docker）
docker run -d -p 6379:6379 redis:alpine

# FastAPIサーバーを起動
python main.py

# 別のターミナルでCeleryワーカーを起動
celery -A app.tasks.celery_app worker --loglevel=info --pool=solo
```

### APIエンドポイント

| エンドポイント | メソッド | 説明 |
|--------------|--------|------|
| `/` | GET | ヘルスチェック |
| `/api/v1/wish` | POST | 願望を処理 |
| `/api/v1/task/{id}` | GET | タスク状態を取得 |　
| `/api/v1/task/{id}/confirm` | POST | タスクを実行 |
| `/api/v1/tasks` | GET | タスク一覧を取得 |
| `/webhook/line` | POST | LINE Webhook |

### 使用例

```bash
# 願望を送信 (bash/curl)
curl -X POST http://localhost:8000/api/v1/wish \
  -H "Content-Type: application/json" \
  -d '{"wish": "Check the weather forecast"}'
```

```powershell
# 願望を送信 (PowerShell)
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/wish" -Method POST -ContentType "application/json" -Body '{"wish": "Check the weather forecast"}'
```

```json
// レスポンス例
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Processing your request.",
  "proposed_actions": ["Search web for weather forecast"],
  "requires_confirmation": false
}
```

## プロジェクト構造

```
D:\Doneダン\
├── main.py                 # エントリーポイント
├── requirements.txt        # 依存関係
├── README.md              # このファイル
├── app/
│   ├── __init__.py
│   ├── config.py          # 設定
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py      # APIルート
│   │   └── line_webhook.py # LINE Webhook
│   ├── agent/
│   │   ├── __init__.py
│   │   └── agent.py       # AIエージェント（LangGraph）
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py     # Pydanticスキーマ
│   ├── services/
│   │   ├── __init__.py
│   │   ├── encryption.py  # 暗号化サービス
│   │   └── supabase_client.py # DB操作
│   ├── tasks/
│   │   ├── __init__.py
│   │   ├── celery_app.py  # Celery設定
│   │   └── task_handlers.py # タスクハンドラー
│   └── tools/
│       ├── __init__.py
│       ├── browser.py     # Playwright操作
│       ├── email_tool.py  # Gmail操作
│       ├── line_tool.py   # LINE操作
│       └── search.py      # Web検索
└── supabase/
    └── migrations/
        └── 001_initial_schema.sql # DBスキーマ
```

## セキュリティ注意事項

- **認証情報の暗号化**: クレジットカード情報やパスワードはAES-256で暗号化して保存
- **二段階承認**: 高額決済や重要な操作は実行前にユーザー確認を実施
- **監査ログ**: 全ての自動操作をログに記録
- **LINE個人アカウント**: 個人アカウントの自動操作はLINE利用規約に抵触する可能性があります
- **銀行サイト**: 金融機関によっては自動操作が禁止されています

## ライセンス

MIT License

