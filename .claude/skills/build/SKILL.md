---
name: build
description: >
  Next.js + shadcn/ui + Tailwind で UI とバックエンドを実装するスキル。
  ダッシュボード・HP・管理画面・LP・問い合わせフォーム付き機能ページなど、
  見せて使える成果物が必要な時に使う。
display_name: ビルド
updated: 2026-04-24
---

# build スキル

ダッシュボード・HP など、**Next.js で見せて使える成果物全般**を実装するスキル。
UI のデザインだけでなく、DB / API / フロントを通したエンドツーエンドの実装と
自己評価ループによる品質保証までを含む。

> 提案書 HTML を作る場合は `actions/proposal_html.md` を参照 (ユーザーが「提案書作って」と明示要求した時のみ)。

## 🧩 まず templates を使う

成果物を書き始める前に `frontend/src/components/templates/` を確認。
ここには構造パターンが既にコンポーネント化されている（色やコピーは各案件で決める）:

| コンポーネント | 用途 |
|---|---|
| `<PageShell>` | ダッシュボード/管理画面の外枠（max-width + padding + ヘッダー） |
| `<LpShell>` | LP全体の外枠（sticky nav + footer） |
| `<Section>` | セクションの縦リズム・見出し・max-width統一 |
| `<HeroSection>` | ヒーロー（split/centered/stacked の3レイアウト） |
| `<FeatureGrid>` | 特徴カードの3〜4カラムグリッド |
| `<KpiCard>` | KPI表示（label / value / icon / trend） |
| `<AIChatPanel>` | Mode B の公開チャットUI (`scope` でAPI側のコンテキスト分岐) |
| `<InquiryForm>` | 問い合わせフォーム（送信先: `/api/v1/inquiries`） |
| `<LocationMap>` | Google Maps iframe 埋め込み（アクセスセクション用、APIキー不要） |

import 例: `import { HeroSection, Section, FeatureGrid } from "@/components/templates";`

**templateで表現できない構造を毎回スクラッチで書かないこと。** 足りない場合は templates/ に足してから使う。

---

## 🧩 機能ブロック（再利用）も使う

ログイン・予約など「丸ごと差し込める機能」は毎回スクラッチで作らず、既存の機能ブロック
を使う。`config`/props で業種・店舗に合わせて調整する。

| 機能 | 使うもの | 場所 |
|---|---|---|
| ログイン/初期設定ゲート | `useSetupGate`（フック） | `@/hooks/use-setup-gate` |
| 予約・カレンダー | `<BookingCalendar>` + `useBooking` | `@/components/booking/booking-calendar`, `@/hooks/use-booking` |
| スクロール出現アニメ | `<FadeIn>` / `<Stagger>` / `<StaggerItem>` | `@/components/motion` |

例: 予約フォームを置きたい → `<BookingCalendar config={{ slug, openTime, closeTime, slotMinutes, services, staff, closedWeekdays }} />` を埋め込むだけ（バックエンドの予約API/DBは実装済み）。実例: `frontend/src/app/artifacts/bookings/page.tsx`。

（決済・LINE連携・会員ログインは順次このメニューに追加予定。）

---

## 共通ルール（全用途で厳守）

### 1. デザイントークンを使う（ハードコード禁止）

`globals.css` に定義済みのCSS変数をTailwind経由で使う。色の値はダーク固定ではなく、案件や用途に応じて適切に選ぶ。

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

### 2. アイコンは Lucide React (Next.js)

| 使う | 使わない |
|------|---------|
| `<Building2 className="h-4 w-4 text-muted-foreground" />` | `<span>🏢</span>` |

### 3. レスポンシブはmobile-first

`grid-cols-1` → `sm:grid-cols-2` → `lg:grid-cols-4` の順で拡張。

### 4. ヒーロー画像 / 動画は **`<HeroMedia>` を使う** (overlay div を書かせない仕組み)

ヒーローや大きな写真・動画は **必ず `<HeroMedia>` テンプレート** を使う。手書きで `<section>` の中に `<img>`/`<video>` + 重ね overlay `<div>` を書かない。

```tsx
import { HeroMedia } from "@/components/templates";

// ✅ OK
<HeroMedia kind="video" src="/hero.mp4" darken={50} blur={1} fade="left">
  <div className="mx-auto max-w-7xl px-6 py-32">
    <h1>働く車を、もっと賢く</h1>
    <p>新明和認定 米子市 ...</p>
  </div>
</HeroMedia>

// 画像版 (kind="image")
<HeroMedia kind="image" src="/hero.png" alt="工場で作業する職人" darken={40}>
  <div className="...">{/* テキスト */}</div>
</HeroMedia>
```

**`<HeroMedia>` の props**:
- `darken` (0-100): 暗くする度合い → 内部で CSS `filter: brightness(...)` に変換
- `blur` (0-20px): ぼかし → 内部で CSS `filter: blur(...)` に変換
- `fade` (`"none" | "left" | "right" | "top" | "bottom"`): 方向性のフェード → 内部で `mask-image` で実装
- `minHeightClass`: ヒーロー高さ (デフォルト `min-h-[60vh]`)

**なぜこれを使うのか**:
- **overlay div を書く隙が無い構造**になっているので、ルール違反が起きない
- 暗転 / ぼかし / フェードは **媒体自体の CSS filter / mask** に変換される → inspector で `<img>`/`<video>` を直接クリック選択できる
- inspector の Overlay (darken/blur) スライダーで UI から調整可能
- `alt` 必須、`autoplay loop muted playsInline` 自動付与、Lighthouse スコア確保

**`<HeroMedia>` で表現できない複雑なヒーロー** (例: 動画が画面分割で 2 つ並ぶ、3D Parallax) が必要になったら、 **新しい template コンポーネントを `frontend/src/components/templates/` に追加** してから使う。手書きの section + overlay 構造を残さない。

**通常の画像表示** (記事中の挿絵、商品サムネ等) は `<img>` / `<Image>` を直接書いて OK。overlay 不要なら `<HeroMedia>` も不要。

### 5. 編集対象要素には **`data-edit-id` を必ず付ける**

ライブペイント（インスペクタ）でユーザーが編集する可能性のあるテキスト要素・CTA・主要画像には、必ず一意の `data-edit-id` 属性を付ける。

**なぜ必須か**：

`data-edit-id` がないと、エディタは要素を **DOM ツリー上の位置（パス）** で識別する。これには 2 つの致命的問題がある：

1. **構造変化に弱い**: ユーザーが部分テキスト装飾を入れた瞬間 `<span>` が DOM に挟まり、識別子がズレる → 編集データが孤立する／別要素扱いになる
2. **ページ間で干渉する**: 同じテンプレで作った複数ページ（top / services / company / careers 等）は同じ DOM 構造になりやすく、構造ベース ID が衝突 → **1 つのヒーローを編集すると全ページに反映**される

`data-edit-id` を付ければ両方解決する。

**命名規則**: `{slug}-{page}-{role}` 形式で全ページ通してユニークに。

```jsx
// ✅ OK
<h1 data-edit-id="kittoku-top-hero-h1">働く車を、止めない。</h1>
<p data-edit-id="kittoku-top-hero-tagline">鳥取・米子の特装車専門整備工場。</p>
<a href="/contact" data-edit-id="kittoku-top-hero-cta">修理・整備の依頼</a>

// 子ページ（必ず page セグメントを変える）
<h1 data-edit-id="kittoku-services-hero-h1">整備・修理・点検・架装。</h1>
<h1 data-edit-id="kittoku-company-hero-h1">米子の地で、働く車を、30年。</h1>
```

**付与する要素**:
- ✅ すべての h1, h2, h3, h4
- ✅ 段落 `<p>`（説明文・本文）
- ✅ ヒーローや CTA 内のリンク `<a>` / ボタン `<button>` でテキスト編集対象になりうるもの
- ✅ 主要な `<img>` / `<video>`（差し替え対象）

**付与しない要素**:
- ❌ ラッパー `<div>`, `<section>`, `<main>`
- ❌ ナビゲーションリンク（共通レイアウトとして共有してよい）
- ❌ アイコン専用 `<span>`
- ❌ `map()` で生成される動的リスト要素（同じ ID が複数できる）。固定数（例: 3つの強み）なら index 付きで個別 ID を付ける

**例外（共有が正しい場合）**:
共通フッター・共通ナビなど、複数ページで同じ ID を意図的に持たせて「1回の編集で全ページに反映」させたい場合は同一 ID を使ってよい。これは仕様、衝突ではない。

---

### 6. ログイン / 初期設定ゲートは **`useSetupGate` を使う**

ログインや初回登録（認証情報・名前の登録など）が **必須なページ** を作るときは、
ゲート判定を自前で書かず **必ず `@/hooks/use-setup-gate` の `useSetupGate` を使う**。

**なぜ必須か**：

チャット右ペインのライブプレビューは成果物を iframe で読み込むため、ゲートを自前で
書くと **プレビューでもログイン/初期設定を求められ、他の画面を閲覧・編集できなくなる**。
`useSetupGate` はプレビュー（`isDanPreview()`）を検出して **自動でゲートをバイパス**し、
管理者として全画面を見られるようにする。各ページでプレビュー判定を再実装しないこと。

```tsx
import { useSetupGate } from '@/hooks/use-setup-gate';

const gate = useSetupGate(async () => {
  // 設定が完了済みか（true=ready / false=要設定）を返す。プレビューでは呼ばれない。
  const r = await fetch('/api/.../status?...');
  return r.ok && (await r.json()).has_credentials;
});

if (gate.status === 'loading')     return <Spinner />;
if (gate.status === 'needs-setup') return <SetupScreen onDone={gate.markReady} />;
return <MainApp />;          // gate.isPreview が true のときは常にここに来る
```

- 設定完了で先へ進めたいタイミングでは `gate.markReady()` を呼ぶ。
- 認証境界ではない（プレビューで飛ばしても保存済み認証情報が無ければ実処理は動かない）。
- 実例: `frontend/src/app/artifacts/salonboard-styleup/page.tsx`

---

### 7. 自己評価ループ（全用途共通）

成果物を出力する前に必ず `actions/create.md` の手順に従う。
用途ごとの評価基準は `criteria.md` を参照。

---

### 8. favicon（ブラウザタブ・検索結果のアイコン）

成果物の favicon は **自動で配線される**（何もしなくてよい）。
`page.tsx` を書くと PostToolUse hook (`hook_register_artifact.py`) が
`scripts/wire_artifact_icons.py` を呼び、そのページ用のアイコンを生成して
`layout.tsx` の `metadata.icons` に焼き込む。これをやらないとタブも検索結果も
ルートのデフォルト favicon（バーセル）に落ちる。

- **デフォルト**: テーマ色 + 屋号の頭文字（ロゴ画像 `public/artifacts/<slug>/logo.png`
  があればそれを優先）。
- **アイコンを変えたいと言われたら**: 画像を用意して
  `python scripts/set_artifact_icon.py --slug <slug> --image <path>` を実行する。
  （AI生成が必要なら先に `media-gen` で作ってからこのコマンドに渡す。画像生成は
  自分でやる ─ ユーザーに丸投げしない）。
- **client component の `layout.tsx` には `metadata` を書けない**。その場合は
  layout を server component にし、`"use client"` の中身を `theme-shell.tsx` 等に
  分離してから配線する（実例: `artifacts/kittoku`, `artifacts/yonago-gojo`）。
- アイコンのパス (`/artifacts/<slug>/icon-*.png`) は静的アセットなので
  `metadata.icons` に絶対パスで直書きしてよい（link guard の対象外）。

---

## 用途別ルール

---

### A/B 共通: 実装順序 (バックエンドファースト)

機能を伴う成果物 (A/B) は以下の順序で実装する:

1. **DB 設計** (テーブル・リレーション)
2. **API 実装** (エンドポイント・ビジネスロジック)
3. **UI 実装** (画面・コンポーネント)
4. **統合テスト** (API ↔ UI 接続確認)

UI を先に作らない。

> ※ `create_feature` + guard hook で強制済み。雛形がこの順序で生成され、未実行でのファイル作成はブロックされる。

---

### A. ダッシュボード / 管理画面（Next.js）

#### shadcn/uiコンポーネントを必ず使う

> ※ `create_feature` が生成する雛形にはshadcn/uiのimportが含まれる。ただしコンポーネント選択自体はコードで強制していないため、以下のルールに従うこと。

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

#### 足りないコンポーネントは PostToolUse hook が自動 install

`hook_autoinstall_shadcn.py` が `@/components/ui/<name>` の import を検出して
未導入なら `npx shadcn@latest add <name>` を自動実行する。手動で気にする必要なし。

#### ページ構造の典型

`<PageShell>` (templates) を外枠にして、以下のようなブロックを縦に積む。
具体的なコードは `frontend/src/app/artifacts/` 配下の既存ダッシュボードを参考にする
(コードサンプルをここに固定で書くと「同じ構造に収束しやすい」ため意図的に省略)。

- ヘッダー: タイトル + 説明 + 主要アクション
- KPI 行: `<KpiCard>` 3〜4 個並べる
- メインエリア: 2 カラム or 3 カラム、目的に応じて
- リスト/テーブル: `<Table>` (詳細閲覧) または `<Card>` グリッド (概要)

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

### B. HP / LP / ツール（Next.js）

ダッシュボードと同じNext.js + shadcn/uiで作る。Astroは使わない。
同じコンポーネント（Card, Button, Badge等）を使い、**CSS変数でクライアントごとの配色・雰囲気を変える**。

#### 技法選択（最初に決める）

HP/LP は「どんな見た目か」の前に **どの作り方（技法）で作るか** を決める。技法はビジネスゴールから選ぶ。詳細レシピは `recipes/` を参照。

| 技法 | 使うもの | 向く案件 | 重さ | レシピ |
|---|---|---|---|---|
| **T1 コンバージョン・フラット**（既定） | shadcn/Tailwind + framer-motion | 集客HP・地域ビジネス・情報サイト（速度/SEO/モバイル最優先） | 軽 | `recipes/conversion-flat.md` |
| **T2 スクロールナラティブ** | GSAP(ScrollTrigger) + Lenis + framer-motion | ブランドストーリー・製品ローンチ | 中 | `recipes/scroll-narrative.md` |
| **T3 スクロール動画ヒーロー** | T2 + スクロールスクラブ動画（media-gen/video-gen） | プレミアム製品ショーケース | 重 | `recipes/scroll-video.md` |
| **T4 3Dイマーシブ** | R3F + drei + three | 製品コンフィギュレータ・体験型 | 重 | `recipes/3d-immersive.md` |

**選び方**:
1. 既定は **T1**。多くの集客HPはこれが正解（重い演出はCVと表示速度を下げる）
2. T2〜T4 を選ぶのは次のいずれか:
   - ユーザーが明示（「3Dで」「スクロール動画で」）
   - 製品/ブランドが"見せ場"で、かつ表示速度・SEOが最優先制約ではない
3. 技法で結果が大きく変わる時（＝重大な分岐）は、**平易な2〜3択を推奨つきで提示**してから着手する。例:「①速くて堅実なフラット ②映像的なスクロール ③製品を3Dで回せる(重め)」

**共通の鉄則**: どの技法でも build のコア規律（デザイントークン / `data-edit-id` / `useSetupGate` / templates / 自己評価ループ）を厳守。重い技法（T3/T4）は性能予算（モバイルLCP）とフォールバックを必ず用意する。

#### リファレンス駆動デザインプロセス

HP制作では**ゼロからデザインを生成しない**。必ず既存の優れたデザインを参照素材（リファレンス）にする。

##### なぜリファレンスが必要か

AIにリファレンスなしで「モダンなサイト作って」と指示すると、学習データの平均的な出力になる。結果として均等グリッド・ありきたりなグラデーション・どこかで見たフローティングカードの「AIテンプレ感」が出る。リファレンスを与えることでAIの出力方向を具体的に制御し、品質のベースラインを引き上げる。

##### ビジネスゴールからデザインへの因果連鎖

HP制作のデザイン判断は全て**ビジネスゴール**から逆算する。「信頼感のあるサイト」のような抽象的な感情ラベルではなく、以下の因果連鎖で具体化する:

```
① ビジネスゴール: このHPで何を達成したいか
  ↓
② 訪問者の行動: 訪問者に何をさせたいか（問い合わせ、予約、購入…）
  ↓
③ 訪問者の確信: その行動をとるために訪問者が確信すべきことは何か
  ↓
④ 必要なコンテンツ: その確信を生むために見せるべき具体物
  ↓
⑤ デザイン方針: そのコンテンツを最も効果的に見せるデザイン
```

**例: 建築事務所のHP**

| ステップ | 内容 |
|---|---|
| ① ゴール | 見込客から問い合わせを取る |
| ② 行動 | 問い合わせフォーム送信 or 電話 |
| ③ 確信 | 「実績がある」「自分の案件も対応できる」「ちゃんとした会社」「連絡しやすい」 |
| ④ コンテンツ | 完成物件の写真（大きく）、類似規模の事例、代表者の顔・創業年数・受賞歴、全セクションにCTA |
| ⑤ デザイン | 写真が主役→余白多めで呼吸させる。テキスト最小限。CTAは問い合わせフォーム+電話番号常時表示 |

**例: 飲食店のHP**

| ステップ | 内容 |
|---|---|
| ① ゴール | 来店・予約を増やす |
| ② 行動 | 予約ボタン押下 or 来店（地図確認） |
| ③ 確信 | 「料理が美味しそう」「雰囲気が良い」「場所がわかる」「値段が妥当」 |
| ④ コンテンツ | 料理写真（大きく鮮明に）、店内写真、メニューと価格、Google Maps、営業時間 |
| ⑤ デザイン | 料理写真が主役→暖色系、大きな写真。メニューと予約はモバイルで即アクセス可能に |

この因果連鎖をプロジェクトの `DESIGN.md` に記録してからリファレンスを探す。

##### Phase 1: リファレンス収集

1. ブラウザでDribbble / Pinterest / 優れた実在サイトを検索する
   - 検索例: 「{業種} website design」「{業種} landing page」
2. **サイト全体を1つ選ぶのではなく、パーツを別々の参照元から集める**:
   - A案のヒーローレイアウト
   - B案のタイポグラフィ（フォント選び・サイズ感・太さ）
   - C案の配色と余白の取り方
   - D案のインタラクション（ホバー、スクロール連動）
3. 各パーツのスクリーンショットをプロジェクトフォルダに保存する
4. **最低3つ以上**のリファレンスを用意する

##### Phase 2: デザイン生成（方法の選択）

リファレンスを基にデザインを形にする。状況に応じて方法を選ぶ:

**方法 1: リファレンス画像を直接渡す** (基本手法)
- 保存したスクショをコンテキストに含め、パーツの組み合わせを指示する
- Next.js + shadcn/ui + Tailwind で直接コード生成
- 最初の出力にテンプレ感があれば、追加のリファレンスを渡して再指示

**方法 2: AI 生成画像/動画ヒーロー付き** (方法 1 と併用)
- `image-gen` スキルでコンセプト画像を生成 (日本語テキスト焼き込み可)
- `video-gen` スキルでループ動画を生成、または image-to-video で画像から動かす
- 開始/終了フレームを同じ画像にしてシームレスループを実現
- ヒーロー背景として全画面配置 (autoplay, muted, loop)
- テキスト/CTA は動画上にオーバーレイ

**方法 3: AI 全画面モックアップで方向をロック** (任意 / 視覚差別化が価値になる案件で)
- `image-gen` で**ページ全体のハイファイモックアップ画像**を生成し、最上位リファレンスにする（Dribbble参照の強化版）
- ⚠️ **ピクセル完コピ禁止**。モックアップは「設計図」ではなく「参照」。実装は必ずデザインシステム（トークン / templates / `data-edit-id` / レスポンシブ）で作る
- 偽テキスト・1ビューポートのみ・非レスポンシブという限界がある。方向性とムード決めに使い、実装で正す
- 単純な集客HPは実サイト参照で十分なのでスキップしてよい

##### Phase 3: 実装とPolish（磨き上げ）

コード生成後、以下の磨き上げを行う:

**タイポグラフィ**（サイトの印象を最も左右する要素）:

3つの役割で分けて選ぶ:
- **Headline**: 見出し。サイトの個性を決める最重要要素。大胆で特徴的なフォント
- **Body**: 本文。読みやすさ優先。汎用sans-serif可
- **Label**: ラベル・キャプション・数値。機械的・データ的な書体が合う

Inter / Roboto / Arial は見出しに使わない（本文・ラベルは可）。

フォント選定基準（クライアントの業種・雰囲気から選ぶ）:

| 出したい印象 | Headline候補 | 理由 |
|---|---|---|
| 格式・伝統・信頼 | Cormorant, Playfair Display, Zen Old Mincho, Noto Serif JP | セリフ体は権威性・歴史を暗示 |
| テック・先進性 | Space Grotesk, DM Sans, IBM Plex Sans | ジオメトリックな形状が精密さを表現 |
| 力強さ・職人感 | Oswald, Barlow Condensed, Zen Kaku Gothic New (700+) | 太く凝縮された書体が力を表現 |
| ラグジュアリー・洗練 | Cormorant (細身), Zen Old Mincho (300) + レタースペーシング広め | 細いセリフ+余白=高級感 |
| 親しみ・カジュアル | M PLUS 1p, Rounded Mplus 1c, Quicksand | 丸みのある書体が親近感を生む |

**レイアウト**:
- セクションごとに構造を変える（全幅→非対称2カラム→ジグザグ→カード群→全幅）
- 均等グリッドの連続禁止
- 余白を大胆に使う（py-16〜py-32でメリハリ）

**微細アニメーション**（派手なアニメーションは禁止 / 標準ツール = framer-motion、全技法共通）:
- ホバーエフェクト: ボタンの応答感、カードの微妙な浮き上がり（translateY + shadow変化）
- スクロール連動: framer-motion の `whileInView` でセクションのフェードイン（手書き IntersectionObserver は使わない）
- ナビバー遷移: 透明 → スクロールで背景色+影が付く
- 画像ホバー: 微妙な拡大 + オーバーレイ表示
- `prefers-reduced-motion` を尊重する（OS設定でアニメ抑制を指定したユーザーには動かさない）

**配色**（4層モデル）:
- **Neutral（80-90%）**: 背景・余白。画面の大半を占める。CSS変数 `bg-background`, `bg-card`
- **Primary**: テキスト・主要要素。CSS変数 `text-foreground`
- **Secondary**: サポート要素・境界線。CSS変数 `text-muted-foreground`, `border-border`
- **Accent（最小面積）**: CTAボタン・ハイライトのみ。CSS変数 `bg-primary`
- 色数を絞る。均等配分禁止。Accentは面積が小さいほど効く

##### 「AI感」脱却チェック

HP生成後、以下を全て確認する:

- [ ] 均等グリッドの羅列ではなく、非対称・重なり合うレイアウトを含むか
- [ ] decorative dots、ダイヤ区切り線、SVG幾何学模様等のAIあるある装飾がないか
- [ ] 見出しフォントが大胆で特徴的か（Inter/Roboto/Arialではない）
- [ ] セクション構造が毎回変化しているか
- [ ] カラーが60-30-10ルールになっているか
- [ ] 微細なアニメーションが適切に配置されているか
- [ ] ボタンが応答感を持っているか（hover/active状態の変化）

##### 人間の介入タイミング

- **初回**: 要件指示（業種、雰囲気、必要な機能等）
- **完成後**: 承認 or 修正指示
- **途中確認は原則しない**。ダンがリファレンス選定・デザイン方向性・実装判断を自律的に行い、完成物を提出する。どうしても判断できない重大な分岐（例: 完全に異なる2方向のブランド解釈）がある場合のみ確認を取る

#### プロジェクト構成 (新アーキテクチャ)

HP は **`frontend/src/app/artifacts/{slug}/` 配下** に作る (クライアント案件も社内 LP も全て同じ場所)。
※ `frontend/src/app/demo/{slug}/` は提案動画用プロトタイプ専用。通常の HP / ダッシュボード制作には使わない。
独立した Next.js プロジェクトを切らない (旧 `D:/dan-workspace/hp-projects/` フローは廃止)。
理由: チャット右ペインのライブプレビューでそのまま見せて会話で詰められる、
`create_feature` の guard hook が機能する、Vercel デプロイは done 本体と同居できる。

```
frontend/src/app/artifacts/yoshikawa-tokuso/
  ├─ page.tsx            ← ホーム (LpShell + 各 Section)
  ├─ services/page.tsx   ← 子ページ
  ├─ contact/page.tsx
  └─ components/         ← その HP 専用コンポーネント (templates 外)
```

#### クライアントごとのカスタマイズ

同じ shadcn/ui コンポーネントを使いつつ、CSS 変数 (例: `frontend/src/app/artifacts/{slug}/page.tsx` 内の局所 `<style>` か、ルート `globals.css` のクライアント別セレクタ `.theme-yoshikawa` 等) でデザインを変える:

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

done 本体の Vercel デプロイに自動追従する。チャットの全画面プレビューや共有URLは `/preview/{slug}` を使い、内部的に `/artifacts/{slug}` へ rewrite される。
artifact 内のナビゲーションで `/artifacts/{slug}` にリンクする場合は、`next/link` ではなく `@/components/artifacts/artifact-link` の `ArtifactLink` を `Link` として使う。これにより `/preview/{slug}`、内部 `/artifacts/{slug}`、独自ドメインの clean path が混ざらない。
クライアント独自ドメインを使う場合は、middleware の `ARTIFACT_CUSTOM_DOMAINS` / `NEXT_PUBLIC_ARTIFACT_CUSTOM_DOMAINS` に `slug=domain.example` 形式で追加する。

---

### C. 提案書 HTML (明示要求時のみ)

ユーザーが「提案書 HTML 作って」「proposal HTML を作って」等と明示的に依頼した時のみ `actions/proposal_html.md` を参照する。
通常のダッシュボード/HP 制作 (用途 A/B) には絡めない。

---

## 自己評価ループ（品質保証）

全用途で共通の仕組み。詳細手順は `actions/create.md` を参照。

### 関連ファイル

| ファイル | 役割 |
|---------|------|
| `criteria.md` | 用途別の品質基準 (必須チェック + 品質スコア) |
| `actions/create.md` | 自己評価ループ込みの作成手順 |

### ループの流れ

```
初版生成 → 視覚評価(screenshot) → criteria.md で採点
→ 不合格なら改善(最大3回) → 合格したら出力
```

> ※ 自動学習 (learned.md への自動追記) は廃止。改善パターンを記録する場合は
> このファイル (SKILL.md) に明示的に追記する。隠れ状態を作らない方針。
