# Phase 2: Chat System（チャットシステム）

## 概要

Done システムの中核となるチャット機能。ユーザーはAIアシスタント「ダン」と直接会話し、また友達とのチャットでもダンが仲介・サポートする。

## コンセプト

### Done ユーザーとダン

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Done システム                                  │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                        ダン（Dan）ページ                            │ │
│  │   ・ユーザーとダンの1対1会話                                        │ │
│  │   ・タスク実行の指示・承認                                          │ │
│  │   ・通知・提案の受け取り                                            │ │
│  │   ← ここが司令塔                                                   │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                              ↑↓ 記憶・情報を共有                        │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                    チャットwithダン ページ                          │ │
│  │   ・友達とのLINE的チャット                                          │ │
│  │   ・互いのダンが会話を見守り・仲介                                   │ │
│  │   ・必要に応じてダンページに提案を送る                               │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  あなた（Doneユーザー）+ あなたのダン                                    │
└─────────────────────────────────────────────────────────────────────────┘
           ↑
           │ チャットwithダン
           ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  友達（Doneユーザー）+ 友達のダン                                        │
└─────────────────────────────────────────────────────────────────────────┘
```

### 重要な原則

1. **全員がDoneユーザー**: チャットwithダンを使うには、全員がDoneをインストールしている必要がある
2. **1ユーザー1ダン**: 各ユーザーに専属のダン（AI人格）が存在
3. **記憶の共有**: ダンページでの会話とチャットwithダンでの会話は、同じダンの記憶として統合される
4. **操作の自由度**: 
   - **デフォルト**: ダンが返信案を考えてダンページに「どうします？」と提案（文章を考える手間を省ける）
   - **直接操作も可能**: ユーザーが望めばチャットwithダンで直接返信・操作できる

---

## Sub-phases

| Sub | 機能 | 説明 | 状態 |
|-----|------|------|------|
| 2A | ユーザー認証 | 登録・ログイン・プロフィール管理 | ✅ 完了（users統合済み） |
| 2B | 友達管理 | 招待リンク発行・承諾・友達一覧 | ✅ 実装済み |
| 2C | チャットルーム | ルーム作成・メンバー管理・1対1/グループ | ✅ 実装済み |
| 2D | メッセージング | メッセージ送受信・既読管理 | ✅ 実装済み |
| 2E | ダンページ | ユーザーとダンの1対1会話（司令塔） | ✅ 実装済み |
| 2F | チャットwithダン | 友達とのチャット＋ダン仲介 | ✅ 基盤完了 |
| 2G | ダン連携 | ダンページ↔チャットwithダン間の通知・提案 | ✅ 実装済み |

---

## 2A: ユーザー認証（完了）

### 統合完了

`users` テーブルと `chat_users` テーブルが統合されました。

**統合後の users テーブル構造:**
```sql
users (
    id UUID PRIMARY KEY,
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255),  -- チャット認証用
    line_user_id VARCHAR(255),
    display_name VARCHAR(255),
    avatar_url TEXT,  -- プロフィール画像
    created_at TIMESTAMP,
    updated_at TIMESTAMP
)
```

### APIエンドポイント（現行）

| メソッド | パス | 説明 |
|---------|------|------|
| POST | `/api/v1/chat/register` | ユーザー登録 |
| POST | `/api/v1/chat/login` | ログイン |
| GET | `/api/v1/chat/me` | 自分のプロフィール取得 |
| PATCH | `/api/v1/chat/me` | プロフィール更新 |

---

## 2B: 友達管理

### 友達追加フロー

```
1. ユーザーAが招待リンクを発行
   POST /api/v1/chat/invite → { code: "abc123", url: "https://done.app/invite/abc123" }
   
2. ユーザーBがURLをクリック
   - Doneアプリがインストールされていない → アプリストアへ誘導
   - Doneアプリがインストール済み → 招待承諾画面へ
   
3. ユーザーBが招待を承諾
   POST /api/v1/chat/invite/{code}/accept
   
4. 双方向の友達関係が成立
```

### APIエンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| POST | `/api/v1/chat/invite` | 招待リンク発行 |
| GET | `/api/v1/chat/invite/{code}` | 招待情報取得 |
| POST | `/api/v1/chat/invite/{code}/accept` | 招待承諾 |
| GET | `/api/v1/chat/friends` | 友達一覧 |
| DELETE | `/api/v1/chat/friends/{id}` | 友達削除 |

---

## 2C-2D: チャットルーム・メッセージング

### ルームタイプ

| タイプ | 説明 | ダンの役割 |
|-------|------|-----------|
| `direct` | 1対1チャット | 双方のダンが見守り・仲介 |
| `group` | グループチャット | 全員のダンが見守り・仲介 |
| `dan` | ダンページ（1対1） | ユーザーと自分のダンのみ |

### APIエンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/api/v1/chat/rooms` | ルーム一覧 |
| POST | `/api/v1/chat/rooms` | ルーム作成 |
| GET | `/api/v1/chat/rooms/{id}` | ルーム詳細 |
| PATCH | `/api/v1/chat/rooms/{id}` | ルーム更新 |
| GET | `/api/v1/chat/rooms/{id}/members` | メンバー一覧 |
| POST | `/api/v1/chat/rooms/{id}/members` | メンバー追加 |
| POST | `/api/v1/chat/rooms/{id}/messages` | メッセージ送信 |
| GET | `/api/v1/chat/rooms/{id}/messages` | メッセージ取得 |
| POST | `/api/v1/chat/rooms/{id}/read` | 既読マーク |

---

## 2F: チャットwithダン

### ダン仲介の例

#### パターン1: ダンに任せる（デフォルト）

```
[チャットwithダン]
友達: 「明日15時に打ち合わせどう？」

[ダン（裏で処理）]
  ・カレンダーを確認
  ・15時は空いている
  ・返信案を作成
  ・ダンページに通知を送信

[ダンページ]
通知: 「友達Bさんから15時に打ち合わせの提案です」
返信案: 「15時で大丈夫です！」
[送信] [編集] [却下]

[ユーザーが「送信」をタップ]

[チャットwithダンに自動返信]
あなた: 「15時で大丈夫です！」
（カレンダーにも自動登録）
```

#### パターン2: 直接返信する

```
[チャットwithダン]
友達: 「明日15時に打ち合わせどう？」

[ユーザーが直接チャットwithダンで返信]
あなた: 「15時OK！楽しみにしてる」

[ダン（裏で処理）]
  ・ユーザーが直接返信したことを検知
  ・カレンダーに予定を登録するか確認
  ・ダンページに通知:
    「15時に予定を登録しますか？ [はい] [いいえ]」
```

**ポイント**: ユーザーはいつでも自分で返信できる。ダンは補助に回る。

---

## 完了したマイグレーション

### 009_user_unification（適用済み）

1. `users` テーブルに `password_hash`, `avatar_url` カラム追加
2. `chat_users` のデータを `users` に移行
3. 外部キー参照を `chat_users` → `users` に変更
4. `chat_users` テーブル削除

---

## 2E: ダンページ（実装完了）

### 概要

各ユーザーに専属のダン（AIアシスタント）との1対1会話ルーム。ユーザー登録時に自動作成される。

### ルームタイプ

| タイプ | 説明 | 自動作成 |
|-------|------|---------|
| `dan` | ユーザーとダンの1対1 | ✅ ユーザー登録時 |

### APIエンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/api/v1/chat/dan` | ダンルーム情報取得 |
| GET | `/api/v1/chat/dan/messages` | メッセージ一覧取得 |
| POST | `/api/v1/chat/dan/messages` | ダンにメッセージ送信 |
| POST | `/api/v1/chat/dan/read` | 既読マーク |

### レスポンス例

```json
{
  "id": "uuid",
  "name": "ダン",
  "type": "dan",
  "unread_count": 3,
  "pending_proposals_count": 1,
  "last_message_at": "2025-12-26T10:00:00Z",
  "created_at": "2025-12-26T09:00:00Z"
}
```

---

## 2G: ダン連携（実装完了）

### 概要

ダンがチャットwithダンの会話を分析し、ダンページに提案を送る仕組み。

### 提案タイプ

| タイプ | 説明 | 例 |
|-------|------|-----|
| `reply` | 返信案 | 「15時で大丈夫です！」 |
| `action` | アクション提案 | 商品購入、予約など |
| `schedule` | スケジュール登録 | カレンダーに予定追加 |
| `reminder` | リマインダー | 締め切り通知 |

### 提案ステータス

| ステータス | 説明 |
|-----------|------|
| `pending` | 保留中（ユーザーの対応待ち） |
| `approved` | 承認済み（実行完了） |
| `rejected` | 却下済み |
| `expired` | 期限切れ |

### APIエンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/api/v1/chat/proposals` | 提案一覧取得 |
| GET | `/api/v1/chat/proposals/{id}` | 提案詳細取得 |
| POST | `/api/v1/chat/proposals/{id}/respond` | 提案に対応（承認/却下/編集） |

### 提案レスポンス例

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "type": "reply",
  "status": "pending",
  "title": "友達Bさんへの返信案",
  "content": "15時で大丈夫です！",
  "source_room_id": "uuid",
  "source_room_name": "友達B",
  "created_at": "2025-12-26T10:00:00Z"
}
```

### 提案アクションリクエスト

```json
{
  "action": "approve"  // or "reject" or "edit"
  "edited_content": "15時OKです！楽しみにしてる"  // action=editの場合
}
```

---

## DBテーブル

### dan_proposals（提案テーブル）

```sql
dan_proposals (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    dan_room_id UUID REFERENCES chat_rooms(id),
    type VARCHAR(50),  -- reply, action, schedule, reminder
    status VARCHAR(50) DEFAULT 'pending',
    title VARCHAR(255),
    content TEXT,
    source_room_id UUID,  -- 元のチャットルーム
    source_message_id UUID,  -- 元のメッセージ
    action_data JSONB,  -- アクション実行データ
    expires_at TIMESTAMPTZ,
    responded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
)
```

### users追加カラム

```sql
ALTER TABLE users ADD COLUMN dan_room_id UUID REFERENCES chat_rooms(id);
```
