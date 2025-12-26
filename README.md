# AI Secretary System / AI秘書システム

「○○したい」という願望に対して提案・実行してくれるAI秘書システムです。

## 開発状況

### ✅ 動作確認済み（2024年12月26日）

**🔄 最新更新（2024年12月26日）**:
- バックエンドメッセージを英語に統一（国際化対応）
- Playwright Windows互換性修正（専用スレッド方式）
- **Travel Fallback機能追加**: バスが見つからない場合に電車・飛行機など代替手段を自動提案
- **WILLER高速バス予約の実機テスト成功**: 梅田→米子（2025年1月5日）の予約確認画面まで到達

#### Phase 1: Core Flow
| 機能 | API | 状態 |
|-----|-----|------|
| タスク一覧を見る | `GET /api/v1/tasks` | ✅ 動作確認済み |
| お願いを送る | `POST /api/v1/wish` | ✅ 動作確認済み |
| お願いの状況を確認 | `GET /api/v1/task/{id}` | ✅ 動作確認済み |
| お願いを実行する | `POST /api/v1/task/{id}/confirm` | ✅ 動作確認済み |
| ヘルスチェック | `GET /` | ✅ 動作確認済み |
| 日本語アクションファースト提案 | `POST /api/v1/wish` | ✅ 動作確認済み |
| LINE Webhook | `POST /webhook/line` | ⏸️ LINE設定後にテスト可能 |

#### Phase 2: Done Chat（AIネイティブチャット）

**🔄 ユーザーテーブル統合完了（2024年12月26日）**
- `chat_users` テーブルを `users` テーブルに統合
- 全チャットユーザー = Doneユーザー
- 詳細: `docs/phase2_chat_system.md`

| 機能 | API | 状態 |
|-----|-----|------|
| ユーザー登録 | `POST /api/v1/chat/register` | ✅ 動作確認済み |
| ログイン | `POST /api/v1/chat/login` | ✅ 動作確認済み |
| プロフィール取得 | `GET /api/v1/chat/me` | ✅ 動作確認済み |
| プロフィール更新 | `PATCH /api/v1/chat/me` | ✅ 動作確認済み |
| 招待リンク発行 | `POST /api/v1/chat/invite` | ✅ 動作確認済み |
| 招待情報取得 | `GET /api/v1/chat/invite/{code}` | ✅ 動作確認済み |
| 招待承諾 | `POST /api/v1/chat/invite/{code}/accept` | ✅ 動作確認済み |
| 友達一覧 | `GET /api/v1/chat/friends` | ✅ 動作確認済み |
| 友達削除 | `DELETE /api/v1/chat/friends/{id}` | ✅ 動作確認済み |
| ルーム一覧 | `GET /api/v1/chat/rooms` | ✅ 動作確認済み |
| ルーム作成 | `POST /api/v1/chat/rooms` | ✅ 動作確認済み |
| ルーム詳細 | `GET /api/v1/chat/rooms/{id}` | ✅ 動作確認済み |
| ルーム更新 | `PATCH /api/v1/chat/rooms/{id}` | ✅ 動作確認済み |
| メンバー一覧 | `GET /api/v1/chat/rooms/{id}/members` | ✅ 動作確認済み |
| メンバー追加 | `POST /api/v1/chat/rooms/{id}/members` | ✅ 動作確認済み |
| メッセージ送信 | `POST /api/v1/chat/rooms/{id}/messages` | ✅ 動作確認済み |
| メッセージ取得 | `GET /api/v1/chat/rooms/{id}/messages` | ✅ 動作確認済み |
| 既読マーク | `POST /api/v1/chat/rooms/{id}/read` | ✅ 動作確認済み |
| AI設定取得 | `GET /api/v1/chat/rooms/{id}/ai` | ✅ 動作確認済み |
| AI設定更新 | `PATCH /api/v1/chat/rooms/{id}/ai` | ✅ 動作確認済み |
| AI要約取得 | `GET /api/v1/chat/rooms/{id}/ai/summary` | ✅ 動作確認済み |
| WebSocket | `WS /api/v1/chat/ws/chat` | ✅ 動作確認済み |
| **ダンルーム取得** | `GET /api/v1/chat/dan` | ✅ **実装済み（2024年12月26日）** |
| **ダンメッセージ取得** | `GET /api/v1/chat/dan/messages` | ✅ **実装済み** |
| **ダンにメッセージ送信** | `POST /api/v1/chat/dan/messages` | ✅ **実装済み** |
| **ダン既読マーク** | `POST /api/v1/chat/dan/read` | ✅ **実装済み** |
| **提案一覧取得** | `GET /api/v1/chat/proposals` | ✅ **実装済み** |
| **提案詳細取得** | `GET /api/v1/chat/proposals/{id}` | ✅ **実装済み** |
| **提案に対応** | `POST /api/v1/chat/proposals/{id}/respond` | ✅ **実装済み** |

#### Phase 3A: Smart Proposal（リアルタイム検索提案）
| 機能 | ツール | 状態 |
|-----|--------|------|
| Tavily汎用検索 | `tavily_search` | ✅ 動作確認済み |
| 電車・新幹線検索 | `search_train` (Yahoo!乗換案内) | ✅ 動作確認済み |
| 高速バス検索 | `search_bus` (高速バスネット) | ✅ 動作確認済み |
| 航空機検索 | `search_flight` (スカイスキャナー) | ✅ 動作確認済み |
| Amazon商品検索 | `search_amazon` | ✅ 動作確認済み |
| 楽天商品検索 | `search_rakuten` | ✅ 動作確認済み |
| 価格.com検索 | `search_kakaku` | ✅ 動作確認済み |
| エージェント統合 | `agent.py` で検索結果を提案に反映 | ✅ 動作確認済み |

#### Phase 3B: Execution Engine（実行エンジン）
| 機能 | API | 説明 | 状態 |
|-----|-----|------|------|
| ログイン情報を保存 | `POST /api/v1/credentials` | Amazon、新幹線予約サイトなどのログイン情報を暗号化して保存。毎回入力不要に | ✅ 動作確認済み |
| 保存済みサービス一覧 | `GET /api/v1/credentials` | どのサービスのログイン情報が保存されているか確認 | ✅ 動作確認済み |
| ログイン情報を削除 | `DELETE /api/v1/credentials/{service}` | 不要になったサービスのログイン情報を削除 | ✅ 動作確認済み |
| 実行中にログイン情報提供 | `POST /api/v1/task/{id}/provide-credentials` | ログインまたは新規登録を選択可能。新規登録時はパスワード自動生成 | ✅ 動作確認済み |
| 実行状況をリアルタイム確認 | `GET /api/v1/task/{id}/execution-status` | 予約・購入の進捗。認証必要時はauth_optionsでフィールド情報を返す | ✅ 動作確認済み |

#### Phase 3B: サービス別実行ロジック（Executor）
| サービス | 機能 | 状態 |
|---------|------|------|
| Amazon | 商品をカートに追加（Playwrightによる自動操作） | ✅ 動作確認済み |
| 楽天 | 商品をカートに追加（Playwrightによる自動操作） | ✅ 動作確認済み |
| EX予約 | 新幹線チケット予約（SmartEX実サイト調査済み・OTP認証対応） | ✅ 動作確認済み |
| 高速バス（WILLER） | バス予約（実サイト調査済み・新規登録対応・チャット連携済み） | ✅ **実機テスト成功（2024年12月26日）** |
| **Travel Fallback** | バス/電車が見つからない場合に代替手段を自動提案 | ✅ **新規追加（2024年12月26日）** |

#### Phase 4: Credential Management（認証情報管理）
| 機能 | API | 状態 |
|-----|-----|------|
| 認証情報保存 | `POST /api/v1/credentials` | ✅ 完了 |
| 認証情報取得 | `GET /api/v1/credentials` | ✅ 完了 |
| 認証情報削除 | `DELETE /api/v1/credentials/{service}` | ✅ 完了 |
| 暗号化保存 | AES-256-GCM | ✅ 完了 |

#### Phase 5: Message Detection（メッセージ検知）✅ 動作確認済み（2024年12月22日）
| 機能 | API | 状態 |
|-----|-----|------|
| Gmail連携状態確認 | `GET /api/v1/gmail/status` | ✅ 動作確認済み |
| Gmail OAuth開始 | `POST /api/v1/gmail/setup` | ✅ 動作確認済み |
| Gmail手動同期 | `POST /api/v1/gmail/sync` | ✅ 動作確認済み |
| Gmail連携解除 | `DELETE /api/v1/gmail/disconnect` | ✅ 動作確認済み |
| 検知メッセージ一覧 | `GET /api/v1/detection/messages` | ✅ 動作確認済み |
| 検知メッセージ詳細 | `GET /api/v1/detection/messages/{id}` | ✅ 動作確認済み |
| 添付ファイル一覧 | `GET /api/v1/detection/messages/{id}/attachments` | ✅ 動作確認済み |
| 添付ファイル取得 | `POST /api/v1/detection/messages/{id}/download-attachments` | ✅ 動作確認済み |
| 添付ファイルDL | `GET /api/v1/detection/attachments/{id}` | ✅ 動作確認済み |
| Doneチャット検知 | ChatService内フック（AI有効ルーム自動検知） | ✅ 動作確認済み |

#### Phase 6: Content Intelligence（コンテンツ解析）✅ 動作確認済み（2024年12月22日）
| 機能 | API | 状態 |
|-----|-----|------|
| PDF解析 | `POST /api/v1/content/extract/pdf` | ✅ 動作確認済み |
| 画像OCR | `POST /api/v1/content/extract/image` | ✅ 動作確認済み |
| URL先取得 | `POST /api/v1/content/extract/url` | ✅ 動作確認済み |
| コンテンツ分類 | `POST /api/v1/content/classify` | ✅ 動作確認済み |
| 添付ファイル解析 | `POST /api/v1/content/analyze/attachment/{id}` | ✅ 動作確認済み |
| メッセージ解析 | `POST /api/v1/content/analyze/message/{id}` | ✅ 動作確認済み |

#### Phase 7: Invoice Management（請求書管理）✅ 動作確認済み
| 機能 | API/サービス | 状態 |
|-----|-------------|------|
| 請求書情報抽出 | `InvoiceExtractor` (7A) | ✅ 動作確認済み（2024年12月23日） |
| スケジュール計算 | `ScheduleCalculator` (7B) | ✅ 動作確認済み（2024年12月23日） |
| 請求書作成API | `POST /api/v1/invoices` (7C) | ✅ 動作確認済み（2024年12月23日） |
| 請求書一覧API | `GET /api/v1/invoices` (7C) | ✅ 動作確認済み（2024年12月23日） |
| 請求書承認API | `POST /api/v1/invoices/{id}/approve` (7C) | ✅ 動作確認済み（2024年12月23日） |
| 請求書却下API | `POST /api/v1/invoices/{id}/reject` (7C) | ✅ 動作確認済み（2024年12月23日） |
| 支払いスケジューラ | Celery Beat (7D) | ✅ 動作確認済み（2024年12月23日） |

#### Phase 8: Payment Execution（支払い実行）✅ 動作確認済み
| 機能 | API | 状態 |
|-----|-----|------|
| 振込先作成 | `POST /api/v1/bank-accounts` (8B) | ✅ 動作確認済み（2024年12月23日） |
| 振込先一覧取得 | `GET /api/v1/bank-accounts` (8B) | ✅ 動作確認済み（2024年12月23日） |
| 振込先詳細取得 | `GET /api/v1/bank-accounts/{id}` (8B) | ✅ 動作確認済み（2024年12月23日） |
| 振込先削除 | `DELETE /api/v1/bank-accounts/{id}` (8B) | ✅ 動作確認済み（2024年12月23日） |
| 振込先検証 | `POST /api/v1/bank-accounts/{id}/verify` (8B) | ✅ 動作確認済み（2024年12月23日） |
| 銀行振込Executor | `BankTransferExecutor` (8A) | ✅ 動作確認済み（2024年12月23日） |
| 支払い実行API | `POST /api/v1/invoices/{id}/pay` (8A) | ✅ 動作確認済み（2024年12月23日） |
| 支払い状況確認API | `GET /api/v1/invoices/{id}/payment-status` (8A) | ✅ 動作確認済み（2024年12月23日） |

#### Phase 9: OTP Automation（OTP自動化）✅ 動作確認済み
| 機能 | API | 状態 |
|-----|-----|------|
| メールOTP抽出 | `POST /api/v1/otp/extract/email` (9A) | ✅ 動作確認済み（2024年12月23日） |
| 最新OTP取得 | `GET /api/v1/otp/latest` (9A) | ✅ 動作確認済み（2024年12月23日） |
| OTP使用済みマーク | `POST /api/v1/otp/{id}/mark-used` (9A) | ✅ 動作確認済み（2024年12月23日） |
| OTP履歴取得 | `GET /api/v1/otp/history` (9A) | ✅ 動作確認済み（2024年12月23日） |
| SMS設定状態確認 | `GET /api/v1/otp/sms/status` (9B) | ✅ 動作確認済み（2024年12月23日） |
| SMS Webhook受信 | `POST /api/v1/otp/sms/webhook` (9B) | ✅ 動作確認済み（2024年12月23日） |
| SMS OTP抽出 | `POST /api/v1/otp/extract/sms` (9B) | ✅ 動作確認済み（2024年12月23日） |
| **音声OTP抽出** | `POST /api/v1/otp/extract/voice` (9C) | ✅ **動作確認済み（2024年12月25日）** |
| Executor OTP統合 | `BaseExecutor._handle_otp_challenge()` (9D) | ✅ 動作確認済み（2024年12月23日） |

#### Phase 10: Voice Communication（音声通話）✅ 動作確認済み（2024年12月25日）
| 機能 | API | 状態 |
|-----|-----|------|
| 音声設定取得 | `GET /api/v1/voice/settings` (10A) | ✅ 動作確認済み |
| 音声設定更新 | `PATCH /api/v1/voice/settings` (10A) | ✅ 動作確認済み |
| 受電オン/オフ | `PATCH /api/v1/voice/inbound` (10A) | ✅ 動作確認済み |
| 電話番号ルール一覧 | `GET /api/v1/voice/rules` (10D) | ✅ 動作確認済み |
| 電話番号ルール追加 | `POST /api/v1/voice/rules` (10D) | ✅ 動作確認済み |
| 電話番号ルール削除 | `DELETE /api/v1/voice/rules/{id}` (10D) | ✅ 動作確認済み |
| 通話履歴取得 | `GET /api/v1/voice/calls` (10B) | ✅ 動作確認済み |
| 通話詳細取得 | `GET /api/v1/voice/call/{id}` (10B) | ✅ 動作確認済み |
| 架電開始 | `POST /api/v1/voice/call` (10B) | ✅ 動作確認済み |
| 通話終了 | `POST /api/v1/voice/call/{id}/end` (10B) | ✅ 動作確認済み |
| 受電Webhook | `POST /api/v1/voice/webhook/incoming` (10C) | ✅ 動作確認済み |
| 通話状態Webhook | `POST /api/v1/voice/webhook/status` (10B) | ✅ 動作確認済み |
| 架電TwiML Webhook | `POST /api/v1/voice/webhook/outbound` (10B) | ✅ 動作確認済み |
| **Media Streams WebSocket** | `WS /api/v1/voice/stream/{call_sid}` (10E) | ✅ **動作確認済み** |
| **音声フォーマット変換** | μ-law ↔ PCM, リサンプリング (10E) | ✅ **動作確認済み** |
| **ElevenLabs STT連携** | 音声→テキスト変換 (10E) | ✅ **動作確認済み** |
| **ElevenLabs TTS連携** | テキスト→音声変換 (10E) | ✅ **動作確認済み** |
| **Claude応答生成** | AI会話応答 (10E) | ✅ **動作確認済み** |
| **双方向AI音声会話** | STT→Claude→TTSパイプライン (10E) | ✅ **動作確認済み** |
| **エージェント架電** | VoiceExecutor (10F) | ✅ **動作確認済み** |
| **通話チャット通知** | VoiceService.notify_chat (10F) | ✅ **動作確認済み** |

**技術スタック**: Twilio Voice + Twilio Media Streams + ElevenLabs + Claude

**実現した機能**:
- 📞 Twilioを使った電話発信・着信
- 🔌 Media Streams WebSocketによるリアルタイム音声ストリーム
- 🎤 ElevenLabs STT（日本語音声認識）
- 🔊 ElevenLabs TTS（日本語音声合成、μ-law変換対応）
- 🤖 Claude応答生成（音声会話用簡潔応答）
- 🗣️ 双方向AI音声会話（無音検知、会話履歴、要約）
- 🤖 AIエージェント「ダン」が日本語で応答
- 🔄 今後の改良: 音声の自然さ向上、レスポンス速度改善

**必要な設定**:
- `TWILIO_ACCOUNT_SID`: TwilioアカウントSID
- `TWILIO_AUTH_TOKEN`: Twilio認証トークン
- `TWILIO_PHONE_NUMBER`: Twilio電話番号（050-xxxx-xxxx形式）
- `ELEVENLABS_API_KEY`: ElevenLabs APIキー
- `VOICE_WEBHOOK_BASE_URL`: Webhook受信URL（ngrok等）

### 🔧 現在の状態

- **アクションファースト提案**: 完成 ✅
  - 質問せずに仮説を立てて具体的なアクションを提案
  - 【アクション】【詳細】【補足】のフォーマットで回答
  - ユーザーは提案を見てから訂正する方式
- **承認フローの土台**: 完成 ✅
  - すべてのリクエストは自動実行されず、ユーザー承認を待つ
- **チャット→Executor連携**: 完成 ✅
  - チャットで「予約して」→確認→Executorが自動でブラウザ操作
  - タスクタイプ（TRAVEL/PURCHASE）に応じて適切なExecutorを選択
- **認証フロー（ログイン/新規登録）**: 完成 ✅
  - 認証情報が保存済み → 自動ログイン
  - 認証情報がない → ログインフィールドと新規登録フィールドを動的に表示
  - 新規登録時はセキュアなパスワードを自動生成（編集可能）
  - 入力された認証情報は次回から自動使用のため保存
- **ブラウザ自動操作（Playwright）**: 完成 ✅
  - WILLER高速バス予約: 検索→日付選択→バス選択→予約確認画面まで自動操作
  - 主要都市・都道府県のURLマッピング対応（47都道府県+主要都市）
- **その他の連携**: 設定が必要 🔧
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
| `/api/v1/task/{id}/execution-status` | GET | 実行状況をリアルタイム取得 |
| `/api/v1/task/{id}/provide-credentials` | POST | 実行中に認証情報を提供 |
| `/api/v1/tasks` | GET | タスク一覧を取得 |
| `/api/v1/credentials` | POST | 認証情報を保存 |
| `/api/v1/credentials` | GET | 保存済みサービス一覧 |
| `/api/v1/credentials/{service}` | DELETE | 認証情報を削除 |
| `/webhook/line` | POST | LINE Webhook |

### 使用例

```bash
# 願望を送信 (bash/curl)
curl -X POST http://localhost:8000/api/v1/wish \
  -H "Content-Type: application/json" \
  -d '{"wish": "PCを新調したい"}'
```

```powershell
# 願望を送信 (PowerShell)
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/wish" -Method POST -ContentType "application/json" -Body '{"wish": "PCを新調したい"}'
```

```json
// レスポンス例（アクションファースト）
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Action proposed. Please confirm to execute, or request revisions.",
  "proposed_actions": ["MDLmakeにLINEで相談メッセージを送信します。"],
  "proposal_detail": "【アクション】\nMDLmakeにLINEで相談メッセージを送信します。\n\n【詳細】\n「お世話になっております。PCの新調を検討しています...」\n\n【補足】\n予算や用途は仮定です。訂正があればお知らせください。",
  "requires_confirmation": true
}
```

**アクションファースト原則**:
- AIは質問せずに仮説を立てて具体的なアクションを提案
- ユーザーは提案を見てから「17時じゃなくて16時にして」と訂正可能
- すべての願望に対して承認を待ってから実行

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
│   │   ├── credentials_service.py # 認証情報管理（Phase 3B）
│   │   ├── execution_service.py # 実行エンジン（Phase 3B）
│   │   ├── dynamic_auth.py  # 動的認証/新規登録サービス（Phase 3C）
│   │   └── supabase_client.py # DB操作
│   ├── executors/           # Phase 3B: サービス別実行ロジック
│   │   ├── __init__.py
│   │   ├── base.py          # 共通実行ロジック・ファクトリー
│   │   ├── amazon_executor.py # Amazon購入（カート追加）
│   │   ├── rakuten_executor.py # 楽天購入（カート追加）
│   │   ├── ex_reservation_executor.py # EX予約（新幹線予約）
│   │   └── highway_bus_executor.py # WILLER高速バス予約
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

## テスト

### テスト実行

```bash
# 全テスト実行
python -m pytest tests/ -v

# Windows (バッチファイル)
run_tests.bat

# PowerShell
.\run_tests.ps1
```

### 開発フロー（必ず守ること）

新しいAPIを追加する際は、以下のフローで進めてください：

```
1. API実装
    ↓
2. 手動でAPIをテスト（ターミナルでcurl/Invoke-RestMethod）
    ↓
3. 成功したら → 自動テストが通るか確認（pytest）
    ↓
4. 自動テストが通ったら → README.mdを更新
    ↓
5. コミット（1 API = 1 コミット）
```

**重要なポイント：**
- 手動で成功したテストは必ず自動テストに組み込む
- 自動テストが通らないとコミットしない
- README.mdは常に最新の状態を保つ
- 1つのAPIごとにコミットする（まとめてコミットしない）

### 自動テストについて

- 動作確認済みのAPIは `tests/` 以下に自動テスト化されています
- コミット前にテストが自動実行されます（pre-commit hook）
- 新しい機能を追加したら、対応するテストも追加してください

## セキュリティ注意事項

- **認証情報の暗号化**: クレジットカード情報やパスワードはAES-256で暗号化して保存
- **二段階承認**: 高額決済や重要な操作は実行前にユーザー確認を実施
- **監査ログ**: 全ての自動操作をログに記録
- **LINE個人アカウント**: 個人アカウントの自動操作はLINE利用規約に抵触する可能性があります
- **銀行サイト**: 金融機関によっては自動操作が禁止されています

## ライセンス

MIT License

