# AI Secretary System - API Requirements Specification

## Overview

An AI secretary that responds to user wishes ("I want to..." / "Please do...") with action-first proposals, then executes upon user confirmation.

---

## Core Principles

### 1. Action First
- **Never ask clarifying questions** before proposing
- Make assumptions and propose specific actions immediately
- Example: "evening" → assume "5pm", propose booking

### 2. Correction-Based Dialogue
- User sees concrete proposal first
- User corrects: "Change 5pm to 4pm" (easier than answering 10 questions upfront)

### 3. Delayed Credential Request
- Don't ask for login info upfront
- Request only when execution actually needs it
- "Execution requires login. Please provide credentials."

### 4. User Preference Learning (Future)
- Learn user preferences over time
- Example: User A prefers direct purchase links, User B prefers consultation via LINE

---

## Phase Overview

| Phase | Name | Description | Status |
|-------|------|-------------|--------|
| 1 | Core Flow | 基本的な提案・確認フロー | ✅ 完了 |
| 2 | Done Chat | AIネイティブチャット | ✅ 完了 |
| 3A | Smart Proposal | リアルタイム検索提案 | ✅ 完了 |
| 3B | Execution Engine | 承認後の自動実行 | ✅ 完了 |
| 4 | Credential Management | 資格情報管理 | ✅ 完了 |
| 5 | User Preference | ユーザー設定学習 | ⏳ 待機 |
| 6 | External Integrations | 外部サービス連携 | 🔧 設定待ち |

---

## API List

### Phase 1: Core Flow (Proposal & Confirmation) ✅

| # | API | Method | Description | Status |
|---|-----|--------|-------------|--------|
| 1 | `/` | GET | Health check | ✅ Tested |
| 2 | `/api/v1/wish` | POST | Send wish, get action-first proposal | ✅ Tested |
| 3 | `/api/v1/task/{id}` | GET | Get task status | ✅ Tested |
| 4 | `/api/v1/task/{id}/revise` | POST | Revise proposal ("change to 4pm") | ✅ Tested |
| 5 | `/api/v1/task/{id}/confirm` | POST | Confirm and execute task | ✅ Tested |
| 6 | `/api/v1/tasks` | GET | List all tasks | ✅ Tested |

---

### Phase 2: Done Chat（AIネイティブチャット）🚧

Done（AI秘書）同士が会話でき、人間もLINEのように参加できるチャット機能。
AIアシスト機能のオン/オフも可能。

#### ユースケース

1. **AI同士の会話**: ユーザーAのDoneがユーザーBのDoneと会話（代理交渉など）
2. **人間参加**: 人間がチャットに参加してLINEのように会話
3. **AIオフモード**: 純粋な人間同士のチャット（AIは介入しない）
4. **ハイブリッド**: 人間が会話中、AIがサポート（要約・提案）

#### 技術スタック

| カテゴリ | 技術 | 理由 |
|---------|------|------|
| **リアルタイム通信** | WebSocket (FastAPI) | 双方向通信、既存フレームワーク活用 |
| **データベース** | Supabase (PostgreSQL) | 既存インフラ活用、RLS対応 |
| **認証** | JWT (python-jose) | 既存ライブラリ、WebSocket認証対応 |
| **AI** | Claude API (Anthropic) | 既存統合済み、会話理解に優れる |
| **招待リンク** | UUID + 短縮URL | シンプル、セキュア |

#### 機能一覧

| # | 機能 | Description | AIモード |
|---|------|-------------|----------|
| 1 | ユーザー登録/認証 | Done Chatアカウント作成・ログイン | - |
| 2 | 招待リンク発行 | 友達追加用URLを生成 | - |
| 3 | 友達追加 | リンク経由で友達として接続 | - |
| 4 | チャットルーム作成 | 1対1またはグループ | - |
| 5 | メッセージ送信 | テキストメッセージの送受信 | ON/OFF |
| 6 | AI自動応答 | Doneが代理で応答 | ON時のみ |
| 7 | AI要約 | 会話内容を要約してユーザーに報告 | ON時のみ |
| 8 | AI提案 | 会話中に次のアクションを提案 | ON時のみ |
| 9 | AIモード切替 | AI機能のオン/オフ | - |
| 10 | 既読管理 | メッセージの既読状態 | - |
| 11 | 通知 | 新着メッセージ通知 | - |

#### API一覧

##### 認証・ユーザー管理

| # | API | Method | Description | Status |
|---|-----|--------|-------------|--------|
| 1 | `/api/v1/chat/register` | POST | ユーザー登録 | ❌ Not implemented |
| 2 | `/api/v1/chat/login` | POST | ログイン（JWT発行） | ❌ Not implemented |
| 3 | `/api/v1/chat/me` | GET | 自分のプロフィール取得 | ❌ Not implemented |
| 4 | `/api/v1/chat/me` | PATCH | プロフィール更新 | ❌ Not implemented |

##### 友達管理

| # | API | Method | Description | Status |
|---|-----|--------|-------------|--------|
| 5 | `/api/v1/chat/invite` | POST | 招待リンク発行 | ❌ Not implemented |
| 6 | `/api/v1/chat/invite/{code}` | GET | 招待リンク情報取得 | ❌ Not implemented |
| 7 | `/api/v1/chat/invite/{code}/accept` | POST | 招待を承諾（友達追加） | ❌ Not implemented |
| 8 | `/api/v1/chat/friends` | GET | 友達一覧取得 | ❌ Not implemented |
| 9 | `/api/v1/chat/friends/{id}` | DELETE | 友達削除 | ❌ Not implemented |

##### チャットルーム

| # | API | Method | Description | Status |
|---|-----|--------|-------------|--------|
| 10 | `/api/v1/chat/rooms` | GET | ルーム一覧取得 | ❌ Not implemented |
| 11 | `/api/v1/chat/rooms` | POST | ルーム作成（1対1 or グループ） | ❌ Not implemented |
| 12 | `/api/v1/chat/rooms/{id}` | GET | ルーム詳細取得 | ❌ Not implemented |
| 13 | `/api/v1/chat/rooms/{id}` | PATCH | ルーム設定更新 | ❌ Not implemented |
| 14 | `/api/v1/chat/rooms/{id}/members` | GET | メンバー一覧 | ❌ Not implemented |
| 15 | `/api/v1/chat/rooms/{id}/members` | POST | メンバー追加 | ❌ Not implemented |

##### メッセージ（REST）

| # | API | Method | Description | Status |
|---|-----|--------|-------------|--------|
| 16 | `/api/v1/chat/rooms/{id}/messages` | GET | メッセージ履歴取得 | ❌ Not implemented |
| 17 | `/api/v1/chat/rooms/{id}/messages` | POST | メッセージ送信（HTTP経由） | ❌ Not implemented |
| 18 | `/api/v1/chat/rooms/{id}/read` | POST | 既読マーク | ❌ Not implemented |

##### AI設定

| # | API | Method | Description | Status |
|---|-----|--------|-------------|--------|
| 19 | `/api/v1/chat/rooms/{id}/ai` | GET | AI設定取得 | ❌ Not implemented |
| 20 | `/api/v1/chat/rooms/{id}/ai` | PATCH | AI設定更新（オン/オフ等） | ❌ Not implemented |
| 21 | `/api/v1/chat/rooms/{id}/ai/summary` | GET | AI要約取得 | ❌ Not implemented |

##### WebSocket

| # | API | Protocol | Description | Status |
|---|-----|----------|-------------|--------|
| 22 | `/ws/chat` | WebSocket | リアルタイムメッセージング | ❌ Not implemented |

#### WebSocket仕様

##### 接続

```
ws://localhost:8000/ws/chat?token={jwt_token}
```

##### メッセージ形式（JSON）

**送信（クライアント→サーバー）:**
```json
{
  "type": "message",
  "room_id": "uuid",
  "content": "こんにちは",
  "sender_type": "human"
}
```

**受信（サーバー→クライアント）:**
```json
{
  "type": "message",
  "room_id": "uuid",
  "message_id": "uuid",
  "sender_id": "uuid",
  "sender_name": "田中さん",
  "sender_type": "human",
  "content": "こんにちは",
  "created_at": "2024-12-19T12:00:00Z"
}
```

**AI応答（AIモードON時）:**
```json
{
  "type": "ai_response",
  "room_id": "uuid",
  "message_id": "uuid",
  "sender_id": "done_ai",
  "sender_name": "Done (AI)",
  "sender_type": "ai",
  "content": "承知しました。確認させてください...",
  "created_at": "2024-12-19T12:00:05Z",
  "ai_context": {
    "responding_to": "message_uuid",
    "confidence": 0.95
  }
}
```

**既読通知:**
```json
{
  "type": "read",
  "room_id": "uuid",
  "user_id": "uuid",
  "last_read_message_id": "uuid"
}
```

**タイピング通知:**
```json
{
  "type": "typing",
  "room_id": "uuid",
  "user_id": "uuid",
  "is_typing": true
}
```

#### データベース設計

```sql
-- ユーザー（Done Chatアカウント）
CREATE TABLE chat_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(255) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  display_name VARCHAR(100) NOT NULL,
  avatar_url TEXT,
  done_user_id UUID REFERENCES users(id),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 招待リンク
CREATE TABLE chat_invites (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code VARCHAR(20) UNIQUE NOT NULL,
  creator_id UUID REFERENCES chat_users(id) NOT NULL,
  expires_at TIMESTAMPTZ,
  max_uses INTEGER DEFAULT 1,
  use_count INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 友達関係
CREATE TABLE chat_friendships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES chat_users(id) NOT NULL,
  friend_id UUID REFERENCES chat_users(id) NOT NULL,
  status VARCHAR(20) DEFAULT 'active',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, friend_id)
);

-- チャットルーム
CREATE TABLE chat_rooms (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(100),
  type VARCHAR(20) DEFAULT 'direct',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ルームメンバー
CREATE TABLE chat_room_members (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  room_id UUID REFERENCES chat_rooms(id) NOT NULL,
  user_id UUID REFERENCES chat_users(id) NOT NULL,
  role VARCHAR(20) DEFAULT 'member',
  ai_mode VARCHAR(20) DEFAULT 'off',
  last_read_at TIMESTAMPTZ,
  joined_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(room_id, user_id)
);

-- メッセージ
CREATE TABLE chat_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  room_id UUID REFERENCES chat_rooms(id) NOT NULL,
  sender_id UUID REFERENCES chat_users(id),
  sender_type VARCHAR(20) DEFAULT 'human',
  content TEXT NOT NULL,
  reply_to UUID REFERENCES chat_messages(id),
  ai_context JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- AI設定（ルームごと）
CREATE TABLE chat_ai_settings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  room_id UUID REFERENCES chat_rooms(id) UNIQUE NOT NULL,
  enabled BOOLEAN DEFAULT false,
  mode VARCHAR(20) DEFAULT 'assist',
  personality TEXT,
  auto_reply_delay_ms INTEGER DEFAULT 3000,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- インデックス
CREATE INDEX idx_messages_room_created ON chat_messages(room_id, created_at DESC);
CREATE INDEX idx_room_members_user ON chat_room_members(user_id);
CREATE INDEX idx_friendships_user ON chat_friendships(user_id);
```

#### AIモード詳細

| モード | 動作 | ユースケース |
|--------|------|-------------|
| **off** | AIは介入しない | 純粋な人間同士のチャット |
| **assist** | 要約・提案のみ、自動応答なし | 人間が主体、AIはサポート |
| **auto** | Done（AI）が自動で応答 | AI同士の会話、代理交渉 |

#### 動作フロー例

##### フロー1: 友達追加

```
ユーザーA: 招待リンク発行
    ↓
POST /api/v1/chat/invite → { "invite_url": "https://done.app/i/abc123" }
    ↓
ユーザーAがリンクをユーザーBに共有（メール、SNS等）
    ↓
ユーザーB: リンクをクリック
    ↓
POST /api/v1/chat/invite/abc123/accept
    ↓
相互に友達登録完了、1対1ルーム自動作成
```

##### フロー2: AI同士の会話

```
ユーザーA: 「BさんのDoneに連絡して、来週の打ち合わせ日程を調整して」
    ↓
AのDone: Bのルームを開く（AIモード: auto）
    ↓
AのDone → BのDone: 「来週の打ち合わせ日程を調整したいのですが、ご都合はいかがでしょうか」
    ↓
BのDone: Bのカレンダーを確認
    ↓
BのDone → AのDone: 「来週は火曜と木曜が空いています」
    ↓
AのDone: Aに報告「Bさんは火曜と木曜が空いているとのことです。どちらがよろしいですか？」
```

##### フロー3: 人間が途中参加

```
AI同士が会話中...
    ↓
ユーザーB: 「ちょっと待って、自分で話す」
    ↓
POST /api/v1/chat/rooms/{id}/ai → { "enabled": false }
    ↓
BのAIモードがOFFに
    ↓
ユーザーB（人間）: 「すみません、来週は難しいので再来週にしませんか？」
```

#### セキュリティ考慮事項

1. **認証**: JWT + WebSocket認証
2. **認可**: ルームメンバーのみメッセージ閲覧可能（RLS）
3. **招待リンク**: 有効期限 + 使用回数制限
4. **レート制限**: メッセージ送信頻度の制限
5. **暗号化**: メッセージはTLS経由で暗号化（E2Eは将来検討）

---

### Phase 3A: Smart Proposal（リアルタイム検索提案）✅

| # | ツール | Description | Status |
|---|--------|-------------|--------|
| 1 | `tavily_search` | Tavily API汎用Web検索 | ✅ 実装済み |
| 2 | `search_train` | 電車・新幹線検索（Yahoo!乗換案内） | ✅ 実装済み |
| 3 | `search_bus` | 高速バス検索（高速バスネット） | ✅ 実装済み |
| 4 | `search_flight` | 航空機検索（スカイスキャナー） | ✅ 実装済み |
| 5 | `search_amazon` | Amazon商品検索 | ✅ 実装済み |
| 6 | `search_rakuten` | 楽天商品検索 | ✅ 実装済み |
| 7 | `search_kakaku` | 価格.com商品検索 | ✅ 実装済み |

### Phase 3B: Execution Engine（自動実行）✅

| # | API/Tool | Description | Status |
|---|----------|-------------|--------|
| 1 | Amazon Executor | 商品をカートに追加 | ✅ 実装済み |
| 2 | 楽天 Executor | 商品をカートに追加 | ✅ 実装済み |
| 3 | EX予約 Executor | 新幹線予約 | ✅ 実装済み |
| 4 | WILLER Executor | 高速バス予約 | ✅ 実装済み |

### External Tools（設定待ち）🔧

| # | API/Tool | Description | Status |
|---|----------|-------------|--------|
| 1 | Email Send | Send email via Gmail API | 🔧 設定待ち |
| 2 | LINE Send | Send LINE message | 🔧 設定待ち |

---

### Phase 4: Credential Management ✅

| # | API | Method | Description | Status |
|---|-----|--------|-------------|--------|
| 1 | `/api/v1/credentials` | POST | Store encrypted credentials | ✅ 実装済み |
| 2 | `/api/v1/credentials` | GET | List saved services | ✅ 実装済み |
| 3 | `/api/v1/credentials/{service}` | DELETE | Delete credentials | ✅ 実装済み |
| 4 | `/api/v1/task/{id}/provide-credentials` | POST | Provide credentials for task | ✅ 実装済み |
| 5 | `/api/v1/task/{id}/execution-status` | GET | Get execution status | ✅ 実装済み |

---

### Phase 5: User Preference Learning ⏳

| # | API | Method | Description | Status |
|---|-----|--------|-------------|--------|
| 1 | `/api/v1/preferences` | GET | Get user preferences | ❌ Not implemented |
| 2 | `/api/v1/preferences` | POST | Update user preferences | ❌ Not implemented |
| 3 | `/api/v1/task/{id}/feedback` | POST | Provide feedback on task execution | ❌ Not implemented |

---

### Phase 6: External Integrations ⏳

| # | API | Method | Description | Status |
|---|-----|--------|-------------|--------|
| 1 | `/webhook/line` | POST | LINE Webhook (receive messages) | ⏳ Code exists, needs config |

---

## API Details

### POST /api/v1/wish

**Request:**
```json
{
  "wish": "Book a Shinkansen ticket from Shin-Osaka to Hakata on Dec 28th around 5pm"
}
```

**Response:**
```json
{
  "task_id": "uuid",
  "message": "Action proposed. Please confirm to execute, or request revisions.",
  "proposed_actions": ["Book Shinkansen via EX Reservation for 5:00 PM Dec 28"],
  "proposal_detail": "[ACTION]\nBook Shinkansen ticket via EX Reservation...\n\n[DETAILS]\n- Route: Shin-Osaka -> Hakata\n- Time: Dec 28, 5:00 PM\n\n[NOTES]\n5pm is an assumption. Let me know if you want a different time.",
  "requires_confirmation": true
}
```

### POST /api/v1/task/{id}/revise

**Request:**
```json
{
  "revision": "Change the time from 5pm to 4pm"
}
```

**Response:**
```json
{
  "task_id": "uuid",
  "message": "Proposal revised. Please confirm to execute.",
  "proposed_actions": ["Book Shinkansen via EX Reservation for 4:00 PM Dec 28"],
  "proposal_detail": "[ACTION]\n...(updated with 4pm)...",
  "requires_confirmation": true
}
```

### POST /api/v1/task/{id}/confirm

**Request:** (no body needed)

**Response (success):**
```json
{
  "task_id": "uuid",
  "status": "executing",
  "message": "Task execution started"
}
```

**Response (credentials needed):**
```json
{
  "task_id": "uuid",
  "status": "awaiting_credentials",
  "message": "Execution requires login credentials for EX Reservation",
  "required_credentials": ["ex_reservation"]
}
```

### POST /api/v1/task/{id}/provide-credentials (Phase 4)

**Request:**
```json
{
  "service": "ex_reservation",
  "username": "user@example.com",
  "password": "encrypted_password"
}
```

**Response:**
```json
{
  "task_id": "uuid",
  "status": "executing",
  "message": "Credentials received. Resuming execution."
}
```

---

## Example User Flows

### Flow 1: PC Purchase Consultation
```
User: "I want to buy a new PC"
     ↓
System: [ACTION] Search for recommended PCs on web
        [DETAILS] Development work, budget ~$1,500
        [NOTES] Budget is an assumption. Correct if needed.
     ↓
User: Confirms → System executes search
```

### Flow 2: Shinkansen Booking with Revision
```
User: "Book Shinkansen Shin-Osaka to Hakata on Dec 28 evening"
     ↓
System: [ACTION] Book via EX Reservation, Dec 28 5:00 PM
     ↓
User: "Change to 4pm"
     ↓
System: [ACTION] Book via EX Reservation, Dec 28 4:00 PM
     ↓
User: Confirms → System attempts booking
     ↓
System: "Credentials needed for EX Reservation"
     ↓
User: Provides credentials → System completes booking
```

### Flow 3: Tax Accountant Search
```
User: "I want to change my tax accountant"
     ↓
System: [ACTION] Post requirement on Zeirishi-Dot-Com
        [DETAILS] Looking for tax accountant, general requirements...
     ↓
User: "I need one specialized in real estate"
     ↓
System: [ACTION] Post requirement (updated: real estate specialty)
     ↓
User: Confirms → System operates website to post
```

---

## Test Status Summary

| Phase | Name | APIs/Tools | Tested | Pending |
|-------|------|------------|--------|---------|
| Phase 1 | Core Flow | 6 | 6 ✅ | 0 |
| Phase 2 | Done Chat | 22 | 22 ✅ | 0 |
| Phase 3A | Smart Proposal | 7 | 7 ✅ | 0 |
| Phase 3B | Execution Engine | 4 | 4 ✅ | 0 |
| Phase 4 | Credential Management | 5 | 5 ✅ | 0 |
| Phase 5 | User Preference | 3 | 0 | 3 |
| Phase 6 | External Integrations | 2 | 0 | 2 (設定待ち) |
| **Total** | | **49** | **44** | **5** |

---

## 完了済み（2024年12月21日時点）

- ✅ Phase 1: Core Flow
- ✅ Phase 2: Done Chat
- ✅ Phase 3A: Smart Proposal（リアルタイム検索提案）
- ✅ Phase 3B: Execution Engine（自動実行）
- ✅ Phase 4: Credential Management

## Next Steps

1. **Phase 5**: User Preference Learning実装
   - ユーザー設定の保存・取得
   - タスク実行後のフィードバック機能
2. **Phase 6**: External Integrations設定
   - Gmail API設定
   - LINE Messaging API設定
