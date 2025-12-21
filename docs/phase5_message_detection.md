# Phase 5: Message Detection（メッセージ検知）

## 概要

**メール**と**Doneチャット**の両方でメッセージ受信を検知し、AIが内容を解析して自動処理できる基盤を構築する。

### ユースケース例

```
1. ユーザーがDoneチャットでメッセージを送信
       ↓
   AIが内容を解析（請求書、OTP、通知等）
       ↓
   必要に応じて自動アクションを実行

2. Gmail に請求書メールが届く
       ↓
   システムが検知し、添付PDF/画像を取得
       ↓
   Phase 6（Content Intelligence）で解析
       ↓
   Phase 7（Invoice Management）で請求書処理
```

---

## サブフェーズ構成

| Sub | 機能 | 説明 | 依存 |
|-----|------|------|------|
| 5A | Doneチャット検知 | 新着メッセージ検知、コンテンツ分類へ連携 | Phase 2（既存） |
| 5B | メール受信検知 | Gmail API連携で新着メール検知 | Gmail API設定 |
| 5C | 添付ファイル取得 | PDF/画像添付をダウンロード・保存 | 5B |

---

## Phase 5A: Doneチャット検知

### 目的

既存のDoneチャット（Phase 2）のメッセージ送信をフックし、AIが内容を解析して自動処理できるようにする。

### 実装方針

既存の`chat_routes.py`の`send_message`処理にフックを追加し、新着メッセージをイベントキューに送信する。

### データフロー

```
ユーザーがDoneチャットで送信
        ↓
WebSocket/REST API → DBに保存
        ↓
メッセージ検知サービスがフック
        ↓
detected_messages テーブルに保存
        ↓
（Phase 6以降で処理）
```

### API

#### イベント発火（内部処理）

メッセージ送信時に自動的にイベントが発火される（APIエンドポイントは不要）。

### DBスキーマ

```sql
-- 検知されたメッセージ
CREATE TABLE detected_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    source VARCHAR(20) NOT NULL,  -- 'done_chat', 'gmail', 'line'
    source_id VARCHAR(255),       -- 元のメッセージID（chat_messagesのid、GmailメッセージID等）
    content TEXT,                 -- メッセージ本文
    metadata JSONB,               -- ソース固有の追加情報
    status VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'processing', 'processed', 'failed'
    content_type VARCHAR(50),     -- 分類結果: 'invoice', 'otp', 'notification', 'general'
    processed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### 成功基準

| # | 基準 | 検証方法 |
|---|------|---------|
| 1 | Doneチャットでメッセージ送信時にdetected_messagesに保存される | 自動テスト |
| 2 | AI設定が有効なルームのみ検知される | 自動テスト |

---

## Phase 5B: メール受信検知

### 目的

Gmail APIを使用して新着メールを検知し、処理対象として登録する。

### 実装方針

Gmail API の **ポーリング方式**を採用（Pub/Sub Pushは設定が複雑なため後回し）。

定期的にGmailをチェックし、未処理のメールを取得する。

### 技術選定

| 方式 | メリット | デメリット | 採用 |
|------|---------|-----------|------|
| **ポーリング** | シンプル、ローカルでも動作 | リアルタイム性が低い | ✅ |
| Pub/Sub Push | リアルタイム検知 | Webhook設定が必要、本番環境のみ | 将来 |

### データフロー

```
Celery Beat (定期実行: 5分毎)
        ↓
Gmail API で新着メール取得
        ↓
detected_messages テーブルに保存
        ↓
添付ファイルがあれば 5C へ
        ↓
（Phase 6以降で処理）
```

### 必要な環境変数

```env
# Gmail API
GMAIL_CREDENTIALS_JSON=credentials.json  # OAuth2認証情報ファイルパス
GMAIL_TOKEN_JSON=token.json              # トークン保存先
GMAIL_POLL_INTERVAL_SECONDS=300          # ポーリング間隔（デフォルト5分）
```

### API

#### POST /api/v1/gmail/setup

Gmail OAuth2認証を開始

**Response:**
```json
{
  "auth_url": "https://accounts.google.com/o/oauth2/...",
  "message": "Please visit this URL to authorize Gmail access"
}
```

#### POST /api/v1/gmail/callback

OAuth2コールバック処理

**Request:**
```json
{
  "code": "authorization_code_from_google"
}
```

**Response:**
```json
{
  "success": true,
  "email": "user@gmail.com",
  "message": "Gmail access authorized successfully"
}
```

#### GET /api/v1/gmail/status

Gmail連携状態を確認

**Response:**
```json
{
  "connected": true,
  "email": "user@gmail.com",
  "last_sync": "2024-12-22T10:00:00Z",
  "unread_count": 5
}
```

#### POST /api/v1/gmail/sync

手動でメール同期を実行

**Response:**
```json
{
  "success": true,
  "new_messages": 3,
  "message_ids": ["msg_1", "msg_2", "msg_3"]
}
```

### DBスキーマ

```sql
-- Gmail連携設定
CREATE TABLE gmail_connections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE UNIQUE,
    email VARCHAR(255) NOT NULL,
    encrypted_token TEXT NOT NULL,  -- OAuth2トークン（暗号化）
    last_history_id VARCHAR(50),    -- Gmail履歴ID（差分取得用）
    last_sync_at TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### 成功基準

| # | 基準 | 検証方法 |
|---|------|---------|
| 1 | Gmail OAuth認証が完了できる | 自動テスト（モック） |
| 2 | 新着メールがdetected_messagesに保存される | 自動テスト |
| 3 | 差分取得で重複メールが保存されない | 自動テスト |

---

## Phase 5C: 添付ファイル取得

### 目的

メールの添付ファイル（PDF、画像等）をダウンロードし、Phase 6での解析に備える。

### 実装方針

Gmail APIで添付ファイルを取得し、ローカルストレージまたはSupabase Storageに保存。

### 対応ファイル形式

| 形式 | MIME Type | 用途 |
|------|-----------|------|
| PDF | application/pdf | 請求書、契約書 |
| PNG | image/png | スクリーンショット、請求書画像 |
| JPEG | image/jpeg | 請求書画像 |
| GIF | image/gif | （対応するが優先度低） |

### データフロー

```
5Bでメール検知
        ↓
添付ファイルあり？
        ↓ Yes
Gmail API で添付取得
        ↓
ストレージに保存
        ↓
attachments テーブルに記録
        ↓
detected_messages.metadata に参照追加
```

### DBスキーマ

```sql
-- 添付ファイル
CREATE TABLE message_attachments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    detected_message_id UUID REFERENCES detected_messages(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    file_size INTEGER,
    storage_path TEXT NOT NULL,  -- ローカルパス or Supabase Storage URL
    storage_type VARCHAR(20) DEFAULT 'local',  -- 'local', 'supabase'
    checksum VARCHAR(64),        -- SHA256ハッシュ（重複検出用）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### API

#### GET /api/v1/attachments/{id}

添付ファイルをダウンロード

**Response:** ファイルバイナリ

#### GET /api/v1/detected-messages/{id}/attachments

メッセージの添付ファイル一覧を取得

**Response:**
```json
{
  "attachments": [
    {
      "id": "uuid",
      "filename": "invoice.pdf",
      "mime_type": "application/pdf",
      "file_size": 102400,
      "created_at": "2024-12-22T10:00:00Z"
    }
  ]
}
```

### 成功基準

| # | 基準 | 検証方法 |
|---|------|---------|
| 1 | PDF添付ファイルがダウンロード・保存される | 自動テスト |
| 2 | 画像添付ファイルがダウンロード・保存される | 自動テスト |
| 3 | ファイルサイズ制限（10MB）が適用される | 自動テスト |

---

## ファイル構成

```
app/
├── api/
│   ├── routes.py               # 変更: Gmail API追加
│   ├── gmail_routes.py         # 新規: Gmail連携API
│   └── detection_routes.py     # 新規: 検知メッセージAPI
├── services/
│   ├── message_detection.py    # 新規: メッセージ検知サービス
│   ├── gmail_service.py        # 新規: Gmail連携サービス
│   └── attachment_service.py   # 新規: 添付ファイルサービス
├── tasks/
│   └── gmail_tasks.py          # 新規: Gmail同期タスク（Celery）
└── models/
    └── detection_schemas.py    # 新規: 検知関連スキーマ

supabase/
└── migrations/
    └── 005_message_detection.sql  # 新規: Phase 5テーブル

tests/
└── test_phase5_message_detection.py  # 新規: Phase 5テスト
```

---

## 実装ステップ

### Step 1: DBマイグレーション

| # | タスク | 説明 |
|---|--------|------|
| 1-1 | detected_messages テーブル作成 | 検知メッセージ保存 |
| 1-2 | gmail_connections テーブル作成 | Gmail連携設定保存 |
| 1-3 | message_attachments テーブル作成 | 添付ファイル情報保存 |

### Step 2: Phase 5A（Doneチャット検知）

| # | タスク | 説明 |
|---|--------|------|
| 2-1 | MessageDetectionService作成 | 共通の検知サービス |
| 2-2 | ChatServiceにフック追加 | send_message後に検知処理 |
| 2-3 | 検知条件設定 | AI有効ルームのみ検知 |

### Step 3: Phase 5B（メール受信検知）

| # | タスク | 説明 |
|---|--------|------|
| 3-1 | GmailService作成 | Gmail API連携 |
| 3-2 | OAuth2認証フロー実装 | 認証URL生成、コールバック処理 |
| 3-3 | メール取得ロジック実装 | 差分取得、メタデータ抽出 |
| 3-4 | Celery Beatタスク設定 | 定期ポーリング |

### Step 4: Phase 5C（添付ファイル取得）

| # | タスク | 説明 |
|---|--------|------|
| 4-1 | AttachmentService作成 | 添付ファイル管理 |
| 4-2 | ファイルダウンロード実装 | Gmail API経由で取得 |
| 4-3 | ストレージ保存実装 | ローカル/Supabase Storage |
| 4-4 | ファイルサイズ制限実装 | 10MB上限 |

### Step 5: テスト

| # | タスク | 説明 |
|---|--------|------|
| 5-1 | 単体テスト | 各サービスのテスト |
| 5-2 | 統合テスト | エンドツーエンドのテスト |

---

## リスクと対策

| リスク | 対策 |
|--------|------|
| Gmail APIの利用制限 | レート制限の実装、キャッシュ活用 |
| OAuth2トークン期限切れ | リフレッシュトークンの自動更新 |
| 大量メールによる負荷 | バッチ処理、ページネーション |
| 添付ファイルの容量 | サイズ制限（10MB）、古いファイルの自動削除 |

---

## 環境変数（追加）

```env
# Gmail API
GMAIL_CLIENT_ID=your_client_id
GMAIL_CLIENT_SECRET=your_client_secret
GMAIL_REDIRECT_URI=http://localhost:8000/api/v1/gmail/callback
GMAIL_POLL_INTERVAL_SECONDS=300

# 添付ファイル
ATTACHMENT_STORAGE_PATH=./data/attachments
ATTACHMENT_MAX_SIZE_MB=10
```

---

## 次のステップ

Phase 5完了後、**Phase 6: Content Intelligence**（コンテンツ解析）に進む。

- Phase 5: メッセージを検知する ← 今回
- Phase 6: コンテンツを解析する（PDF解析、OCR、分類）
- Phase 7: 請求書を管理する
