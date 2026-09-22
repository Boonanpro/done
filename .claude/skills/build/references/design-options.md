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

