---
name: design
description: >
  UI/デザイン全般のスキル。ダッシュボード、クライアントHP、提案書HTML、管理画面など
  ビジュアルを伴う成果物を作成する際に使用する。shadcn/uiコンポーネントと
  デザイントークンの使用を強制し、自己評価ループで品質を保証する。
display_name: デザイン
updated: 2026-03-30
---

# デザインスキル

ダッシュボード・クライアントHP・提案書など、**ビジュアルを伴う全ての成果物**に適用するデザインルール。

---

## 共通ルール（全用途で厳守）

### 1. デザイントークンを使う（ハードコード禁止）

`globals.css` に定義済みのCSS変数をTailwind経由で使う。

| 使う | 使わない |
|------|---------|
| `bg-background` | `bg-[#0a0a0a]` `bg-neutral-950` |
| `bg-card` | `bg-neutral-900/50` `bg-neutral-900` |
| `text-foreground` | `text-white` `text-neutral-100` |
| `text-muted-foreground` | `text-neutral-400` `text-neutral-500` |
| `border-border` | `border-neutral-800` `border-neutral-700` |
| `bg-primary` | `bg-white`（アクセント用途時） |
| `text-primary-foreground` | `text-neutral-900`（アクセント上テキスト） |
| `bg-secondary` | `bg-neutral-800` |
| `bg-accent` | `bg-neutral-700` |
| `bg-destructive` | `bg-red-500` |

**例外**: チャートの色分け等、セマンティックトークンでカバーできない場合のみ `emerald-400` 等を許可。CSS変数 `--chart-1` 〜 `--chart-5` を優先。

### 2. アイコンはLucide React（Next.js）またはSVG（HTML）

| 使う | 使わない |
|------|---------|
| `<Building2 className="h-4 w-4 text-muted-foreground" />` | `<span>🏢</span>` |
| インラインSVG（提案書HTML用） | 絵文字をアイコン代わりに多用 |

### 3. レスポンシブはmobile-first

`grid-cols-1` → `sm:grid-cols-2` → `lg:grid-cols-4` の順で拡張。

### 4. 自己評価ループ（全用途共通）

成果物を出力する前に必ず `actions/create.md` の手順に従う。
用途ごとの評価基準は `criteria.md` を参照。

---

## 用途別ルール

---

### A. ダッシュボード / 管理画面（Next.js）

#### shadcn/uiコンポーネントを必ず使う

`frontend/src/components/ui/` にあるコンポーネントを最優先で使用する。

| やること | やらないこと |
|---------|------------|
| `<Card>` `<CardHeader>` `<CardContent>` | `<div className="rounded-xl border border-neutral-800 ...">` |
| `<Button variant="outline">` | `<button className="px-4 py-2 rounded-lg bg-neutral-800">` |
| `<Badge>` | `<span className="text-xs px-2 py-0.5 rounded-full">` |
| `<Tabs>` `<TabsList>` `<TabsTrigger>` | 自作タブ切り替え |
| `<Skeleton>` | 自作ローディングスピナー |
| `<Input>` `<Label>` | `<input className="...">` |
| `<Dialog>` | 自作モーダル |
| `<DropdownMenu>` | 自作ドロップダウン |
| `<Separator>` | `<div className="border-b">` |
| `<Tooltip>` | title属性やカスタムツールチップ |
| `<Table>` | 自作テーブル |

#### 足りないコンポーネントは追加する

```bash
npx shadcn@latest add <component-name>
```

未導入で有用なもの: `table`, `select`, `progress`, `chart`, `textarea`, `alert`, `breadcrumb`, `collapsible`, `command`, `navigation-menu`

#### ページ構造

```tsx
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export default function BusinessDashboard() {
  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* ヘッダー */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-foreground">タイトル</h1>
          <p className="text-sm text-muted-foreground">説明</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline">アクション</Button>
          <Button>主要アクション</Button>
        </div>
      </div>

      {/* KPIカード */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm text-muted-foreground">ラベル</span>
              <Icon className="h-4 w-4 text-muted-foreground" />
            </div>
            <span className="text-2xl font-semibold tabular-nums">1,234</span>
          </CardContent>
        </Card>
      </div>

      {/* メインコンテンツ */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>チャート</CardTitle></CardHeader>
          <CardContent>...</CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>最近の活動</CardTitle></CardHeader>
          <CardContent>...</CardContent>
        </Card>
      </div>
    </div>
  );
}
```

#### チャート

shadcn/uiのchartコンポーネント（Recharts統合）を使う。`npx shadcn@latest add chart` で追加。手書きSVGやカスタムチャートは禁止。

#### 状態表示パターン

```tsx
// ステータスバッジ
<Badge variant="outline" className="text-emerald-400 border-emerald-400/30">稼働中</Badge>

// 空状態
<Card>
  <CardContent className="flex flex-col items-center justify-center py-12">
    <FolderOpen className="h-10 w-10 text-muted-foreground mb-3" />
    <p className="text-muted-foreground">データがありません</p>
  </CardContent>
</Card>

// ローディング
<Card>
  <CardContent className="pt-6 space-y-3">
    <Skeleton className="h-4 w-24" />
    <Skeleton className="h-8 w-16" />
  </CardContent>
</Card>
```

---

### B. クライアントHP / ツール（Next.js）

ダッシュボードと同じNext.js + shadcn/uiで作る。Astroは使わない。
同じコンポーネント（Card, Button, Badge等）を使い、**CSS変数でクライアントごとの配色・雰囲気を変える**。

#### プロジェクト構成

各クライアントHPは独立したNext.jsプロジェクトとして `D:/dan-workspace/hp-projects/` に作成する。

```bash
npx create-next-app@latest {client-name} --typescript --tailwind --app
cd {client-name}
npx shadcn@latest init
npx shadcn@latest add card button badge separator
```

#### クライアントごとのカスタマイズ

同じshadcn/uiコンポーネントを使いつつ、`globals.css` のCSS変数でデザインを変える:

```css
/* 例: 野性的・アウトドア系 */
:root {
  --background: oklch(0.15 0.02 80);    /* 暗い土色 */
  --foreground: oklch(0.92 0.01 90);    /* 温かい白 */
  --primary: oklch(0.6 0.15 140);       /* 深い緑 */
  --card: oklch(0.2 0.02 80);           /* 土色カード */
  --muted-foreground: oklch(0.6 0.02 80);
  --border: oklch(0.3 0.02 80);
  --radius: 1rem;                        /* 大きめ角丸 */
}

/* 例: 機械的・テック系 */
:root {
  --background: oklch(0.05 0 0);         /* 真っ黒 */
  --foreground: oklch(0.95 0 0);         /* 白 */
  --primary: oklch(0.7 0.15 230);        /* 青白い光 */
  --card: oklch(0.1 0 0);               /* ダークカード */
  --muted-foreground: oklch(0.5 0 0);
  --border: oklch(0.2 0 0);
  --radius: 0;                           /* シャープ角丸なし */
}
```

#### デプロイ

Vercelにデプロイ（Next.jsの標準ホスティング）。既存HPと同じ運用。

---

### C. 提案書HTML

#### 出力ルール

1. 生成したHTMLを `D:/dan-workspace/proposals/` に保存する（write_fileツール使用）
2. ファイル名は `{プロジェクト名}-proposal.html`（英数字ケバブケース）
3. チャットに以下の形式でリンクを表示する:

````
```proposal
ファイル名.html
```
````

#### HTMLの技術制約

- **完全自己完結**: 外部CSS/JSファイルへのリンク禁止。Google Fonts + Tailwind CDNのみ外部読み込み可
- **1ページ縦スクロール**: ページ切り替え・ページネーション禁止
- **横はみ出し禁止**: `overflow-x: hidden` を body に設定
- **レスポンシブ必須**: PC（960px+）/ タブレット（680px）/ スマホ（420px以下）の3段階
- **別タブ表示前提**: ブラウザの別タブで全画面表示される

#### タイポグラフィ

**禁止フォント**: Arial, Inter, Roboto, system-ui, sans-serif単体指定

**推奨フォント（Google Fonts）**:

| 用途 | 推奨 |
|------|------|
| 日本語見出し | Noto Sans JP (700-900), M PLUS 1p, Zen Kaku Gothic New |
| 日本語本文 | Noto Sans JP (400), BIZ UDPGothic |
| 英数字アクセント | JetBrains Mono, IBM Plex Mono, Space Grotesk, DM Sans |
| KPI数値 | JetBrains Mono, Oswald, Barlow Condensed |

フォントは**最大2種類**。

#### 配色

- **支配色1色 + アクセント1色 + ニュートラル**: 3色構成。均等配分禁止
- 支配色は面積60%以上。アクセントは要所のみ
- CSS変数で色管理:

```css
:root {
  --bg: #0d0d0d;
  --surface: #161616;
  --border: #252525;
  --text: #e8e8e8;
  --muted: #888;
  --accent: #e8a020;       /* 提案ごとに変える */
  --accent-subtle: rgba(232, 160, 32, 0.10);
}
```

**毎回同じ配色にしないこと。** 業界・トーンに合わせて変える。

#### レイアウト

- 情報密度を高く（スカスカ禁止、ギチギチも禁止）
- グリッドを活用（2〜4カラムを適材適所で）
- セクション間に明確な区切り
- カード角丸は控えめ（4-6px）

#### 背景と視覚効果

- ベタ塗り単色は避ける。微妙なグラデーション・テクスチャを加える
- ヒーローに `radial-gradient` / `linear-gradient`
- `::before` / `::after` で控えめな光彩効果
- アニメーションは不要（静的に）

#### 提案書の構成（推奨セクション）

| # | セクション | デザインパターン |
|---|-----------|-----------------|
| — | **ヒーロー** | 全幅背景 + KPI 3-4個 + グリッド |
| 01 | **結論** | 本文テキスト、3行以内 |
| 02 | **背景/課題** | カードグリッド or 箇条書き |
| 03 | **提案内容** | フローチャート or ステップリスト |
| 04 | **収益/効果** | テーブル + プログレスバー |
| 05 | **ロードマップ** | 横並びフェーズカラム |
| 06 | **体制/コスト** | 2-3カラム |
| 07 | **リスクと対策** | テーブル + バッジ |
| — | **CTA** | 全幅背景 + ボタン |

#### アンチパターン

- 角丸カードの羅列だけで構成する
- 全セクションが同じ見た目
- 絵文字をアイコン代わりに多用
- フォントサイズが2段階しかない
- テキストの壁（5行以上の連続段落）

---

## 自己評価ループ（品質保証）

全用途で共通の仕組み。詳細手順は `actions/create.md` を参照。

### 関連ファイル

| ファイル | 役割 |
|---------|------|
| `criteria.md` | 用途別の品質基準（必須チェック + 品質スコア） |
| `learned.md` | 蓄積された改善パターン（用途別セクション） |
| `actions/create.md` | 自己評価ループ込みの作成手順 |

### ループの流れ

```
learned.md参照 → 初版生成 → 視覚評価(screenshot) → 採点
→ 不合格なら改善(最大3回) → 合格したら出力 → learned.mdに記録
```

---

## 禁止事項チェックリスト（全用途共通）

コード生成後、以下をセルフチェックする:

- [ ] `bg-neutral-*` `text-neutral-*` `border-neutral-*` のハードコードがないか
- [ ] Card/Button/Badge等を手書きで再発明していないか（Next.js用途）
- [ ] 絵文字をアイコンとして使っていないか
- [ ] ローディングスピナーを自作していないか
- [ ] `text-white` → `text-foreground` に置換したか
- [ ] `text-neutral-500` → `text-muted-foreground` に置換したか
- [ ] セクションごとにレイアウトが変化しているか（提案書）
- [ ] 配色が内容に合っているか
