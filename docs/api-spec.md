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

## API List

### Phase 1: Core Flow (Proposal & Confirmation)

| # | API | Method | Description | Status |
|---|-----|--------|-------------|--------|
| 1 | `/` | GET | Health check | ✅ Tested |
| 2 | `/api/v1/wish` | POST | Send wish, get action-first proposal | ✅ Tested |
| 3 | `/api/v1/task/{id}` | GET | Get task status | ✅ Tested |
| 4 | `/api/v1/task/{id}/revise` | POST | Revise proposal ("change to 4pm") | ✅ Tested |
| 5 | `/api/v1/task/{id}/confirm` | POST | Confirm and execute task | ✅ Tested |
| 6 | `/api/v1/tasks` | GET | List all tasks | ✅ Tested |

### Phase 2: Actual Execution Tools

| # | API/Tool | Description | Status |
|---|----------|-------------|--------|
| 7 | Email Send | Send email via Gmail API | ⏳ Code exists, needs config |
| 8 | Web Browse | Browse/operate websites via Playwright | ⏳ Code exists, not connected |
| 9 | Form Fill | Fill forms on websites | ⏳ Code exists, not connected |
| 10 | Web Search | Search web for information | ⏳ Code exists, not connected |

### Phase 2A: LINE Proxy Communication (LINEコミュニケーション代行)

AI秘書がユーザーの個人LINEアカウントを代行操作し、外部（店舗・個人）とのコミュニケーションを仲介する機能。

#### 技術調査結果（2024年12月）

| 方法 | 可否 | 理由 |
|------|------|------|
| LINE Chrome拡張 | ❌ | 2025年9月終了 |
| LINE Web版 | ❌ | 存在しない |
| Playwright + LINE | ❌ | デスクトップアプリのため |
| LINE Messaging API | ❌ | 公式→公式は送信不可 |
| **pywinauto + LINE PC版** | ✅ | UI Automation方式で安定操作可能 |

#### 技術スタック
- **pywinauto**: LINE PC版（Windows）のUI自動操作
- **LangGraph**: 会話コンテキスト理解・自律判断
- **Supabase**: 会話履歴・コンテキスト保存

#### ⚠️ 利用規約に関する注意

LINE利用規約では「ボット、チートツール、その他の技術的手段を使用してサービスを操作すること」が禁止されています。
pywinautoによる操作は規約違反となる可能性があり、アカウント停止のリスクがあります。

**リスク軽減策:**
- 人間らしい操作間隔（ランダム遅延）
- 大量送信の回避
- 自己責任での利用

#### 機能一覧

| # | 機能 | Description | Status |
|---|------|-------------|--------|
| 11 | LINE Connect | pywinautoでLINE PC版に接続 | ❌ Not implemented |
| 12 | Friend Check | 送信先が友達追加されているか確認 | ❌ Not implemented |
| 13 | Friend Add | 友達追加されていなければ追加（ID検索） | ❌ Not implemented |
| 14 | Send Message | 承認済みメッセージをpywinautoで送信 | ❌ Not implemented |
| 15 | Receive Message | 相手からの返信を監視・受信 | ❌ Not implemented |
| 16 | Summarize & Report | 受信内容を要約してユーザーに報告 | ❌ Not implemented |
| 17 | Auto-Clarify | 相手の返信が不明確な場合、自律的に確認返信 | ❌ Not implemented |
| 18 | Conversation Memory | 会話履歴・コンテキストを記憶 | ❌ Not implemented |

#### API一覧

| # | API | Method | Description | Status |
|---|-----|--------|-------------|--------|
| 19 | `/api/v1/line/connect` | POST | LINE PC版への接続開始 | ❌ Not implemented |
| 20 | `/api/v1/line/status` | GET | 接続状態確認 | ❌ Not implemented |
| 21 | `/api/v1/line/friends` | GET | 友達リスト取得 | ❌ Not implemented |
| 22 | `/api/v1/line/friends/search` | POST | ID検索して友達追加 | ❌ Not implemented |
| 23 | `/api/v1/line/conversations` | GET | 会話一覧取得 | ❌ Not implemented |
| 24 | `/api/v1/line/conversations/{id}` | GET | 特定会話の履歴取得 | ❌ Not implemented |
| 25 | `/api/v1/line/conversations/{id}/send` | POST | メッセージ送信（要承認） | ❌ Not implemented |
| 26 | `/api/v1/line/conversations/{id}/messages` | GET | 新着メッセージ取得 | ❌ Not implemented |

#### 動作フロー

```
【前提条件】
- LINE PC版がインストール済み
- ユーザーがLINE PC版にログイン済み
- LINE PC版が起動している

【初回セットアップ】
1. POST /api/v1/line/connect → pywinautoでLINE PC版に接続
2. GET /api/v1/line/status → 接続状態確認

【メッセージ送信フロー】
1. ユーザー: 「MDLmakeにPCの相談をしたい」
2. AI秘書: 提案生成（アクションファースト）
3. ユーザー: 承認
4. AI秘書: 友達追加確認 → 未追加なら追加
5. AI秘書: メッセージ送信
6. AI秘書: 会話履歴に保存

【返信受信・報告フロー】
1. AI秘書: 定期的に新着メッセージを監視（ポーリング or WebSocket）
2. 相手から返信受信
3. AI秘書: 内容を分析
   - 報告すべき内容 → ユーザーに要約して報告
   - 確認が必要な内容 → ユーザーに確認を求める
   - 不明確な内容 → 自律的に相手に確認返信
4. 会話履歴に保存（コンテキスト維持）

【自律判断の例】
相手: 「納期はいつがいいですか？」
AI秘書の判断:
  - ユーザーの元の要望に納期の情報がない
  - → ユーザーに確認: 「MDLmakeから納期について質問がありました。希望納期を教えてください」

相手: 「OK」
AI秘書の判断:
  - 何に対するOKか不明確
  - → 自律的に確認: 「すみません、何についてのOKでしょうか？」
```

#### 会話コンテキスト管理

```
line_conversations テーブル:
- id: UUID
- user_id: UUID (AI秘書のユーザー)
- line_contact_id: VARCHAR (相手のLINE識別子)
- contact_name: VARCHAR (相手の表示名)
- original_task_id: UUID (発端となったタスク)
- context_summary: TEXT (AIによる会話要約)
- status: VARCHAR (active, resolved, waiting_user, waiting_reply)
- created_at, updated_at

line_messages テーブル:
- id: UUID
- conversation_id: UUID
- direction: VARCHAR (sent, received)
- content: TEXT
- ai_summary: TEXT (AIによる要約)
- ai_action_taken: VARCHAR (reported, auto_replied, waiting)
- created_at
```

### Phase 3: Credential Management

| # | API | Method | Description | Status |
|---|-----|--------|-------------|--------|
| 12 | `/api/v1/credentials` | POST | Store encrypted credentials | ❌ Not implemented |
| 13 | `/api/v1/credentials/{service}` | GET | Get credentials for service | ❌ Not implemented |
| 14 | `/api/v1/task/{id}/provide-credentials` | POST | Provide credentials for blocked task | ❌ Not implemented |

### Phase 4: User Preference Learning

| # | API | Method | Description | Status |
|---|-----|--------|-------------|--------|
| 15 | `/api/v1/preferences` | GET | Get user preferences | ❌ Not implemented |
| 16 | `/api/v1/preferences` | POST | Update user preferences | ❌ Not implemented |
| 17 | `/api/v1/task/{id}/feedback` | POST | Provide feedback on task execution | ❌ Not implemented |

### Phase 5: External Integrations

| # | API | Method | Description | Status |
|---|-----|--------|-------------|--------|
| 18 | `/webhook/line` | POST | LINE Webhook (receive messages) | ⏳ Code exists, needs config |

---

## API Details

### 2. POST /api/v1/wish

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

### 4. POST /api/v1/task/{id}/revise

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

### 5. POST /api/v1/task/{id}/confirm

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

### 14. POST /api/v1/task/{id}/provide-credentials (Phase 3)

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
System: [ACTION] Send LINE message to MDLmake for consultation
        [DETAILS] "Hello, I'm looking for a new PC for development work..."
        [NOTES] Assumed budget: $1,500. Correct if needed.
     ↓
User: Confirms → System sends LINE message
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

| Phase | APIs | Tested | Pending |
|-------|------|--------|---------|
| Phase 1 | 6 | 6 ✅ | 0 |
| Phase 2 | 4 | 0 | 4 (needs config) |
| Phase 2A | 8 APIs + 8 機能 | 0 | 16 (not implemented) |
| Phase 3 | 3 | 0 | 3 (not implemented) |
| Phase 4 | 3 | 0 | 3 (not implemented) |
| Phase 5 | 1 | 0 | 1 (needs config) |
| **Total** | **25+** | **6** | **19+** |

---

## Next Steps

1. **Phase 2A (優先)**: LINE代行コミュニケーション機能
   - PlaywrightでLINE操作の技術調査
   - 会話履歴テーブルの実装
   - ログイン・送信・受信の基本機能
   - 自律判断ロジックの実装
2. **Phase 2**: Email/Browser/Search ツールの接続
3. **Phase 3**: 資格情報管理フローの実装
4. **Phase 4**: ユーザー設定学習の実装
5. **Phase 5**: LINE Webhookの設定（公式アカウント経由の場合）

---

## Phase 2A 詳細設計

### 技術調査が必要な項目

1. **LINE操作方法の選定**
   - LINE PC版アプリ + PyAutoGUI/画像認識
   - LINE Web版（存在するか調査）
   - LINE公式アカウント管理画面 (manager.line.biz)
   - 他の方法

2. **メッセージ監視方法**
   - ポーリング（定期的に画面を確認）
   - 通知フック（OS通知を監視）
   - 他の方法

3. **セッション維持**
   - ログイン状態の永続化
   - 再認証の自動化

### 自律判断ロジック

AI秘書が相手からの返信を受け取った際の判断フロー:

```
受信メッセージ
    ↓
[分析] メッセージの意図を理解
    ↓
┌─────────────────────────────────────────────┐
│ 判断基準                                      │
├─────────────────────────────────────────────┤
│ 1. ユーザーに報告すべきか？                    │
│    - 重要な情報（価格、納期、確認事項）         │
│    - 決定が必要な内容                          │
│    → YES: ユーザーに要約して報告               │
│                                               │
│ 2. ユーザーへの確認が必要か？                  │
│    - 元の要望に含まれていない情報を求められた   │
│    → YES: ユーザーに確認を求める               │
│                                               │
│ 3. 相手の返信が不明確か？                      │
│    - 「OK」「了解」など文脈なしで意味不明       │
│    - 質問の意図が不明確                        │
│    → YES: 自律的に相手に確認返信               │
│                                               │
│ 4. 会話が完了したか？                          │
│    - 目的達成（予約完了、情報取得完了）         │
│    → YES: ユーザーに完了報告                   │
└─────────────────────────────────────────────┘
```

### セキュリティ考慮事項

- LINE認証情報は暗号化して保存
- 送信前に必ずユーザー承認を取得（アクションファースト原則）
- 自律返信はあらかじめ定義されたパターンのみ（確認質問など）
- センシティブな情報（支払い、個人情報）は自律送信しない
