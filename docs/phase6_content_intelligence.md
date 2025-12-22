# Phase 6: Content Intelligence（コンテンツ解析）

## 概要

メール、添付ファイル、URLなどからコンテンツを抽出・解析し、自動的に分類するシステム。

### サブフェーズ

| Sub | 機能 | 説明 | 状態 |
|-----|------|------|------|
| 6A | PDF解析 | PDFからテキスト抽出（pdfplumber使用） | ✅ 完了 |
| 6B | 画像OCR | 画像からテキスト抽出（Tesseract/Google Vision） | ✅ 完了 |
| 6C | URL先取得 | URLにアクセスしてページ内容を取得（Playwright） | ✅ 完了 |
| 6D | コンテンツ分類AI | 文章から請求書・OTP・通知等を判定（Claude） | ✅ 完了 |

---

## アーキテクチャ

```
┌─────────────────────────────────────────────────────────────┐
│                   Content Intelligence                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐   │
│  │ PDFExtractor  │  │ OCRExtractor  │  │ URLExtractor  │   │
│  │ (pdfplumber)  │  │ (Tesseract/   │  │ (Playwright)  │   │
│  │               │  │  Vision API)  │  │               │   │
│  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘   │
│          │                  │                  │            │
│          └─────────────┬────┴──────────────────┘            │
│                        ▼                                     │
│              ┌─────────────────┐                            │
│              │ContentClassifier│                            │
│              │  (Claude API)   │                            │
│              └────────┬────────┘                            │
│                       ▼                                      │
│              ┌─────────────────┐                            │
│              │Classification   │                            │
│              │Result           │                            │
│              └─────────────────┘                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 6A: PDF解析

### 機能

- PDFファイルからテキストを抽出
- ページごとのテキスト取得
- テーブルデータの抽出

### 使用ライブラリ

- **pdfplumber**: メインの抽出エンジン

### API

```python
async def extract_text_from_pdf(file_data: bytes, filename: str = "") -> PDFExtractionResult
```

### レスポンス例

```json
{
  "success": true,
  "text": "請求書\n株式会社テスト...",
  "method": "pdf_pdfplumber",
  "page_count": 2,
  "pages": ["1ページ目のテキスト", "2ページ目のテキスト"],
  "tables": [
    {"page": 1, "data": [["項目", "金額"], ["商品A", "1000"]]}
  ],
  "confidence": 0.95,
  "processing_time_ms": 150
}
```

---

## 6B: 画像OCR

### 機能

- 画像からテキストを抽出
- 日本語/英語対応
- 単語位置情報の取得

### OCRプロバイダ

| プロバイダ | 設定値 | 特徴 |
|-----------|--------|------|
| Tesseract | `tesseract` | 無料、ローカル実行、要インストール |
| Google Vision | `google_vision` | 高精度、クラウド、有料 |

### 設定（.env）

```env
# OCRプロバイダ選択
OCR_PROVIDER=tesseract  # または google_vision

# Tesseract設定
TESSERACT_CMD=/usr/bin/tesseract  # Windowsの場合パスを指定

# Google Vision設定（使用する場合）
GOOGLE_CLOUD_PROJECT_ID=your-project-id
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

### API

```python
async def extract_text_from_image(file_data: bytes, language: str = "jpn+eng") -> OCRExtractionResult
```

---

## 6C: URL先コンテンツ取得

### 機能

- URLにアクセスしてテキストコンテンツを取得
- JavaScript実行後のコンテンツ取得（SPA対応）
- リダイレクト追跡
- メインコンテンツの自動検出

### 使用ライブラリ

- **Playwright**: ヘッドレスブラウザ

### API

```python
async def extract_text_from_url(
    url: str,
    wait_for_selector: Optional[str] = None,
    timeout_ms: int = 30000
) -> URLExtractionResult
```

### レスポンス例

```json
{
  "success": true,
  "text": "ページのメインコンテンツ...",
  "method": "url_playwright",
  "title": "ページタイトル",
  "url": "https://example.com/page",
  "final_url": "https://example.com/redirected-page",
  "confidence": 0.9,
  "processing_time_ms": 2500
}
```

---

## 6D: コンテンツ分類AI

### 機能

- テキストをカテゴリに分類
- 構造化データの抽出
- 信頼度スコアの算出

### カテゴリ一覧

| カテゴリ | 説明 | 抽出データ |
|---------|------|----------|
| `invoice` | 請求書 | 金額、期日、振込先、発行元 |
| `receipt` | 領収書 | 金額、日付、発行元 |
| `otp` | 認証コード | コード、サービス名、有効期限 |
| `confirmation` | 確認メール | 確認番号、タイプ、詳細 |
| `notification` | 通知 | - |
| `newsletter` | メルマガ | - |
| `personal` | 個人メッセージ | - |
| `spam` | スパム | - |
| `unknown` | 不明 | - |

### 信頼度レベル

| レベル | スコア範囲 |
|--------|-----------|
| HIGH | 90%以上 |
| MEDIUM | 70-90% |
| LOW | 50-70% |
| UNCERTAIN | 50%未満 |

### API

```python
async def classify_content(
    text: str,
    subject: Optional[str] = None,
    sender: Optional[str] = None,
) -> ClassificationResult
```

### レスポンス例（請求書）

```json
{
  "category": "invoice",
  "confidence": "high",
  "confidence_score": 0.95,
  "reasoning": "支払期日、振込先情報、請求金額が含まれているため",
  "extracted_data": {
    "amount": 50000,
    "currency": "JPY",
    "due_date": "2024-01-31",
    "invoice_number": "INV-2024-001",
    "issuer_name": "株式会社テスト",
    "bank_info": {
      "bank_name": "みずほ銀行",
      "branch": "本店",
      "account_type": "普通",
      "account_number": "1234567"
    }
  },
  "secondary_categories": []
}
```

---

## API エンドポイント

### PDF抽出

```
POST /api/v1/content/extract/pdf
Content-Type: multipart/form-data

- file: PDFファイル
- classify: 分類も行うか（デフォルト: true）
```

### 画像OCR

```
POST /api/v1/content/extract/image
Content-Type: multipart/form-data

- file: 画像ファイル（PNG, JPEG, GIF）
- language: OCR言語（デフォルト: jpn+eng）
- classify: 分類も行うか（デフォルト: true）
```

### URL抽出

```
POST /api/v1/content/extract/url
Content-Type: application/json

{
  "url": "https://example.com/page",
  "wait_for_selector": ".content",  // オプション
  "timeout_ms": 30000
}
```

### テキスト分類

```
POST /api/v1/content/classify
Content-Type: application/json

{
  "text": "分類するテキスト",
  "subject": "件名",  // オプション
  "sender": "送信者"  // オプション
}
```

### 添付ファイル解析

```
POST /api/v1/content/analyze/attachment/{attachment_id}
?classify=true
```

### 検知メッセージ解析

```
POST /api/v1/content/analyze/message/{message_id}
?include_attachments=true
```

### バッチ解析

```
POST /api/v1/content/analyze/batch
Content-Type: application/json

{
  "message_ids": ["id1", "id2", "id3"]
}
```

---

## 設定項目

```env
# Phase 6: Content Intelligence
OCR_PROVIDER=tesseract                # tesseract または google_vision
TESSERACT_CMD=                        # Tesseract実行ファイルのパス（オプション）
GOOGLE_CLOUD_PROJECT_ID=              # Google Cloud プロジェクトID
GOOGLE_APPLICATION_CREDENTIALS=       # サービスアカウントJSONのパス
CONTENT_EXTRACTION_MAX_SIZE_MB=20     # 最大ファイルサイズ
CONTENT_EXTRACTION_TIMEOUT_SECONDS=60 # 抽出タイムアウト
URL_EXTRACTION_TIMEOUT_SECONDS=30     # URL抽出タイムアウト
```

---

## Phase 7との連携

Phase 6で分類されたコンテンツは、Phase 7（Invoice Management）に連携されます。

```
Phase 6                          Phase 7
┌─────────────────┐              ┌─────────────────┐
│ 分類結果        │              │ 請求書管理       │
│ category=invoice│─────────────▶│ 情報抽出        │
│ extracted_data  │              │ スケジュール計算 │
└─────────────────┘              └─────────────────┘
```

---

## 依存関係

### 必須

```
pdfplumber>=0.11.0
pytesseract>=0.3.10
Pillow>=10.0.0
playwright>=1.40.0
langchain-anthropic>=0.1.0
```

### オプション

```
google-cloud-vision>=3.5.0  # Google Vision OCR使用時
```

### システム要件

- **Tesseract**: システムにインストールが必要
  - Windows: https://github.com/UB-Mannheim/tesseract/wiki
  - macOS: `brew install tesseract tesseract-lang`
  - Ubuntu: `apt-get install tesseract-ocr tesseract-ocr-jpn`

---

## テスト

```bash
# Phase 6のテストを実行
pytest tests/test_content_intelligence.py -v

# 特定のテストクラスを実行
pytest tests/test_content_intelligence.py::TestPDFExtractor -v
pytest tests/test_content_intelligence.py::TestOCRExtractor -v
pytest tests/test_content_intelligence.py::TestURLExtractor -v
pytest tests/test_content_intelligence.py::TestContentClassifier -v
```

