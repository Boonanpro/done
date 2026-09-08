---
name: build
description: >
  UIとバックエンドを実装するスキル。ダッシュボード・HP・管理画面・LP・
  問い合わせフォーム付き機能ページなど、見せて使える成果物が必要な時に使う。
  LPを含め、見た目の品質と編集可能性を両立する。画像生成・コード・併用から
  案件に合う方式を選ぶ。作り始める前に必ずこのスキルを読むこと。
display_name: ビルド
updated: 2026-09-08
---

# build スキル

Next.js で「見せて使える成果物」（ダッシュボード・HP・LP・機能ページ）を作るスキル。

このファイルは 3 層に分かれている。**縛るのは第 1 層だけ**。

| 層 | 性質 | 内容 |
|---|---|---|
| 1. 不変条件 | 守らないと編集・公開・プレビューが壊れる配線 | 置き場所、EditableText の ID、公開の仕組み、Tailwind のスキャン、プレビュー用ゲート |
| 2. 判断材料 | 案件に合わせて自分で選ぶ。従わなくてよい | 部品一覧、方式・技法、設計の考え方、落とし穴 |
| 3. 確認と納品 | 完了と言う前に実物で確かめること | 実ブラウザ確認、機能確認、公開URL確認 |

デザインの判断（配色・書体・レイアウト・モーション・トーン）は、ユーザーの要望と
実素材を出発点に **自分で決めてよい**。スキルはデザインの方向を指定しない。
ユーザーが方向を指定したらそれに従う。過去の成果物を「先例」として真似る義務はない。

---

## 1. 不変条件（配線。ここだけは必ず守る）

### 1-1. 置き場所と page 構造

- 成果物は **`frontend/src/app/artifacts/<slug>/`** に作る（クライアント案件も社内LPも同じ）。
  独立した Next.js プロジェクトは切らない。`demo/` `scratch/` は試行錯誤用。
- `page.tsx` は **server component** にして `release.gen.json`（初期値 `{}` で作る）を
  `EditableProvider` に渡し、本体は `"use client"` の `page-body.tsx` に書く:

```tsx
// page.tsx（server）
import { EditableProvider } from "@/components/dan/editable";
import { toEditableOverrides, type ReleaseOverrides } from "@/lib/editable-release";
import releaseJson from "./release.gen.json";
import { PageBody } from "./page-body";

export default function Page() {
  return (
    <EditableProvider overrides={toEditableOverrides(releaseJson as ReleaseOverrides)}>
      <PageBody />
    </EditableProvider>
  );
}
```

  新規 slug はこの雛形を `python scripts/editable_artifact.py init --slug <slug> --title "…"` で
  作れる（既存 slug には実行しない。保存済み編集が消える）。
- `layout.tsx` は server component にする（favicon の `metadata.icons` が書けるように）。
  client の中身は `theme-shell.tsx` 等に分離する。実例: `artifacts/kittoku`。

### 1-2. 編集対象は `EditableText` / `EditableElement`（`data-edit-id`）

ユーザーが手動編集・チャット編集で触りうる要素には、`@/components/dan/editable` の
`EditableText`（文字）・`EditableElement`（画像・セクション・複合要素）を使い、
**durable な ID** を付ける。ID が無いと DOM パスで識別され、構造が変わると編集が孤立し、
同構造の別ページと衝突し、公開ページに反映されない。

- ID は `{slug}-{page}-{role}` 形式で全ページ通してユニーク。チャット修正でも維持する。
- 付ける: h1〜h4、本文 `<p>`、CTA の `<a>`/`<button>`、主要な `<img>`/`<video>`、
  余白や背景を編集させたい `<section>`。
- 付けない: 単なるラッパー div、アイコン専用 span。`map()` で生成する項目は並び順でなく
  項目の安定キーで ID を作る。
- 共通フッター・共通ナビを複数ページで同じ ID にして「1回の編集で全ページ反映」させるのは仕様。
- 公開済み編集（`release.gen.json` に載っている editId）は **JSX を書き換えても公開ページに
  出ない**（オーバーライドが勝つ）。チャットで文言を直す前に必ず `release.gen.json` を見て、
  載っていれば公開済みテキストを土台に JSX を直し、`inspector_overrides` の draft 行を更新
  または削除して再公開する。
- 文字は画像に焼き込まず、ネイティブなテキスト要素にする。alt や透明テキストは編集可能性の
  代わりにならない。

### 1-3. ヒーロー画像・動画の暗転/ぼかしは媒体自体の CSS で行う

`<img>`/`<video>` の上に半透明の overlay `<div>` を重ねると、インスペクタで媒体をクリック
選択できず、Overlay スライダーも効かない。暗転は `filter: brightness()`、ぼかしは
`filter: blur()`、方向フェードは `mask-image` を **媒体自体に** 当てる。
`<HeroMedia kind="video|image" src darken blur fade>` がこれを済ませてある。
自前で書く場合も同じ原則で書く（`alt`、`autoplay loop muted playsInline` を忘れない）。

### 1-4. ログイン / 初期設定ゲートは `useSetupGate`

ログインや初回登録が必須なページでは `@/hooks/use-setup-gate` の `useSetupGate` を使う。
チャット右ペインのプレビューは iframe なので、自前ゲートだとプレビューでもログインを求められ
編集できなくなる。`useSetupGate` はプレビュー（`isDanPreview()`）を検出して自動でバイパスする。
実例: `artifacts/salonboard-styleup/page.tsx`。

### 1-5. Tailwind のスキャン漏れ

`artifacts/<slug>/` は `.gitignore` 対象で、Tailwind v4 の自動ソース検出は `.gitignore` を
尊重する。成果物の中でしか使わないクラス（`max-w-[34rem]`、`xl:` など）が **無言で無視**
される。`hook_register_artifact.py` が `scripts/wire_artifact_tailwind_sources.py` を自動で
走らせるが、手で slug を作った直後にレイアウトが効かない時はこれを実行する。

### 1-6. 登録＝公開、リンク、ドメイン

- `artifacts/<slug>/page.tsx` を書くと PostToolUse hook (`hook_register_artifact.py`) が
  dan-core の登録API (`POST /api/v1/chat/internal/artifacts/register`) に渡し、専用 Vercel
  プロジェクトへの公開まで保証される。公開URLは成果物カードの `share_url` に入る。
  hook 以外の場所（サンドボックスやスクリプトの裏方スレッド）で公開を起こさない。
  再公開は `POST /api/v1/chat/internal/artifacts/<artifact_id>/publish`。
  手動登録: `echo '{"tool_name":"Write","tool_input":{"file_path":"<絶対パス>"}}' | DAN_ROOM_ID=<room> DAN_PROJECT_ID=<project> python scripts/hook_register_artifact.py`
- 成果物内のページ間リンクは `next/link` ではなく `@/components/artifacts/artifact-link` の
  `ArtifactLink`（`/preview/<slug>`・`/artifacts/<slug>`・独自ドメインを混ぜないため）。
- 独自ドメインは middleware の `ARTIFACT_CUSTOM_DOMAINS` / `NEXT_PUBLIC_ARTIFACT_CUSTOM_DOMAINS`
  に `slug=domain.example` で追加。
- favicon は hook が自動生成して `layout.tsx` の `metadata.icons` に焼き込む。差し替えは
  `python scripts/set_artifact_icon.py --slug <slug> --image <path>`（画像生成は自分でやる）。

### 1-7. ダン管理画面（ダッシュボード）はダンの UI 体系に合わせる

ダンのダッシュボード内に置くページは既存画面と同じ操作感にするため、`globals.css` の
セマンティックトークン（`bg-background` `text-foreground` `text-muted-foreground`
`border-border` `bg-primary` …）と `frontend/src/components/ui/` の shadcn/ui、Lucide アイコン
を使う。チャートは shadcn の chart（Recharts）。サイドバーに導線を足す。

**これはダッシュボード限定**。クライアント HP・LP・ブランドページは成果物内で固有の配色・
書体・部品を自由に定義してよく、shadcn を使う義務はない。

### 1-8. 変更の分離

成果物と ダン infra は同じ commit に混ぜない（`CLAUDE.md` の Scope 規律）。
`DAN_DONE_ARTIFACTS_NATIVE_SLUGS`（kittoku 等）は `done-artifacts` リポジトリ直編集。

---

## 2. 判断材料（参考。案件に合わせて選ぶ・書き足す・使わない、すべて可）

### 2-1. 既存部品（`frontend/src/components/templates/`）

合えば使う。合わなければ書く。採用デザインを崩してまで押し込まない。
繰り返し使いそうな構造は templates に足す。

| 部品 | 用途 |
|---|---|
| `PageShell` / `LpShell` | 管理画面 / LP の外枠（LpShell = sticky nav + footer） |
| `Section` | セクションの縦リズム・見出し・max-width |
| `HeroSection` | ヒーロー（split / centered / stacked） |
| `HeroMedia` | 画像/動画ヒーロー。darken / blur / fade を媒体側 CSS で（1-3） |
| `FullBleedVideoHero` | 全幅動画ヒーロー。mobileSrc / poster / align / contentWidth |
| `ScrollVideo` | スクロール進捗で動画をスクラブ。chapters / progressBar / fallback |
| `FeatureGrid` | 特徴カードのグリッド |
| `ServiceShowcase` | サービス一覧。featuredIndex で 1 件を大きく |
| `CaseStudyGrid` | 事例グリッド（category / result） |
| `ProcessTimeline` | 手順・流れ |
| `ProofBar` | 数字・実績の帯（light / dark） |
| `ConversionCta` | 締めの CTA（primary / secondary / image） |
| `FaqSection` | FAQ |
| `InquiryForm` | 問い合わせフォーム（送信先 `/api/v1/inquiries`） |
| `LocationMap` | Google Maps iframe（APIキー不要） |
| `KpiCard` | KPI 表示 |
| `AIChatPanel` | 公開チャットUI（`scope` で API 側コンテキスト分岐） |
| `ImageSlicePage` | 画像タイル + 操作箇所オーバーレイ（画像ファースト方式の器） |
| typography: `HeroCopy` `VerticalHeroCopy` `SectionKicker` `SectionTitle` `LeadCopy` `BodyCopy` `MetaLabel` `EditorialButton` | 日本語組版（palt）済みの文字部品。縦書きヒーローあり |
| editorial-accents: `RoundelBadge` `SealMark` `RuleDivider` `BrushStroke` `InkCircle` `HandRule` `PhotoCaption` `InfoStrip` `EditorialFrame` | 装飾部品（印章・筆線・囲み・写真キャプション・情報帯） |

import: `import { HeroMedia, Section, ... } from "@/components/templates";`

機能ブロック:

| 機能 | 使うもの |
|---|---|
| ログイン/初期設定ゲート | `useSetupGate`（`@/hooks/use-setup-gate`。1-4） |
| 予約・カレンダー | `<BookingCalendar config={{ slug, openTime, closeTime, slotMinutes, services, staff, closedWeekdays }} />` + `useBooking`（API/DB 実装済み。実例 `artifacts/bookings`） |
| スクロール出現 | `FadeIn` / `Stagger` / `StaggerItem`（`@/components/motion`） |
| shadcn/ui の追加 | `@/components/ui/<name>` を import すれば hook が `npx shadcn add` を自動実行 |

導入済みライブラリ: Next 16 / React 19 / Tailwind v4 / shadcn/ui / lucide-react /
framer-motion / gsap / three + @react-three/fiber + drei / recharts。
足りないものは案件に必要なら入れてよい（重さと理由を報告する）。

### 2-2. 方式と技法（最初に決めるが、迷ったら作って見せて決める）

| 方式 | 内容 | レシピ |
|---|---|---|
| コードで作る（基本） | ネイティブ文字・レイアウト。写真・イラスト・テクスチャは画像素材 | `recipes/editable-lp.md`（LP）、`recipes/conversion-flat.md`（集客HP） |
| 画像素材の併用 | GPT Image 2 で写真・装飾・完成見本を作り、コードで再構成 | `recipes/editable-lp.md` |
| 画像ファースト（保守用） | 画像タイル + 操作箇所だけ HTML。既存画像LPの部分修正・品質比較のために残す | `recipes/image-first-lp.md` |
| スクロールナラティブ | GSAP ScrollTrigger + Lenis | `recipes/scroll-narrative.md` |
| スクロール動画ヒーロー | `ScrollVideo` + 生成動画 | `recipes/scroll-video.md` |
| 3D | R3F + drei | `recipes/3d-immersive.md` |

- 集客・問い合わせ目的で速度・SEO・モバイルが最優先なら軽い方式が無難。
  重い演出はユーザーが求めた時か、製品/ブランドが見せ場の時。
- 方式で結果が大きく変わる分岐だけ、平易な 2〜3 択を推奨つきで示してから着手する。
  それ以外の判断は自分で決め、完成後にフィードバックを受ける。
- 画像生成は `scripts/gpt_image.py`（OpenAI API 直。プロンプトは標準入力）。
  プロンプトに渡すのはユーザーの要望と実素材。デザインの方向性を足さない
  （ユーザーの feedback: 方向付けはユーザーがする）。実在しない数字・出典を描かせない。

### 2-3. 設計の考え方（思考の道具。成果物として提出する義務はない）

「信頼感のあるサイト」のような感情ラベルから始めず、次の連鎖で具体化すると迷いが減る:

ビジネスゴール → 訪問者にさせたい行動 → そのために訪問者が確信すべきこと →
確信を生む具体物（写真・数字・事例・地図） → それを最も効果的に見せる設計。

例: 飲食店なら「来店・予約」→「美味しそう・雰囲気が良い・場所がわかる・値段が妥当」→
料理写真を大きく、店内写真、メニューと価格、地図、営業時間 → 写真が主役でモバイルから
予約に即到達。

書き出したければ `artifacts/<slug>/DESIGN.md` に置く（任意）。

### 2-4. リファレンス（任意）

- ユーザーが参考サイト・画像・ロゴ・写真を出したら **最優先で使う**。WebFetch や browser で
  開いて把握する。提供素材は AI 生成で代替せず実際に組み込む。
- ユーザー提供が無く方向が定まらない時だけ、実在サイトやギャラリーを見て候補を絞る。
  収集を必須工程にしない。

### 2-5. 落とし穴（AI らしさを避ける規則ではなく、実害が出たもの）

- 縦スクロール LP を PC 向けの横組みで作る。媒体（スマホ縦）を先に決める。
- CTA がモバイルで届かない。全セクションから問い合わせ・電話に到達できるか。
- 文字を画像に焼き込む（1-2）。編集不能になり、公開反映もできない。
- 座標固定で見本をなぞる。改行や文量変更で隣が覆われる。通常フロー・grid・flex で内容追従。
- ヒーローの上に overlay div（1-3）。
- 手書き `IntersectionObserver` で出現アニメ。`framer-motion` の `whileInView` か `FadeIn` で足りる。
- `prefers-reduced-motion` を無視する。スクロールジャックで戻れなくする。
- 重い技法で LCP を落とす。モバイルは静止画フォールバック、3D は遅延ロード。
- 均一なカード行列だけで全セクションを作って単調になる（写真・余白・文字の大小・構成の
  リズムで意図を出す）。ただし均一が案件の意図なら構わない。
- 絵文字をアイコン代わりにする（Lucide か SVG）。

### 2-6. ダッシュボード / 管理画面

- 1-7 の UI 体系。ページ外枠は `PageShell`、KPI 行 `KpiCard`、`Table` / `Card` グリッド、
  `Skeleton` / 空状態 / エラーの 3 状態。既存ダッシュボード（`artifacts/aix-dashboard` 等）が参考。
- 機能を伴う場合は DB → API → UI → 統合確認の順が整理しやすい（`create_feature` ツールが
  雛形を出す）。LP のようにバックエンドの無い成果物には無関係。

### 2-7. 提案書 HTML

ユーザーが「提案書 HTML 作って」と明示した時だけ `actions/proposal_html.md`。

---

## 3. 確認と納品（完了と言う前に）

手順は `actions/create.md`、確認項目は `criteria.md`。要点:

1. **実ブラウザで見る**: 390 / 768 / 1280px 程度でスクリーンショット。文字の読みやすさ、
   写真の切れ方、横溢れ、情報の順序と密度。比較元があれば同じ幅で並べる。
   `python scripts/editable_artifact.py audit --slug <slug> --origin http://localhost:3001`
   が 3 幅スクショ + 必須コピー欠落 / ID 重複 / 画像読込失敗 / 横溢れ / 公開データ接続を検査する。
2. **編集が効く**: 手動編集ONで見出しを長文に変えて崩れないか、画像差し替え、余白変更、
   再読み込み後に保存が残るか。
3. **機能が動く**: API に curl、ブラウザで作成→表示→編集→削除、3 状態。
4. **公開URL**: `share_url` を curl かブラウザで確認。「ローカルで動いた」は完了ではない。
5. **報告**: 品質・編集・保存・公開の検証を分けて書く。スクショを添付する。
   モックした保存テストを本番の証拠として書かない。

品質は自分の目で見て判断し、直せる欠陥は聞かずに直す。点数表は使わない。
判断が分かれる方向転換だけユーザーに委ねる。

---

## 4. 参照

| ファイル | 役割 |
|---|---|
| `actions/create.md` | 制作の流れ（要件整理 → 実装 → 確認 → 納品） |
| `criteria.md` | 確認項目（用途別） |
| `recipes/*.md` | 方式・技法ごとの手順と落とし穴 |
| `actions/proposal_html.md` | 提案書 HTML（明示要求時のみ） |
| `frontend/src/components/templates/index.ts` | 部品の正（この表より新しければそちらが正） |
