# 開発者ダッシュボード 設計書

## 概要

ダン（秘書AI）が記録したイシューを閲覧・管理するための開発者向けダッシュボード。
イシューの確認、スクリーンショット・HTML閲覧、ステータス管理を提供する。

**配置:** `D:\done\dev-dashboard`
**ポート:** Backend 8001, Frontend 3001

---

## 技術スタック

既存のダン・フロントエンドと統一:

| カテゴリ | 技術 | バージョン |
|---------|------|-----------|
| フレームワーク | Next.js (App Router) | 16.x |
| 言語 | TypeScript | 5.x |
| UIライブラリ | shadcn/ui (Radix UI) | 最新 |
| スタイリング | Tailwind CSS | 4.x |
| 状態管理 | Zustand | 5.x |
| データフェッチ | TanStack React Query | 5.x |
| アイコン | Lucide React | 0.5x |
| 通知 | Sonner | 2.x |
| バックエンド | FastAPI | 0.115.x |

---

## ディレクトリ構造

```
dev-dashboard/
├── backend/
│   ├── main.py                    # FastAPIエントリポイント
│   ├── config.py                  # 設定（ポート、パス等）
│   ├── routes/
│   │   ├── __init__.py
│   │   └── issues.py              # イシューAPI
│   ├── services/
│   │   ├── __init__.py
│   │   └── issue_service.py       # ビジネスロジック
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx         # ルートレイアウト
│   │   │   ├── globals.css        # グローバルスタイル
│   │   │   ├── page.tsx           # イシュー一覧（トップ）
│   │   │   └── issues/
│   │   │       └── [id]/
│   │   │           └── page.tsx   # イシュー詳細
│   │   ├── components/
│   │   │   ├── ui/                # shadcn/ui コンポーネント
│   │   │   │   ├── button.tsx
│   │   │   │   ├── card.tsx
│   │   │   │   ├── badge.tsx
│   │   │   │   ├── select.tsx
│   │   │   │   ├── dialog.tsx
│   │   │   │   ├── skeleton.tsx
│   │   │   │   └── table.tsx
│   │   │   ├── layout/
│   │   │   │   ├── header.tsx     # ヘッダー（タイトル、統計）
│   │   │   │   └── page-layout.tsx
│   │   │   └── issues/
│   │   │       ├── issue-list.tsx
│   │   │       ├── issue-card.tsx
│   │   │       ├── issue-detail.tsx
│   │   │       ├── filter-bar.tsx
│   │   │       ├── status-badge.tsx
│   │   │       ├── screenshot-viewer.tsx
│   │   │       └── html-viewer.tsx
│   │   ├── lib/
│   │   │   ├── api.ts             # APIクライアント
│   │   │   ├── utils.ts           # ユーティリティ
│   │   │   └── query-client.ts    # React Query設定
│   │   ├── stores/
│   │   │   └── filter-store.ts    # フィルタ状態
│   │   ├── types/
│   │   │   └── issue.ts           # 型定義
│   │   └── providers.tsx          # プロバイダー
│   ├── package.json
│   ├── tsconfig.json
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   └── components.json            # shadcn/ui設定
│
├── DESIGN.md                      # この設計書
└── README.md                      # セットアップ手順
```

---

## API設計

### エンドポイント一覧

| Method | Path | 説明 |
|--------|------|------|
| GET | `/api/issues` | イシュー一覧（フィルタ対応） |
| GET | `/api/issues/{id}` | イシュー詳細 |
| PATCH | `/api/issues/{id}` | イシュー更新（ステータス等） |
| GET | `/api/issues/{id}/screenshot/{filename}` | スクリーンショット取得 |
| GET | `/api/issues/{id}/html/{filename}` | HTMLスナップショット取得 |
| GET | `/api/stats` | 統計情報 |

### 詳細仕様

#### GET /api/issues

**クエリパラメータ:**
```
status      : string  # open, in_progress, resolved, wont_fix
site        : string  # rakuten.co.jp, amazon.co.jp 等
issue_type  : string  # user_input_required, execution_failed 等
limit       : int     # デフォルト 50
offset      : int     # ページネーション用
sort        : string  # created_at, priority, last_occurred_at
order       : string  # asc, desc (デフォルト desc)
```

**レスポンス:**
```json
{
  "issues": [
    {
      "id": "uuid",
      "issue_type": "user_input_required",
      "status": "open",
      "priority": 3,
      "original_wish": "楽天でアベンヌウォーター購入",
      "service_type": "visual_browse",
      "service_name": "rakuten.co.jp",
      "page_url": "https://...",
      "error_message": "必須項目エラー",
      "screenshots": ["session_id/issues/xxx.png"],
      "html_snapshot_path": "session_id/issues/xxx.html",
      "fallback_action": "Amazonに切り替え",
      "created_at": "2026-01-26T...",
      "last_occurred_at": "2026-01-26T...",
      "occurrence_count": 3
    }
  ],
  "total": 42,
  "has_more": true
}
```

#### GET /api/issues/{id}

**レスポンス:**
```json
{
  "id": "uuid",
  "issue_type": "user_input_required",
  "status": "open",
  "priority": 3,
  "original_wish": "楽天でアベンヌウォーター購入",
  "service_type": "visual_browse",
  "service_name": "rakuten.co.jp",
  "page_url": "https://...",
  "error_message": "必須項目エラー",
  "error_details": { ... },
  "screenshots": ["session_id/issues/xxx.png"],
  "html_snapshot_path": "session_id/issues/xxx.html",
  "fallback_action": "Amazonに切り替え",
  "suggested_solutions": [ ... ],
  "created_at": "2026-01-26T...",
  "updated_at": "2026-01-26T...",
  "resolved_at": null,
  "last_occurred_at": "2026-01-26T...",
  "occurrences": [
    {
      "id": "uuid",
      "occurred_at": "2026-01-26T...",
      "original_wish": "...",
      "error_message": "...",
      "page_url": "...",
      "screenshots": [...]
    }
  ]
}
```

#### PATCH /api/issues/{id}

**リクエスト:**
```json
{
  "status": "resolved"
}
```

**レスポンス:**
```json
{
  "success": true,
  "issue": { ... }
}
```

#### GET /api/stats

**レスポンス:**
```json
{
  "total": 42,
  "by_status": {
    "open": 30,
    "in_progress": 5,
    "resolved": 7
  },
  "by_type": {
    "user_input_required": 15,
    "execution_failed": 25,
    "selector_outdated": 2
  },
  "by_site": {
    "rakuten.co.jp": 20,
    "amazon.co.jp": 10,
    "mercari.com": 12
  }
}
```

---

## UI設計

### 画面構成

```
┌─────────────────────────────────────────────────────────────┐
│ 🛠️ Dev Dashboard                           [Stats: 30 open] │
├─────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ [Status ▼] [Site ▼] [Type ▼]              [🔄 Refresh] │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Type          │ Site      │ Task         │ Status │ ... │ │
│ ├───────────────┼───────────┼──────────────┼────────┼─────┤ │
│ │ 🔴 USER_INPUT │ rakuten   │ アベンヌ...  │ open   │ →   │ │
│ │ 🟡 EXEC_FAIL  │ mercari   │ iPhone探す   │ open   │ →   │ │
│ │ 🟢 EXEC_FAIL  │ amazon    │ 水購入       │ resolved │ → │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                               Page 1 of 5   │
└─────────────────────────────────────────────────────────────┘
```

### イシュー一覧画面（トップページ）

**コンポーネント構成:**
- `Header` - タイトル、統計サマリー
- `FilterBar` - ステータス/サイト/タイプのフィルタ
- `IssueList` - テーブル形式のイシュー一覧
  - `IssueCard` - 各イシュー行
    - `StatusBadge` - ステータス表示

**テーブルカラム:**
| カラム | 説明 | 幅 |
|--------|------|-----|
| Type | issue_type（アイコン付き） | 140px |
| Site | service_name | 120px |
| Task | original_wish（truncate） | flex |
| Error | error_message（truncate） | 200px |
| Status | ステータスバッジ | 100px |
| Priority | 優先度（発生回数） | 60px |
| Created | 作成日時（相対時間） | 100px |
| Action | 詳細リンク | 40px |

**ステータスバッジの色:**
```
open        → 赤 (destructive)
in_progress → 黄 (warning/amber)
resolved    → 緑 (success)
wont_fix    → グレー (muted)
```

**issue_typeアイコン:**
```
user_input_required → 🔴 (入力必要)
execution_failed    → 🟡 (実行失敗)
selector_outdated   → 🔧 (セレクタ古い)
executor_missing    → ⚠️ (Executor無し)
search_failed       → 🔍 (検索失敗)
```

### イシュー詳細画面

```
┌─────────────────────────────────────────────────────────────┐
│ ← Back                                     Issue #abc123    │
├─────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 基本情報                                                │ │
│ │ Type: USER_INPUT_REQUIRED    Status: [open ▼]          │ │
│ │ Site: rakuten.co.jp          Priority: 3               │ │
│ │ Created: 2026-01-26 13:36    Last: 5分前              │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ タスク                                                  │ │
│ │ 楽天でアベンヌウォーター 50ml を検索して購入           │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ エラー                                                  │ │
│ │ レビュー投稿のドロップダウンが必須項目です             │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Page URL                                                │ │
│ │ https://search.rakuten.co.jp/...         [🔗 Open]     │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Screenshot                                  [拡大表示]  │ │
│ │ ┌─────────────────────────────────────────┐            │ │
│ │ │                                         │            │ │
│ │ │          [スクリーンショット画像]        │            │ │
│ │ │                                         │            │ │
│ │ └─────────────────────────────────────────┘            │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ HTML Snapshot                              [View HTML]  │ │
│ │ snapshot_20260126_133640.html (13.5 KB)                │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 発生履歴 (3回)                                         │ │
│ │ ├─ 2026-01-26 13:36 - 同じエラー                      │ │
│ │ ├─ 2026-01-25 10:22 - 同じエラー                      │ │
│ │ └─ 2026-01-24 15:45 - 初回発生                        │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**コンポーネント構成:**
- `IssueDetail` - メインコンテナ
  - `IssueHeader` - 戻るボタン、ID
  - `BasicInfoCard` - 基本情報カード
  - `TaskCard` - タスク内容
  - `ErrorCard` - エラーメッセージ
  - `PageUrlCard` - URL表示＋外部リンク
  - `ScreenshotViewer` - 画像表示（モーダル拡大対応）
  - `HtmlViewer` - HTMLプレビュー/ダウンロード
  - `OccurrenceHistory` - 発生履歴リスト

### ScreenshotViewer コンポーネント

**機能:**
- サムネイル表示（カード内）
- クリックでモーダル拡大表示
- ズーム機能（ホイール or ボタン）
- ダウンロードボタン

### HtmlViewer コンポーネント

**機能:**
- ファイル名とサイズ表示
- 「View HTML」ボタン → 新タブでiframe表示 or ダウンロード
- セキュリティ: sandboxed iframe使用

---

## スタイリング

既存ダンフロントエンドと同じダークテーマを使用:

```css
/* globals.css */
:root {
  --background: oklch(0.098 0 0);     /* #0a0a0a */
  --foreground: oklch(0.98 0 0);       /* #fafafa */
  --card: oklch(0.13 0 0);             /* #141414 */
  --primary: oklch(0.98 0 0);
  --secondary: oklch(0.18 0 0);
  --muted: oklch(0.18 0 0);
  --accent: oklch(0.22 0 0);
  --border: oklch(0.22 0 0);
  --input: oklch(0.25 0 0);
  --destructive: oklch(0.65 0.2 25);   /* Red */
  --warning: oklch(0.75 0.15 85);      /* Amber */
  --success: oklch(0.65 0.2 145);      /* Green */
}
```

---

## 状態管理

### filter-store.ts

```typescript
interface FilterState {
  status: string | null;
  site: string | null;
  issueType: string | null;
  sortBy: 'created_at' | 'priority' | 'last_occurred_at';
  sortOrder: 'asc' | 'desc';
}

interface FilterActions {
  setStatus: (status: string | null) => void;
  setSite: (site: string | null) => void;
  setIssueType: (type: string | null) => void;
  setSortBy: (sort: FilterState['sortBy']) => void;
  setSortOrder: (order: FilterState['sortOrder']) => void;
  resetFilters: () => void;
}
```

**特徴:**
- URLクエリパラメータと同期（ブックマーク可能）
- ローカルストレージに保存（ページリロード後も維持）

---

## データフェッチング

### React Query設定

```typescript
// query-client.ts
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30 * 1000,      // 30秒
      refetchInterval: 60 * 1000, // 1分ごとに自動更新
      refetchOnWindowFocus: true,
      retry: 1,
    },
  },
});
```

### Query Keys

```typescript
const queryKeys = {
  issues: ['issues'] as const,
  issueList: (filters: FilterState) => ['issues', 'list', filters] as const,
  issueDetail: (id: string) => ['issues', 'detail', id] as const,
  stats: ['stats'] as const,
};
```

---

## バックエンド実装

### ファイルアクセス

スクリーンショット・HTMLは `D:\done\app\logs\browser\` に保存されている。
バックエンドからこのディレクトリにアクセスして提供する。

```python
# config.py
BROWSER_LOGS_DIR = Path("D:/done/app/logs/browser")
```

### CORS設定

```python
# main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Supabase接続

既存の `app.services.supabase_client` を再利用:

```python
# issue_service.py
import sys
sys.path.insert(0, "D:/done")
from app.services.supabase_client import get_supabase_client
```

---

## 実装計画

### Phase 1: 基盤構築（優先）
1. バックエンドプロジェクト作成
2. フロントエンドプロジェクト作成
3. APIクライアント実装
4. 基本UIコンポーネント（shadcn/ui）

### Phase 2: イシュー一覧
1. GET /api/issues 実装
2. GET /api/stats 実装
3. FilterBar コンポーネント
4. IssueList コンポーネント
5. ページネーション

### Phase 3: イシュー詳細
1. GET /api/issues/{id} 実装
2. スクリーンショット配信API
3. HTML配信API
4. IssueDetail ページ
5. ScreenshotViewer
6. HtmlViewer

### Phase 4: ステータス管理
1. PATCH /api/issues/{id} 実装
2. ステータス変更UI
3. 確認ダイアログ

---

## セキュリティ考慮事項

1. **認証**: 初期バージョンでは認証なし（ローカル開発環境想定）
2. **CORS**: フロントエンドオリジンのみ許可
3. **HTML表示**: sandboxed iframeで表示（XSS防止）
4. **ファイルアクセス**: BROWSER_LOGS_DIR外へのアクセス禁止

---

## 起動方法（予定）

```bash
# バックエンド
cd dev-dashboard/backend
pip install -r requirements.txt
python main.py
# → http://localhost:8001

# フロントエンド
cd dev-dashboard/frontend
npm install
npm run dev
# → http://localhost:3001
```
