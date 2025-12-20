# Phase 3B: Execution Engine（承認後の実行）

## 概要

Phase 3Aで検索・提案した内容を、ユーザーが承認したら**実際に予約・購入を実行**する。

### フロー全体像

```
Phase 3A（検索・提案）              Phase 3B（実行）
        │                                │
ユーザー：「新幹線予約したい」            │
        ↓                                │
Done：便を検索して提案                    │
  「17:00発 のぞみ47号を予約しますか？」  │
        ↓                                │
ユーザー：「OK、予約して」  ─────────────→ 実際にEX予約サイトで予約
        │                                ↓
        │                          Done：「予約完了しました」
        │                                │
        │                          (ログイン必要な場合)
        │                                ↓
        │                          Done：「ログイン情報が必要です」
        │                                ↓
        │                          ユーザー：認証情報を提供
        │                                ↓
        │                          Done：「予約完了しました」
```

---

## ユースケース

| # | カテゴリ | アクション | 実行内容 |
|---|---------|-----------|---------|
| 1 | 交通 | 新幹線予約 | EX予約/スマートEXで予約完了 |
| 2 | 交通 | 高速バス予約 | 高速バスネット等で予約完了 |
| 3 | 交通 | 航空券予約 | 航空会社サイト/スカイスキャナー経由で予約 |
| 4 | 買い物 | 商品購入 | Amazon/楽天等でカートに入れて購入 |
| 5 | 専門家 | 問い合わせ | 税理士ドットコム等でフォーム送信 |
| 6 | 飲食 | レストラン予約 | 食べログ/ホットペッパーで予約 |
| 7 | 汎用 | フォーム送信 | 任意のWebフォームに入力・送信 |

---

## Phase 3Aとの連携ポイント

### 検索サイトと購入サイトの分離

**重要**: 検索に使うサイトと実際に予約・購入するサイトは異なる場合がある。

| カテゴリ | 検索サイト（Phase 3A） | 購入/予約サイト（Phase 3B） |
|---------|----------------------|---------------------------|
| 新幹線 | Yahoo!乗換案内 | EX予約、スマートEX、えきねっと |
| 高速バス | 高速バスネット | 高速バスネット（同一） |
| 航空券 | Skyscanner | 各航空会社サイト（JAL、ANA等） |
| 商品 | 価格.com | Amazon、楽天（商品ページ直リンク） |
| 商品 | Amazon/楽天 | Amazon/楽天（同一） |

### 対応方針

1. **検索結果のURLは「情報元」として保持**
   - `url`: 検索結果の情報元URL（Yahoo!乗換案内など）
   
2. **購入先URLは`execution_params`で別途保持**
   - `execution_params.booking_url`: 実際に予約・購入するURL
   - `execution_params.service_name`: 使用するサービス名（"ex_reservation"等）

3. **Phase 3B実行時のURL解決ロジック**
   ```
   if execution_params.booking_url exists:
       → そのURLにアクセス
   elif category == "train":
       → EX予約/えきねっとのURLを生成（出発地・到着地・日時から）
   elif category == "product" and url contains amazon/rakuten:
       → そのままurlを使用（直接購入可能）
   elif category == "product" and url contains kakaku:
       → 最安ショップのURLを取得
   else:
       → urlにアクセス
   ```

### 検索時に取得すべき情報（Phase 3Aで対応）

Phase 3Bの実行に必要な情報を、Phase 3Aの検索段階で取得しておく：

| カテゴリ | 検索時に取得 | 実行時に使用 |
|---------|------------|-------------|
| 新幹線 | 便名、時刻、出発地、到着地、日付 | EX予約で検索・予約 |
| 高速バス | 便名、時刻、予約URL、空席状況 | URLを開いて予約フォーム入力 |
| 航空機 | 便名、時刻、航空会社、価格 | 航空会社サイトで予約 |
| 商品（Amazon/楽天） | 商品名、価格、商品URL | URLを開いてカートに入れる |
| 商品（価格.com） | 商品名、価格、最安ショップURL | ショップURLを開いてカートに入れる |
| 専門家 | 事務所名、問い合わせURL | URLを開いてフォーム入力 |

### 共通データ構造

```python
# Phase 3A検索結果 → Phase 3B実行入力
class SearchResult:
    id: str                    # 検索結果ID
    category: str              # "train" / "bus" / "flight" / "product" / etc.
    title: str                 # 表示名
    url: str                   # 実行時にアクセスするURL ← 重要
    price: Optional[int]       # 価格
    details: dict              # カテゴリ固有の詳細情報
    execution_params: dict     # 実行時に必要なパラメータ ← 重要

# 例: 新幹線の場合（Yahoo!乗換案内で検索 → EX予約で予約）
{
    "id": "train_001",
    "category": "train",
    "title": "のぞみ47号 17:00発",
    "url": "https://transit.yahoo.co.jp/...",  # 情報元（Yahoo!乗換案内）
    "price": 14500,
    "details": {
        "departure": "新大阪",
        "arrival": "博多",
        "date": "2024-12-28",
        "time": "17:00",
        "train_name": "のぞみ47号"
    },
    "execution_params": {
        "service_name": "ex_reservation",  # 予約に使うサービス
        "booking_url": null,               # EX予約は動的に生成するためnull
        "requires_login": true,
        "booking_params": {                # 予約時に使用するパラメータ
            "departure_station": "新大阪",
            "arrival_station": "博多",
            "date": "2024-12-28",
            "time": "17:00",
            "train_type": "のぞみ"
        }
    }
}

# 例: Amazon商品の場合（検索と購入が同一サイト）
{
    "id": "product_001",
    "category": "product",
    "title": "MacBook Air M3",
    "url": "https://www.amazon.co.jp/dp/XXXXX",  # 商品ページ（直接購入可能）
    "price": 164800,
    "details": {
        "seller": "Amazon.co.jp",
        "rating": 4.5,
        "review_count": 1234
    },
    "execution_params": {
        "service_name": "amazon",
        "booking_url": "https://www.amazon.co.jp/dp/XXXXX",  # urlと同じ
        "requires_login": true,
        "booking_params": {
            "asin": "XXXXX",
            "quantity": 1
        }
    }
}

# 例: 価格.comで検索した商品（購入は別サイト）
{
    "id": "product_002",
    "category": "product",
    "title": "MacBook Air M3",
    "url": "https://kakaku.com/item/XXXXX",  # 価格.comの商品ページ
    "price": 158000,
    "details": {
        "lowest_price_shop": "ビックカメラ.com",
        "lowest_price_url": "https://www.biccamera.com/..."
    },
    "execution_params": {
        "service_name": "external_shop",
        "booking_url": "https://www.biccamera.com/...",  # 最安ショップのURL
        "requires_login": true,
        "booking_params": {
            "shop_name": "ビックカメラ.com"
        }
    }
}
```

---

## 技術スタック

| レイヤー | 技術 | 理由 |
|---------|------|------|
| **ブラウザ自動化** | Playwright | Phase 3Aと統一、フル機能 |
| **認証情報管理** | AES-256暗号化 + Supabase | 既存の暗号化サービス活用 |
| **タスク実行** | Celery + Redis | 既存、非同期実行 |
| **状態管理** | Supabase (PostgreSQL) | タスク状態の永続化 |

---

## アーキテクチャ

```
┌─────────────────────────────────────────────────────────────┐
│                    POST /api/v1/task/{id}/confirm           │
│                    「この便を予約して」                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    実行エンジン                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  1. タスク情報取得                                    │   │
│  │     - 検索結果（Phase 3Aで保存済み）                   │   │
│  │     - 実行パラメータ                                  │   │
│  └─────────────────────────────────────────────────────┘   │
│                              │                              │
│                              ▼                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  2. 認証情報チェック                                  │   │
│  │     - 必要なサービスの認証情報があるか？              │   │
│  │     - なければ status: awaiting_credentials          │   │
│  └─────────────────────────────────────────────────────┘   │
│                              │                              │
│                              ▼                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  3. Playwright実行                                   │   │
│  │     - URLにアクセス                                   │   │
│  │     - ログイン（必要な場合）                          │   │
│  │     - フォーム入力                                    │   │
│  │     - 確認・送信                                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                              │                              │
│                              ▼                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  4. 結果確認                                         │   │
│  │     - 成功: 予約番号等を取得                          │   │
│  │     - 失敗: エラー内容を取得                          │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  レスポンス                                                  │
│  {                                                          │
│    "task_id": "uuid",                                       │
│    "status": "completed",                                   │
│    "execution_result": {                                    │
│      "success": true,                                       │
│      "confirmation_number": "ABC123",                       │
│      "message": "予約が完了しました"                         │
│    }                                                        │
│  }                                                          │
└─────────────────────────────────────────────────────────────┘
```

---

## 認証情報管理

### 対応サービス

| サービス | 認証方式 | 保存する情報 |
|---------|---------|-------------|
| EX予約/スマートEX | ID/パスワード | email, password |
| Amazon | ID/パスワード + 2FA | email, password, (OTP) |
| 楽天 | ID/パスワード | email, password |
| 高速バスネット | ID/パスワード | email, password |
| JAL/ANA | マイレージ番号/パスワード | member_id, password |

### 認証フロー

```
1. タスク実行時にログインが必要
       ↓
2. 保存済み認証情報をチェック
       ↓
   ┌─────────────────┐
   │ 認証情報あり？  │
   └────────┬────────┘
            │
   ┌────────┴────────┐
   ↓                 ↓
  あり              なし
   ↓                 ↓
  復号化         status: awaiting_credentials
   ↓              「ログイン情報が必要です」
  ログイン実行         ↓
   ↓             ユーザーが認証情報を提供
  タスク続行           ↓
                  暗号化して保存
                       ↓
                  タスク再開
```

### セキュリティ

| 項目 | 対策 |
|------|------|
| 暗号化 | AES-256-GCM（既存の encryption.py 活用） |
| 保存場所 | Supabase（RLSでユーザー別にアクセス制限） |
| 伝送 | HTTPS必須 |
| 表示 | パスワードはマスク表示（*****） |

---

## API一覧

### 既存API（Phase 1で実装済み、拡張が必要）

| # | API | Method | 変更内容 |
|---|-----|--------|---------|
| 1 | `/api/v1/task/{id}/confirm` | POST | 実際の実行ロジックを追加 |

### 新規API

| # | API | Method | 説明 |
|---|-----|--------|------|
| 2 | `/api/v1/credentials` | POST | 認証情報を暗号化して保存 |
| 3 | `/api/v1/credentials` | GET | 保存済みサービス一覧取得 |
| 4 | `/api/v1/credentials/{service}` | DELETE | 認証情報を削除 |
| 5 | `/api/v1/task/{id}/provide-credentials` | POST | タスク実行中に認証情報を提供 |
| 6 | `/api/v1/task/{id}/execution-status` | GET | 実行状況をリアルタイム取得 |

### API詳細

#### POST /api/v1/credentials

認証情報を暗号化して保存

**Request:**
```json
{
  "service": "ex_reservation",
  "credentials": {
    "email": "user@example.com",
    "password": "secret123"
  }
}
```

**Response:**
```json
{
  "success": true,
  "service": "ex_reservation",
  "message": "認証情報を保存しました"
}
```

#### POST /api/v1/task/{id}/provide-credentials

タスク実行中に認証情報を提供（awaiting_credentials状態のタスク用）

**Request:**
```json
{
  "service": "ex_reservation",
  "credentials": {
    "email": "user@example.com",
    "password": "secret123"
  },
  "save_credentials": true
}
```

**Response:**
```json
{
  "task_id": "uuid",
  "status": "executing",
  "message": "認証情報を受け取りました。実行を再開します。"
}
```

#### GET /api/v1/task/{id}/execution-status

実行状況をリアルタイム取得（ポーリング用）

**Response:**
```json
{
  "task_id": "uuid",
  "status": "executing",
  "progress": {
    "current_step": "logging_in",
    "steps_completed": ["opened_url", "entered_credentials"],
    "steps_remaining": ["submit_form", "confirm_booking"],
    "screenshot_url": "/screenshots/task_xxx_step2.png"
  }
}
```

---

## 実行ステップ詳細

### 例: 新幹線予約

```python
async def execute_train_booking(task: Task, credentials: Credentials):
    page = await get_page()
    
    # Step 1: 予約ページにアクセス
    await page.goto(task.search_result.url)
    update_progress("opened_url")
    
    # Step 2: ログイン（必要な場合）
    if await page.locator("#login-form").is_visible():
        await page.fill("#email", credentials.email)
        await page.fill("#password", credentials.password)
        await page.click("#login-button")
        await page.wait_for_navigation()
        update_progress("logged_in")
    
    # Step 3: 予約情報入力
    await page.fill("#date", task.details.date)
    await page.fill("#time", task.details.time)
    await page.fill("#from", task.details.departure)
    await page.fill("#to", task.details.arrival)
    await page.click("#search-button")
    update_progress("entered_details")
    
    # Step 4: 便を選択
    await page.click(f"text={task.details.train_name}")
    update_progress("selected_train")
    
    # Step 5: 確認・予約
    await page.click("#confirm-button")
    await page.wait_for_selector("#confirmation-number")
    update_progress("completed")
    
    # 予約番号を取得
    confirmation = await page.text_content("#confirmation-number")
    
    return {
        "success": True,
        "confirmation_number": confirmation,
        "message": f"予約完了: {confirmation}"
    }
```

---

## 実装ステップ

### Step 0: 基盤準備

| # | タスク | 説明 |
|---|--------|------|
| 0-1 | DBスキーマ拡張 | credentials テーブル追加 |
| 0-2 | 暗号化サービス確認 | 既存の encryption.py が使えるか確認 |

### Step 1: 認証情報管理

| # | タスク | 説明 |
|---|--------|------|
| 1-1 | POST /credentials | 認証情報保存API |
| 1-2 | GET /credentials | サービス一覧API |
| 1-3 | DELETE /credentials/{service} | 認証情報削除API |

### Step 2: 実行エンジン

| # | タスク | 説明 |
|---|--------|------|
| 2-1 | 実行フレームワーク | 共通の実行ロジック |
| 2-2 | 認証フロー | ログイン処理の共通化 |
| 2-3 | 進捗管理 | ステップごとの進捗更新 |

### Step 3: サービス別実行ロジック

| # | タスク | 説明 |
|---|--------|------|
| 3-1 | 新幹線予約（EX予約） | 予約フロー実装 |
| 3-2 | 高速バス予約 | 予約フロー実装 |
| 3-3 | EC購入（Amazon） | 購入フロー実装 |
| 3-4 | EC購入（楽天） | 購入フロー実装 |

### Step 4: API統合

| # | タスク | 説明 |
|---|--------|------|
| 4-1 | confirm API拡張 | 実際の実行ロジック接続 |
| 4-2 | provide-credentials API | 認証情報提供API |
| 4-3 | execution-status API | 実行状況取得API |

### Step 5: テスト・検証

| # | タスク | 説明 |
|---|--------|------|
| 5-1 | 単体テスト | 各実行ロジックのテスト |
| 5-2 | 統合テスト | 検索→承認→実行の一連フロー |
| 5-3 | 手動テスト | 実際のサービスでの動作確認 |

---

## ファイル構成（新規・変更）

```
app/
├── api/
│   ├── routes.py                # 変更: 新API追加
│   └── credentials_routes.py    # 新規: 認証情報API
├── services/
│   ├── encryption.py            # 既存（活用）
│   ├── credentials_service.py   # 新規: 認証情報管理
│   └── execution_service.py     # 新規: 実行エンジン
├── executors/                   # 新規: サービス別実行ロジック
│   ├── __init__.py
│   ├── base.py                  # 共通実行ロジック
│   ├── train_executor.py        # 新幹線予約
│   ├── bus_executor.py          # 高速バス予約
│   ├── flight_executor.py       # 航空券予約
│   ├── amazon_executor.py       # Amazon購入
│   └── rakuten_executor.py      # 楽天購入
├── models/
│   └── schemas.py               # 変更: Credential, ExecutionResult追加
└── tools/
    └── browser.py               # 変更: 共通ログイン処理追加
```

---

## DBスキーマ（追加）

```sql
-- ユーザー認証情報（暗号化して保存）
CREATE TABLE user_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) NOT NULL,
    service VARCHAR(50) NOT NULL,           -- "ex_reservation", "amazon", etc.
    encrypted_data TEXT NOT NULL,            -- AES-256暗号化されたJSON
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, service)
);

-- RLS有効化
ALTER TABLE user_credentials ENABLE ROW LEVEL SECURITY;

-- ユーザー自身のみアクセス可能
CREATE POLICY "Users can manage own credentials"
    ON user_credentials
    FOR ALL
    USING (auth.uid() = user_id);

-- 実行ログ
CREATE TABLE execution_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID REFERENCES tasks(id) NOT NULL,
    step VARCHAR(50) NOT NULL,               -- "opened_url", "logged_in", etc.
    status VARCHAR(20) NOT NULL,             -- "success", "failed"
    details JSONB,
    screenshot_path TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## リスクと対策

| リスク | 対策 |
|--------|------|
| サイト構造変更で実行失敗 | セレクタを設定ファイル化、失敗時にスクリーンショット保存 |
| 2段階認証 | OTP入力をユーザーに依頼する仕組み |
| CAPTCHA | 検出したらユーザーに手動対応を依頼 |
| 決済エラー | 決済前に確認ステップ、エラー時のロールバック |
| 認証情報漏洩 | AES-256暗号化、RLSによるアクセス制限 |

---

## セキュリティ考慮事項

### 認証情報の取り扱い

1. **暗号化**: AES-256-GCMで暗号化してから保存
2. **復号化**: 実行時のみ復号化、メモリ上で使用後即座に破棄
3. **アクセス制御**: RLSでユーザー本人のみアクセス可能
4. **監査ログ**: 認証情報の使用をログに記録

### 決済の安全性

1. **確認ステップ**: 決済前に必ずユーザー確認
2. **金額上限**: 設定可能な金額上限
3. **ホワイトリスト**: 許可されたサービスのみ実行可能

---

## 成功基準

| # | 基準 | 検証方法 |
|---|------|---------|
| 1 | 認証情報を安全に保存・取得できる | 自動テスト |
| 2 | EX予約で新幹線を予約できる | 手動テスト（テスト環境） |
| 3 | Amazonで商品をカートに入れられる | 手動テスト |
| 4 | 実行中の進捗が確認できる | 手動テスト |
| 5 | 認証情報が必要な場合に適切に要求される | 自動テスト |
| 6 | エラー時にスクリーンショットが保存される | 自動テスト |

---

## Phase 3A/3B 連携まとめ

| 項目 | Phase 3A（検索） | Phase 3B（実行） |
|------|-----------------|-----------------|
| 目的 | 実データを検索して提案 | 承認後に実際に実行 |
| 技術 | Playwright + Tavily | Playwright + Celery |
| 出力 | SearchResult（URL含む） | ExecutionResult |
| 状態 | proposed | executing → completed |

### データの流れ

```
Phase 3A                      Phase 3B
    │                             │
 検索実行                         │
    ↓                             │
 SearchResult生成                 │
  - url ──────────────────────→ URLにアクセス
  - execution_params ─────────→ フォーム入力に使用
    │                             │
 タスク保存（proposed）           │
    │                             │
    │←─── confirm API ───────────│
    │                             ↓
    │                        実行開始
    │                             ↓
    │                        ExecutionResult
    │                             ↓
    │                        タスク更新（completed）
```

---

## 次のステップ

Phase 3AとPhase 3Bの仕様が完成したので、以下の順で実装：

1. **Phase 3A API一覧・テスト作成**
2. **Phase 3A 実装**（1件ずつ動作確認・コミット）
3. **Phase 3B API一覧・テスト作成**
4. **Phase 3B 実装**（1件ずつ動作確認・コミット）
